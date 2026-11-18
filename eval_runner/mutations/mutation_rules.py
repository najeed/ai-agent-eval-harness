"""Semantic delivery proofs shared by issuance and detached trace verification."""

import json
from collections.abc import Mapping

PHASES = {
    "tool_contract": (
        "tool_arguments_modified",
        "tool_arguments_received",
        "tool_contract_rejected",
        "tool_consumer_received",
    ),
    "rollback_failure": ("compensation_scheduled", "compensation_dispatch_blocked"),
    "partial_commit": ("commit_proposed", "partial_commit_observed"),
    "stale_commit": ("revision_read", "competing_commit", "revision_guard_rejected"),
    "approval_stale": (
        "authorization_request",
        "authorization_expiry_observed",
        "authorization_attempt",
        "authorization_rejected",
        "authorization_cleanup",
    ),
    "approval_mismatch": (
        "authorization_request",
        "authorization_attempt",
        "authorization_rejected",
        "authorization_cleanup",
    ),
    "approval_replay": (
        "authorization_request",
        "authorization_consumed",
        "authorization_attempt",
        "authorization_rejected",
        "authorization_cleanup",
    ),
    "tool_response_corruption": (
        "tool_response_produced",
        "tool_response_modified",
        "tool_consumer_received",
    ),
    "timeout_boundary": (
        "tool_execution_requested",
        "tool_invocation_started",
        "tool_deadline_expired",
        "tool_consumer_received",
    ),
    "malformed_payload": ("tool_wire_received", "tool_parse_rejected", "tool_consumer_received"),
    "latency_jitter": (
        "tool_execution_requested",
        "tool_invocation_started",
        "tool_invocation_completed",
        "tool_delay_elapsed",
        "tool_consumer_received",
    ),
    "tool_duplicate": (
        "tool_execution_requested",
        "tool_invocation_started",
        "tool_invocation_completed",
        "tool_consumer_received",
    ),
    "tool_replay": ("tool_execution_requested", "tool_response_replayed", "tool_consumer_received"),
}

TOOL_FAULTS = frozenset(
    {
        "tool_contract",
        "timeout_boundary",
        "malformed_payload",
        "latency_jitter",
        "tool_duplicate",
        "tool_replay",
    }
)
for _fault in TOOL_FAULTS:
    _phases = PHASES[_fault]
    PHASES[_fault] = (*_phases[:-1], "tool_response_available", _phases[-1])


def _valid_response_chain(receipt, bound, index):
    rows = {row["kind"]: row["observation"] for row in bound}
    current = rows.get("tool_response_available", {}).get("payload_hash")
    if not isinstance(current, str) or not current:
        return False
    available = next(row for row in bound if row["kind"] == "tool_response_available")
    last_position = index.get(available.get("event_id"), (None, {}, -1))[2]
    for row in bound:
        if row["kind"] != "tool_response_transformed":
            continue
        change = row["observation"]
        ref = change.get("transformation_ref") or {}
        if not isinstance(ref, Mapping) or not isinstance(ref.get("event_id"), str):
            return False
        digest, source, source_position = index.get(ref.get("event_id"), (None, {}, -1))
        source_change = source.get("observation", {})
        if not isinstance(source_change, Mapping):
            return False
        if not (
            digest
            and digest == ref.get("evidence_hash")
            and source.get("kind") == "tool_response_modified"
            and source.get("fault") == "tool_response_corruption"
            and all(
                source.get(key) == receipt.get(key)
                for key in ("run_id", "node_id", "execution_instance_id")
            )
            and 0 <= last_position < source_position < index[row["event_id"]][2]
            and change.get("original_hash") == source_change.get("original_hash") == current
            and change.get("modified_hash") == source_change.get("modified_hash")
            and current != change.get("modified_hash")
        ):
            return False
        current = change["modified_hash"]
        last_position = index[row["event_id"]][2]
    return current == rows["tool_consumer_received"].get("expected_hash")


