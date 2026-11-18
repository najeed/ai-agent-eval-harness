"""Independent validation of execution-bound mutation delivery evidence."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from agentv_runtime.canonical import canonical_json_encode
from eval_runner.mutations.mutation_rules import PHASES, valid_extended_observations

BOUNDARY_FAULTS = frozenset(
    {"cancel_race", "commit_after_cancel", "approval_race", "approval_revocation", *PHASES}
)


def evidence_hash(value):
    return "sha3_256:" + hashlib.sha3_256(canonical_json_encode(value)).hexdigest()


def fault_receipt_failures(events, required_faults=(), *, run_id=None):
    """Recompute receipt commitments and resolve evidence only within the recorded trace."""
    index = {}
    delivered = set()
    executions = {}
    compensations = set()
    failures = []
    for position, event in enumerate(events or []):
        if not isinstance(event, Mapping):
            failures.append("InvalidMutationDeliveryEvent")
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else event
        if event.get("event") == "execution_graph_node" and data.get("status") in (
            "completed",
            "failed",
            "success",
            "failure",
        ):
            node = data.get("scenario_node_id") or data.get("node_id")
            execution = data.get("execution_instance_id")
            if isinstance(node, str) and isinstance(execution, str) and execution:
                executions.setdefault(node, set()).add(execution)
                if data.get("compensating") is True:
                    compensations.add(execution)
        if event.get("event") == "runtime_fault_observation":
            evidence = data.get("evidence") or {}
            if (
                not isinstance(evidence, Mapping)
                or not isinstance(evidence.get("event_id"), str)
                or not evidence["event_id"]
                or not isinstance(evidence.get("kind"), str)
            ):
                failures.append("InvalidMutationObservation")
                continue
            try:
                digest = evidence_hash(evidence)
            except (TypeError, ValueError):
                failures.append("InvalidMutationObservation")
                continue
            if evidence.get("event_id") in index:
                failures.append("DuplicateMutationObservation")
                index[evidence["event_id"]] = (None, {}, -1)
            elif data.get("evidence_hash") == digest:
                index[evidence.get("event_id")] = (digest, evidence, position)
        if event.get("event") != "mutation_delivery" and not (
            isinstance(data.get("mutation_receipt"), Mapping)
            and data["mutation_receipt"].get("delivery") == "DELIVERED"
        ):
            continue
        receipt = data.get("mutation_receipt") or {}
        if not isinstance(receipt, Mapping):
            failures.append("InvalidMutationDeliveryReceipt")
            continue
        if not isinstance(receipt.get("fault"), str):
            failures.append("InvalidMutationDeliveryReceipt")
            continue
        if receipt["fault"] not in BOUNDARY_FAULTS:
            failures.append(f"UnsupportedMutationDeliveryReceipt:{receipt['fault']}")
            continue
        unsigned = {key: value for key, value in receipt.items() if key != "receipt_hash"}
        refs = receipt.get("evidence_refs") or []
        bound = []
        try:
            actual_receipt_hash = evidence_hash(unsigned)
        except (TypeError, ValueError):
            failures.append("InvalidMutationDeliveryReceipt")
            continue
        valid = (
            isinstance(refs, list)
            and bool(refs)
            and receipt.get("receipt_hash") == actual_receipt_hash
            and isinstance(receipt.get("delivery"), str)
            and receipt.get("delivery") in {"DELIVERED", "NOT_DELIVERED"}
        )
        valid = (
            valid
            and all(
                isinstance(receipt.get(key), str) and bool(receipt[key])
                for key in (
                    "fault_id",
                    "run_id",
                    "node_id",
                    "execution_instance_id",
                )
            )
            and (run_id is None or receipt.get("run_id") == run_id)
        )
        if not isinstance(refs, list):
            refs = []
        observed_positions = {}
        referenced_ids = set()
        previous_position = -1
        for ref in refs:
            if not isinstance(ref, Mapping) or not isinstance(ref.get("event_id"), str):
                valid = False
                continue
            digest, evidence, observed_position = index.get(ref.get("event_id"), (None, {}, -1))
            valid = (
                valid
                and digest == ref.get("evidence_hash")
                and 0 <= observed_position < position
                and previous_position < observed_position
                and ref["event_id"] not in referenced_ids
                and all(
                    evidence.get(key) == receipt.get(key)
                    for key in ("fault_id", "fault", "run_id", "node_id", "execution_instance_id")
                )
            )
            bound.append(evidence)
            referenced_ids.add(ref["event_id"])
            previous_position = observed_position
            observed_positions[evidence.get("kind")] = observed_position
        phase_order = {
            "cancel_race": ["cancellation_requested"],
            "commit_after_cancel": ["cancellation_requested", "state_commit_observed"],
            "approval_race": ["approval_before", "approval_race_observed"],
            "approval_revocation": [
                "approval_before",
                "approval_granted",
                "approval_revoked",
                "approval_replay_blocked",
            ],
            **PHASES,
        }[receipt["fault"]]
        # An observed attempt can legitimately be inapplicable or restored by
        # later middleware; it cannot satisfy a required delivery proof.
        if receipt.get("delivery") == "NOT_DELIVERED":
            if not valid:
                failures.append(f"InvalidMutationDeliveryEvidence:{receipt.get('fault_id')}")
            continue
        valid = valid and set(phase_order).issubset({row.get("kind") for row in bound})
        phase_positions = [observed_positions.get(kind, -1) for kind in phase_order]
        valid = valid and all(
            a < b for a, b in zip(phase_positions, phase_positions[1:], strict=False)
        )
        observations = {row.get("kind"): row.get("observation") for row in bound}
        if receipt["fault"] in PHASES:
            try:
                valid = valid and valid_extended_observations(
                    receipt, bound, index, position, evidence_hash
                )
            except (KeyError, TypeError, ValueError, IndexError, OverflowError):
                # Malformed detached artifacts are invalid proofs, never runtime errors.
                valid = False
        else:
            valid = valid and _valid_fault_observations(receipt, observations)
        if not valid:
            failures.append(f"InvalidMutationDeliveryEvidence:{receipt.get('fault_id')}")
        elif receipt.get("delivery") == "DELIVERED":
            delivered.add((receipt["fault"], receipt["node_id"], receipt["execution_instance_id"]))
    for requirement in required_faults:
        fault, node = requirement if isinstance(requirement, tuple) else (requirement, None)
        found = {
            execution
            for found_fault, found_node, execution in delivered
            if found_fault == fault and (node is None or found_node == node)
        }
        expected = executions.get(node, set())
        if fault == "rollback_failure":
            expected = compensations if node is None else expected.intersection(compensations)
        if not found or not expected.issubset(found):
            failures.append(f"MutationDeliveryEvidenceMissing:{fault}:{node or '*'}")
    return failures


def _valid_fault_observations(receipt, observations):
    if any(not isinstance(row, Mapping) for row in observations.values()):
        return False
    fault = receipt["fault"]
    observed = receipt.get("observed")
    if not isinstance(observed, Mapping):
        return False
    if fault in {"cancel_race", "commit_after_cancel"}:
        cancellation = observations.get("cancellation_requested", {})
        if cancellation.get("cancelled") is not True:
            return False
        if fault == "cancel_race":
            return (
                cancellation.get("tool_dispatched") is False
                and observed.get("tool_dispatched") is False
                and observed.get("cancelled") is True
                and cancellation.get("tool") == observed.get("tool")
            )
        commit = observations.get("state_commit_observed", {})
        return (
            commit == observed
            and commit.get("cancelled") is True
            and bool(commit.get("after_hash"))
            and bool(commit.get("before_hash"))
            and commit["after_hash"] != commit["before_hash"]
            and bool(commit.get("diff_hash"))
        )
    token = observed.get("approval_token")
    if not token or any(row.get("approval_token") != token for row in observations.values()):
        return False
    if fault == "approval_revocation":
        return (
            observations.get("approval_granted", {}).get("status") == "APPROVED"
            and observations.get("approval_revoked", {}).get("status") == "REJECTED"
            and observations.get("approval_replay_blocked", {}).get("blocked") is True
            and observed.get("status") == "REJECTED"
            and observed.get("replay_blocked") is True
        )
    race = observations.get("approval_race_observed", {})
    contenders = race.get("contenders")
    if (
        not isinstance(contenders, list)
        or len(contenders) != 2
        or any(not isinstance(row, Mapping) for row in contenders)
    ):
        return False
    if any(
        type(row.get("accepted")) is not bool or not isinstance(row.get("decision"), str)
        for row in contenders
    ):
        return False
    winners = [row for row in contenders if row.get("accepted") is True]
    return (
        observations.get("approval_before", {}).get("status") == "PENDING"
        and {row.get("decision") for row in contenders} == {"APPROVED", "REJECTED"}
        and len(winners) == 1
        and race.get("status") == winners[0]["decision"]
        and observed.get("contenders") == contenders
        and observed.get("winner") == race.get("status")
        and observed.get("status") == "REJECTED"
        and (
            race.get("status") == "REJECTED"
            or observations.get("approval_race_cleanup", {}).get("status") == "REJECTED"
        )
    )
