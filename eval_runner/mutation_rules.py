"""Semantic delivery proofs shared by issuance and detached trace verification."""

import json
from collections.abc import Mapping

PHASES = {
    "partial_commit": ("commit_proposed", "partial_commit_observed"),
    "stale_commit": ("revision_read", "competing_commit", "revision_guard_rejected"),
    "approval_stale": (
        "authorization_request",
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


def valid_extended_observations(receipt, bound, index, position, hash_value):
    fault = receipt["fault"]
    rows = {row["kind"]: row["observation"] for row in bound}
    if any(not isinstance(row, Mapping) for row in rows.values()):
        return False
    if fault == "partial_commit":
        proposal, commit = rows["commit_proposed"], rows["partial_commit_observed"]
        before, after, proposed = (
            commit.get("before", {}),
            commit.get("after", {}),
            commit.get("proposed", {}),
        )
        applied, omitted = commit.get("applied_paths", []), commit.get("omitted_paths", [])
        return (
            proposal.get("before") == before
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
                and before[path] != after[path] == proposed[path]
                for path in applied
            )
            and all(
                path in proposed and path in after and after[path] == before[path] != proposed[path]
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
            return (
                valid
                and type(request.get("expires_at")) in (float, int)
                and type(attempt.get("attempted_at")) in (float, int)
                and request["expires_at"] <= attempt["attempted_at"]
            )
        if fault == "approval_mismatch":
            return (
                valid
                and bool(request.get("payload_hash"))
                and bool(attempt.get("payload_hash"))
                and request["payload_hash"] != attempt["payload_hash"]
            )
        consumption = rows["authorization_consumed"].get("consumption") or {}
        return (
            valid
            and consumption.get("run_id") == receipt["run_id"]
            and consumption.get("payload_hash") == attempt.get("payload_hash")
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
    if fault == "tool_response_corruption":
        modified = rows["tool_response_modified"]
        return (
            bool(modified.get("original_hash"))
            and rows["tool_response_produced"].get("payload_hash") == modified["original_hash"]
            and modified["original_hash"] != modified.get("modified_hash")
            and modified.get("modified_hash") == received["payload_hash"]
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
        digest, source, source_position = index.get(ref.get("event_id"), (None, {}, -1))
        source_row = source.get("observation", {})
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
            == received["payload_hash"]
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