def valid_extended_observations(receipt, bound, index, position, hash_value):
    fault = receipt["fault"]
    rows = {row["kind"]: row["observation"] for row in bound}
    if any(not isinstance(row, Mapping) for row in rows.values()):
        return False
    if fault == "rollback_failure":
        scheduled, blocked = rows["compensation_scheduled"], rows["compensation_dispatch_blocked"]
        return (
            scheduled.get("compensating") is True
            and blocked == receipt.get("observed")
            and blocked.get("compensating") is True
            and blocked.get("handler_dispatched") is False
            and blocked.get("blocked_by_fault") is True
            and scheduled.get("parent_execution_id") == blocked.get("parent_execution_id")
            and isinstance(scheduled.get("parent_execution_id"), str)
            and bool(scheduled["parent_execution_id"])
        )
    if fault == "partial_commit":
        proposal, commit = rows["commit_proposed"], rows["partial_commit_observed"]
        before, after, proposed = (
            commit.get("before", {}),
            commit.get("after", {}),
            commit.get("proposed", {}),
        )
        applied, omitted = commit.get("applied_paths", []), commit.get("omitted_paths", [])
        before_exists, after_exists = commit.get("before_exists"), commit.get("after_exists")
        if (
            not isinstance(before_exists, Mapping)
            or not isinstance(after_exists, Mapping)
            or set(before_exists) != set(proposed)
            or set(after_exists) != set(proposed)
            or any(
                type(value) is not bool
                for value in (*before_exists.values(), *after_exists.values())
            )
        ):
            return False
        return (
            proposal.get("before") == before
            and proposal.get("before_exists") == before_exists
            and proposal.get("proposed") == proposed
            and proposal.get("applicable") is True
            and commit == receipt["observed"]
            and bool(applied)
            and bool(omitted)
            and not set(applied).intersection(omitted)
            and all(
                path in proposed
                and path in before
                and path in after
                and after_exists[path] is True
                and hash_value(after[path]) == hash_value(proposed[path])
                and (not before_exists[path] or hash_value(before[path]) != hash_value(after[path]))
                for path in applied
            )
            and all(
                path in proposed
                and path in before
                and path in after
                and after_exists[path] == before_exists[path]
                and hash_value(after[path]) == hash_value(before[path])
                and (
                    not before_exists[path]
                    or hash_value(before[path]) != hash_value(proposed[path])
                )
                for path in omitted
            )
        )
    if fault == "stale_commit":
        read, commit, rejected = (
            rows["revision_read"],
            rows["competing_commit"],
            rows["revision_guard_rejected"],
        )
        return (
            type(read.get("revision")) is int
            and commit.get("revision_before") == read["revision"]
            and commit.get("revision_after") == read["revision"] + 1
            and rejected.get("expected_revision") == read["revision"]
            and rejected.get("actual_revision") == commit["revision_after"]
            and rejected.get("blocked") is True
            and rejected == receipt["observed"]
        )
    if fault.startswith("approval_"):
        token = rows["authorization_request"].get("approval_token")
        if not token or any(row.get("approval_token") != token for row in rows.values()):
            return False
        request, attempt, rejected = (
            rows["authorization_request"],
            rows["authorization_attempt"],
            rows["authorization_rejected"],
        )
        code = {
            "approval_stale": "ApprovalExpired",
            "approval_mismatch": "ApprovalPayloadMismatch",
            "approval_replay": "ApprovalReplayBlocked",
        }[fault]
        valid = (
            rejected.get("code") == code
            and rejected.get("blocked") is True
            and rejected == receipt["observed"]
            and rows["authorization_cleanup"].get("status") == "REJECTED"
        )
        if fault == "approval_stale":
            expiry = rows["authorization_expiry_observed"]
            return (
                valid
                and type(expiry.get("expires_at")) in (float, int)
                and type(expiry.get("observed_at")) in (float, int)
                and type(attempt.get("attempted_at")) in (float, int)
                and expiry["expires_at"] <= expiry["observed_at"] <= attempt["attempted_at"]
                and expiry.get("payload_hash") == request.get("payload_hash")
            )
        if fault == "approval_mismatch":
            return (
                valid
                and bool(request.get("payload_hash"))
                and bool(attempt.get("payload_hash"))
                and request["payload_hash"] != attempt["payload_hash"]
            )
        consumption = rows["authorization_consumed"].get("consumption") or {}
        if not isinstance(consumption, Mapping):
            return False
        from eval_runner.approval_validation import payload_hash_matches

        return (
            valid
            and consumption.get("run_id") == receipt["run_id"]
            and payload_hash_matches(consumption.get("payload_hash"), attempt.get("payload_hash"))
            and bool(consumption.get("authorization_id"))
        )
    received = rows.get("tool_consumer_received", {})
    if (
        received != receipt["observed"]
        or received.get("consumer_received") is not True
        or not received.get("payload_hash")
        or received.get("payload_hash") != received.get("expected_hash")
    ):
        return False
    if fault in TOOL_FAULTS and not _valid_response_chain(receipt, bound, index):
        return False
    if fault == "tool_response_corruption":
        modified = rows["tool_response_modified"]
        return (
            bool(modified.get("original_hash"))
            and rows["tool_response_produced"].get("payload_hash") == modified["original_hash"]
            and modified["original_hash"] != modified.get("modified_hash")
            and modified.get("modified_hash") == received["payload_hash"]
        )
    if fault == "tool_contract":
        from .tool_contracts import contract_violation

        mutation, request, rejected = (
            rows["tool_arguments_modified"],
            rows["tool_arguments_received"],
            rows["tool_contract_rejected"],
        )
        return (
            mutation.get("original_hash") == hash_value(mutation.get("original_arguments"))
            and mutation.get("modified_hash") == request.get("arguments_hash")
            and mutation.get("original_hash") != mutation.get("modified_hash")
            and request.get("arguments_hash")
            == hash_value(request.get("arguments"))
            == rejected.get("arguments_hash")
            and rejected.get("blocked") is True
            and rejected.get("validator") == "additionalProperties"
            and contract_violation(
                request.get("schema"), request.get("arguments"), mutation.get("original_arguments")
            )
        )
    if fault == "malformed_payload":
        wire, rejected = rows["tool_wire_received"], rows["tool_parse_rejected"]
        if wire.get("raw_hash") != hash_value(wire.get("raw_payload")) or wire.get(
            "raw_hash"
        ) != rejected.get("raw_hash"):
            return False
        try:
            json.loads(wire["raw_payload"])
        except json.JSONDecodeError as exc:
            return (
                rejected.get("exception") == "JSONDecodeError"
                and rejected.get("position") == exc.pos
            )
        except (TypeError, UnicodeDecodeError):
            return False
        return False
    requested = rows["tool_execution_requested"]
    if requested.get("request_hash") != received.get("request_hash"):
        return False
    starts = [row["observation"] for row in bound if row["kind"] == "tool_invocation_started"]
    ends = [row["observation"] for row in bound if row["kind"] == "tool_invocation_completed"]
    if any(row.get("request_hash") != requested["request_hash"] for row in starts):
        return False
    if fault == "tool_replay":
        replayed = rows["tool_response_replayed"]
        ref = replayed.get("source_ref") or {}
        if not isinstance(ref, Mapping) or not isinstance(ref.get("event_id"), str):
            return False
        digest, source, source_position = index.get(ref.get("event_id"), (None, {}, -1))
        source_row = source.get("observation", {})
        if not isinstance(source_row, Mapping):
            return False
        replay_event = next(row for row in bound if row["kind"] == "tool_response_replayed")
        replay_position = index[replay_event["event_id"]][2]
        return (
            not starts
            and replayed.get("tool_dispatched") is False
            and source.get("kind") == "tool_response_delivered"
            and source.get("run_id") == receipt["run_id"]
            and digest == ref.get("evidence_hash")
            and 0 <= source_position < replay_position < position
            and source_row.get("consumer_received") is True
            and source_row.get("request_hash")
            == requested["request_hash"]
            == replayed.get("request_hash")
            and source_row.get("payload_hash")
            == replayed.get("payload_hash")
            == rows["tool_response_available"].get("payload_hash")
        )
    if not starts:
        return False
    if fault == "timeout_boundary":
        deadline = rows["tool_deadline_expired"]
        return (
            type(requested.get("timeout_ms")) in (float, int)
            and requested["timeout_ms"] > 0
            and deadline.get("timeout_ms") == requested["timeout_ms"]
            and deadline.get("task_cancelled") is True
            and deadline.get("response_withheld") is True
            and deadline.get("elapsed_seconds", -1) >= requested["timeout_ms"] / 1000
        )
    if fault == "tool_duplicate":
        ids = [row.get("invocation_id") for row in starts]
        completed = [row.get("invocation_id") for row in ends]
        return (
            len(ids) == 2
            and len(set(ids)) == 2
            and ids == completed
            and all(row.get("result_hash") for row in ends)
        )
    delay = rows["tool_delay_elapsed"]
    return (
        bool(starts)
        and len(starts) == len(ends)
        and [row.get("invocation_id") for row in starts]
        == [row.get("invocation_id") for row in ends]
        and type(delay.get("requested_seconds")) in (float, int)
        and delay["requested_seconds"] > 0
        and delay.get("elapsed_seconds", -1) >= delay["requested_seconds"]
    )
