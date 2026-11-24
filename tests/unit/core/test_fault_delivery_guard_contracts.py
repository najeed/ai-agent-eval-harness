"""Behavioral regressions for malformed inputs and truthful fault evidence."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from eval_runner.approval_validation import payload_hash_matches
from eval_runner.events import CoreEvents
from eval_runner.execution_ir import compile_evaluation_plan
from eval_runner.mutations.mutation_evidence import evidence_hash
from eval_runner.mutations.mutation_registry import required_deliveries
from eval_runner.mutations.mutation_rules import (
    _valid_response_chain,
    valid_extended_observations,
)
from eval_runner.mutations.tool_contracts import FORBIDDEN_PROPERTY, contract_violation
from eval_runner.session_components.security_evidence import record_security_rejection


@pytest.mark.parametrize("left,right", [(None, "digest"), ("digest", None), (42, "42"), ("42", 42)])
def test_payload_hash_requires_two_string_values(left, right):
    assert payload_hash_matches(left, right) is False


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ("sha3_256:digest", "digest", True),
        ("digest", "sha3_256:digest", True),
        ("digest", "different", False),
        ("", "", False),
        ("non-ascii-\u00e9", "non-ascii-\u00e9", False),
    ],
)
def test_payload_hash_string_comparison_controls(left, right, expected):
    assert payload_hash_matches(left, right) is expected


@pytest.mark.parametrize("payload_hash", [42, True, ["digest"], {"digest": "value"}, None, ""])
def test_response_chain_rejects_non_string_or_empty_hash_even_when_consumer_matches(payload_hash):
    bound = [
        {
            "kind": "tool_response_available",
            "event_id": "available",
            "observation": {"payload_hash": payload_hash},
        },
        {
            "kind": "tool_consumer_received",
            "event_id": "consumer",
            "observation": {"expected_hash": payload_hash},
        },
    ]
    assert _valid_response_chain({}, bound, {}) is False


def test_response_chain_accepts_bound_string_and_rejects_changed_consumer():
    bound = [
        {
            "kind": "tool_response_available",
            "event_id": "available",
            "observation": {"payload_hash": "digest"},
        },
        {"kind": "tool_consumer_received", "observation": {"expected_hash": "digest"}},
    ]
    assert _valid_response_chain({}, bound, {}) is True
    bound[1]["observation"]["expected_hash"] = "different"
    assert _valid_response_chain({}, bound, {}) is False


@pytest.mark.parametrize(
    "defect",
    [
        "source_fault",
        "source_kind",
        "source_run",
        "source_node",
        "source_execution",
        "reference_digest",
        "source_order",
        "transformation_order",
        "source_original_hash",
        "source_modified_hash",
        "unchanged_payload",
        "consumer_hash",
        "missing_source",
        "reference_not_mapping",
        "reference_missing_id",
        "reference_non_string_id",
    ],
)
def test_response_transformation_requires_complete_bound_provenance(defect):
    receipt = {
        "run_id": "response-run",
        "node_id": "review",
        "execution_instance_id": "review:1",
        "fault": "tool_replay",
    }
    original = evidence_hash({"value": "original"})
    modified = evidence_hash({"value": "modified"})
    available = {
        "event_id": "available",
        "kind": "tool_response_available",
        "observation": {"payload_hash": original},
    }
    source = {
        **receipt,
        "event_id": "modification",
        "kind": "tool_response_modified",
        "fault": "tool_response_corruption",
        "observation": {"original_hash": original, "modified_hash": modified},
    }
    transformed = {
        "event_id": "transformation",
        "kind": "tool_response_transformed",
        "observation": {
            "original_hash": original,
            "modified_hash": modified,
            "transformation_ref": {"event_id": "modification"},
        },
    }
    consumer = {
        "event_id": "consumer",
        "kind": "tool_consumer_received",
        "observation": {"expected_hash": modified},
    }
    bound = [available, transformed, consumer]
    reference = transformed["observation"]["transformation_ref"]

    def bind_index(source_position=1, transformation_position=2):
        digest = evidence_hash(source)
        reference["evidence_hash"] = digest
        return {
            "available": (evidence_hash(available), available, 0),
            "modification": (digest, source, source_position),
            "transformation": (evidence_hash(transformed), transformed, transformation_position),
            "consumer": (evidence_hash(consumer), consumer, 3),
        }

    assert _valid_response_chain(receipt, bound, bind_index()) is True
    if defect == "source_fault":
        source["fault"] = "tool_duplicate"
    elif defect == "source_kind":
        source["kind"] = "tool_response_available"
    elif defect in {"source_run", "source_node", "source_execution"}:
        key = {
            "source_run": "run_id",
            "source_node": "node_id",
            "source_execution": "execution_instance_id",
        }[defect]
        source[key] = "unrelated-context"
    elif defect == "source_original_hash":
        source["observation"]["original_hash"] = evidence_hash("other-original")
    elif defect == "source_modified_hash":
        source["observation"]["modified_hash"] = evidence_hash("other-modified")
    elif defect == "unchanged_payload":
        source["observation"]["modified_hash"] = original
        transformed["observation"]["modified_hash"] = original
        consumer["observation"]["expected_hash"] = original
    elif defect == "consumer_hash":
        consumer["observation"]["expected_hash"] = original

    # Rebind every changed source's digest. Rejection must establish semantic
    # provenance, not merely notice that a copied evidence hash went stale.
    index = bind_index(
        0 if defect == "source_order" else 1, 1 if defect == "transformation_order" else 2
    )
    if defect == "reference_digest":
        reference["evidence_hash"] = evidence_hash("forged-reference")
    elif defect == "missing_source":
        index.pop("modification")
    elif defect == "reference_not_mapping":
        transformed["observation"]["transformation_ref"] = ["modification"]
    elif defect == "reference_missing_id":
        reference.pop("event_id")
    elif defect == "reference_non_string_id":
        reference["event_id"] = 42
    assert _valid_response_chain(receipt, bound, index) is False


@pytest.mark.parametrize("malformed", [None, "not-a-mapping", 42, []])
def test_valid_rollback_receipt_rejects_one_unrelated_malformed_observation(malformed):
    scheduled = {"compensating": True, "parent_execution_id": "parent:1"}
    blocked = {**scheduled, "handler_dispatched": False, "blocked_by_fault": True}
    receipt = {"fault": "rollback_failure", "observed": blocked}
    bound = [
        {"kind": "compensation_scheduled", "observation": scheduled},
        {"kind": "compensation_dispatch_blocked", "observation": blocked},
    ]
    assert valid_extended_observations(receipt, bound, {}, 0, str) is True
    bound.append({"kind": "unrelated_observation", "observation": malformed})
    assert valid_extended_observations(receipt, bound, {}, 0, str) is False


@pytest.mark.parametrize(
    "flags,expected",
    [
        ({"injected_latency_ms": 1}, {("latency_jitter", "review")}),
        ({"timeout_boundary_ms": 1}, {("timeout_boundary", "review")}),
        ({"injected_latency_ms": 2, "timeout_boundary_ms": 1}, {("timeout_boundary", "review")}),
        (
            {"timeout_boundary_ms": 1, "duplicate_execution": True},
            {("timeout_boundary", "review"), ("tool_duplicate", "review")},
        ),
    ],
)
def test_deadline_stimulus_does_not_erase_independent_fault_requirements(flags, expected):
    assert required_deliveries({"workflow": {"nodes": [{"id": "review", **flags}]}}) == expected


def test_unrelated_schema_violation_is_not_injected_contract_delivery():
    schema = {
        "type": "object",
        "properties": {"amount": {"type": "integer"}},
        "additionalProperties": False,
    }
    original = {"amount": 10}
    assert contract_violation(schema, {**original, FORBIDDEN_PROPERTY: True}, original) is True
    assert contract_violation(schema, {**original, "unrelated_extra": True}, original) is False


@pytest.mark.parametrize("with_plan", [False, True])
def test_security_denial_evidence_records_rejected_not_approved_for_every_oracle(with_plan):
    plan = (
        compile_evaluation_plan(
            {
                "workflow": {
                    "nodes": [
                        {
                            "id": "review",
                            "expected_outcome": [
                                {
                                    "oracle_id": "policy:review",
                                    "target": "message",
                                    "expected": "ok",
                                }
                            ],
                        }
                    ],
                    "edges": [],
                }
            }
        )
        if with_plan
        else None
    )
    bus = SimpleNamespace(emit=Mock())
    results = record_security_rejection(
        bus, "denied-run", "review", "approval_boundary", "approval denied", "security", plan
    )
    assert len(results) == (2 if with_plan else 1)
    assert results[0]["oracle_id"] == "security:approval_boundary"
    assert len(bus.emit.call_args_list) == len(results)
    for result, call in zip(results, bus.emit.call_args_list, strict=True):
        assert result["outcome"] == "FAIL"
        assert result["expected"] == "ALLOWED"
        assert result["observed"] == "REJECTED"
        assert result["requiredness"] == "REQUIRED"
        assert call.args[0] == CoreEvents.ASSERTION_EVALUATED
        assert call.args[1]["observed"] == "REJECTED"
        assert call.args[1]["passed"] is False


def test_security_rejection_skips_duplicate_primary_oracle_id():
    from eval_runner.session_components.security_evidence import security_rejection_oracles

    plan = SimpleNamespace(
        required_oracles_for_node=lambda _node_id: [
            SimpleNamespace(oracle_id="security:approval_boundary", resolver="security"),
            SimpleNamespace(oracle_id="policy:review", resolver=None),
        ]
    )
    results = security_rejection_oracles(
        "review", "approval_boundary", "denied", "sec_resolver", plan
    )
    assert [row["oracle_id"] for row in results] == [
        "security:approval_boundary",
        "policy:review",
    ]
    assert results[1]["resolver"] == "sec_resolver"


def test_tool_contracts_rejects_invalid_and_unresolvable_schemas():
    from eval_runner.mutations.tool_contracts import argument_error

    with pytest.raises(ValueError, match="Tool schema is invalid"):
        argument_error({"type": 12345}, {})

    with pytest.raises(ValueError, match="Tool schema is invalid"):
        argument_error({"$ref": "https://example.invalid/missing.schema.json"}, {})


def test_mutation_evidence_malformed_and_edge_paths():
    from unittest.mock import patch

    from eval_runner.mutations.mutation_evidence import evidence_hash, fault_receipt_failures
    from eval_runner.mutations.mutation_rules import PHASES

    phase_names = PHASES["tool_response_corruption"]
    refs = []
    events_prefix = []
    for idx, kind in enumerate(phase_names):
        ev_id = f"ev_{idx}"
        row = {
            "event_id": ev_id,
            "kind": kind,
            "fault_id": "f2",
            "fault": "tool_response_corruption",
            "run_id": "r1",
            "node_id": "n1",
            "execution_instance_id": "x1",
        }
        h = evidence_hash(row)
        refs.append({"event_id": ev_id, "evidence_hash": h})
        events_prefix.append(
            {"event": "runtime_fault_observation", "evidence": row, "evidence_hash": h}
        )

    obs = {"event_id": "e1", "kind": "k1"}
    good_hash = evidence_hash(obs)
    bad_receipt = {
        "fault": "tool_response_corruption",
        "fault_id": "f1",
        "run_id": "r1",
        "node_id": "n1",
        "execution_instance_id": "x1",
        "delivery": "NOT_DELIVERED",
        "evidence_refs": [],
        "receipt_hash": "sha3_256:bad",
    }
    phase_receipt_unsigned = {
        "fault": "tool_response_corruption",
        "fault_id": "f2",
        "run_id": "r1",
        "node_id": "n1",
        "execution_instance_id": "x1",
        "delivery": "DELIVERED",
        "evidence_refs": refs,
    }
    phase_receipt = {
        **phase_receipt_unsigned,
        "receipt_hash": evidence_hash(phase_receipt_unsigned),
    }
    events = [
        "not-a-dict",
        {
            "event": "runtime_fault_observation",
            "evidence": {"event_id": "bad", "kind": "k", "v": float("nan")},
        },
        {"event": "runtime_fault_observation", "evidence": obs, "evidence_hash": good_hash},
        {"event": "runtime_fault_observation", "evidence": obs, "evidence_hash": good_hash},
        {
            "event": "runtime_fault_observation",
            "evidence": {"event_id": "e2", "kind": "k2"},
            "evidence_hash": "wrong",
        },
        *events_prefix,
        {"event": "mutation_delivery", "mutation_receipt": "not-a-mapping"},
        {
            "event": "mutation_delivery",
            "mutation_receipt": {"fault": "cancel_race", "bad": float("nan")},
        },
        {"event": "mutation_delivery", "mutation_receipt": bad_receipt},
        {"event": "mutation_delivery", "mutation_receipt": phase_receipt},
    ]
    with patch(
        "eval_runner.mutations.mutation_evidence.valid_extended_observations",
        side_effect=ValueError("boom"),
    ):
        failures = fault_receipt_failures(events)
    assert "InvalidMutationDeliveryEvent" in failures
    assert "InvalidMutationObservation" in failures
    assert "DuplicateMutationObservation" in failures
    assert failures.count("InvalidMutationDeliveryReceipt") == 2
    assert "InvalidMutationDeliveryEvidence:f1" in failures
    assert "InvalidMutationDeliveryEvidence:f2" in failures


def test_mutation_rules_edge_guards():
    from eval_runner.mutations.mutation_evidence import evidence_hash
    from eval_runner.mutations.mutation_rules import valid_extended_observations

    avail = {
        "event_id": "av",
        "kind": "tool_response_available",
        "observation": {"payload_hash": "p"},
    }
    req = {"kind": "tool_execution_requested", "observation": {"request_hash": "r1"}}
    rec_obs = {
        "request_hash": "r2",
        "consumer_received": True,
        "payload_hash": "p",
        "expected_hash": "p",
    }
    rec = {"kind": "tool_consumer_received", "observation": rec_obs}
    index = {
        "av": (evidence_hash(avail), avail, 0),
        "src": (evidence_hash({"observation": "bad"}), {"observation": "bad"}, 0),
    }

    # TypeError / valid JSON in malformed_payload (lines 300-302)
    for raw_payload in (123, "{}"):
        raw_hash = evidence_hash(raw_payload)
        mal_bound = [
            avail,
            {
                "kind": "tool_wire_received",
                "observation": {"raw_payload": raw_payload, "raw_hash": raw_hash},
            },
            {"kind": "tool_parse_rejected", "observation": {"raw_hash": raw_hash}},
            rec,
        ]
        assert (
            valid_extended_observations(
                {"fault": "malformed_payload", "observed": rec_obs},
                mal_bound,
                index,
                5,
                evidence_hash,
            )
            is False
        )

    # Mismatched request_hash (line 305)
    assert (
        valid_extended_observations(
            {"fault": "tool_duplicate", "observed": rec_obs},
            [avail, req, rec],
            index,
            5,
            evidence_hash,
        )
        is False
    )

    # Mismatched start request_hash (line 309)
    rec_match_obs = {
        "request_hash": "r1",
        "consumer_received": True,
        "payload_hash": "p",
        "expected_hash": "p",
    }
    rec_match = {"kind": "tool_consumer_received", "observation": rec_match_obs}
    bad_start = {"kind": "tool_invocation_started", "observation": {"request_hash": "other"}}
    assert (
        valid_extended_observations(
            {"fault": "tool_duplicate", "observed": rec_match_obs},
            [avail, req, bad_start, rec_match],
            index,
            5,
            evidence_hash,
        )
        is False
    )

    # Missing starts for tool_duplicate (line 337)
    assert (
        valid_extended_observations(
            {"fault": "tool_duplicate", "observed": rec_match_obs},
            [avail, req, rec_match],
            index,
            5,
            evidence_hash,
        )
        is False
    )

    # Non-mapping source_change in _valid_response_chain (line 96)
    good_start = {"kind": "tool_invocation_started", "observation": {"request_hash": "r1"}}
    trans = {
        "kind": "tool_response_transformed",
        "observation": {"transformation_ref": {"event_id": "src"}},
    }
    assert (
        valid_extended_observations(
            {"fault": "tool_duplicate", "observed": rec_match_obs},
            [avail, req, good_start, trans, rec_match],
            index,
            5,
            evidence_hash,
        )
        is False
    )

    # Non-mapping source_row for tool_replay (line 318)
    rep = {
        "event_id": "rp",
        "kind": "tool_response_replayed",
        "observation": {"source_ref": {"event_id": "src"}},
    }
    assert (
        valid_extended_observations(
            {"fault": "tool_replay", "observed": rec_match_obs},
            [avail, req, rep, rec_match],
            index,
            5,
            evidence_hash,
        )
        is False
    )


def test_approval_and_runtime_fault_guard_errors():
    from unittest.mock import MagicMock, patch

    from eval_runner.mutations.approval_faults import deliver_authorization_fault
    from eval_runner.mutations.runtime_faults import FaultDeliveryController, FaultDeliveryError

    bus = SimpleNamespace(emit_evidence=Mock(), run_id="run-1")
    ctrl = FaultDeliveryController("run-1", bus)

    # Runtime faults guards: 88, 111, 114, 151, 179, 202, 208, 243-245, 260, 263, 277
    ctrl.cancellation_event = SimpleNamespace(set=lambda: None, is_set=lambda: False)
    with pytest.raises(FaultDeliveryError, match="not acknowledged"):
        ctrl.cancel_at_tool_boundary("n1", "write")
    with pytest.raises(FaultDeliveryError, match="nonempty proposed write"):
        ctrl.prepare_cancelled_commit("n1", {}, {})
    with pytest.raises(FaultDeliveryError, match="not acknowledged"):
        ctrl.prepare_cancelled_commit("n1", {}, {"a": 1})
    with pytest.raises(FaultDeliveryError, match="Not an approval-boundary fault"):
        ctrl.approval_fault(
            "bad_fault", MagicMock(), SimpleNamespace(approval_token="t"), node_id="n1"
        )
    with pytest.raises(FaultDeliveryError, match="Not an approval-boundary fault"):
        ctrl._execute_approval_fault(
            "bad_fault", MagicMock(), SimpleNamespace(approval_token="t"), node_id="n1"
        )

    # Approval race & revocation guards
    store_no_revoke = SimpleNamespace(
        get_request=lambda *_a, **_k: SimpleNamespace(
            run_id="run-1",
            status="PENDING",
            outbound_payload_hash="h",
            checkpoint_id="c",
            scope_digest="s",
            to_dict=lambda: {},
        )
    )
    with pytest.raises(FaultDeliveryError, match="durable revocation"):
        ctrl._execute_approval_fault(
            "approval_revocation",
            store_no_revoke,
            SimpleNamespace(approval_token="t"),
            node_id="n1",
        )
    with pytest.raises(FaultDeliveryError, match="withdraw its test grant"):
        ctrl._execute_approval_fault(
            "approval_race", store_no_revoke, SimpleNamespace(approval_token="t"), node_id="n1"
        )

    store_rejected = SimpleNamespace(
        get_request=lambda *_a, **_k: SimpleNamespace(
            run_id="run-1",
            status="REJECTED",
            outbound_payload_hash="h",
            checkpoint_id="c",
            scope_digest="s",
            to_dict=lambda: {},
        ),
        revoke_request=lambda *_a, **_k: None,
    )
    with pytest.raises(FaultDeliveryError, match="granted approval"):
        ctrl._execute_approval_fault(
            "approval_revocation", store_rejected, SimpleNamespace(approval_token="t"), node_id="n1"
        )
    with pytest.raises(FaultDeliveryError, match="unresolved durable request"):
        ctrl._execute_approval_fault(
            "approval_race", store_rejected, SimpleNamespace(approval_token="t"), node_id="n1"
        )

    # Approval replay / stale guards in approval_faults.py
    import time

    from eval_runner.approval_validation import ApprovalValidationError

    req = SimpleNamespace(approval_token="tok")
    future_exp = time.time() + 3600
    approved_rec = SimpleNamespace(
        run_id="run-1",
        status="APPROVED",
        action_payload={"a": 1},
        outbound_payload_hash="h",
        metadata={
            "expires_at": future_exp,
            "consumption": {"run_id": "run-1", "payload_hash": "h", "authorization_id": "a1"},
        },
        to_dict=lambda: {"status": "APPROVED"},
    )
    store_no_expire = SimpleNamespace(
        get_request=lambda *_a, **_k: approved_rec,
        consume_request=lambda *_a, **_k: approved_rec,
        revoke_request=lambda *_a, **_k: approved_rec,
    )
    with pytest.raises(FaultDeliveryError, match="durable expiry"):
        deliver_authorization_fault(ctrl, "approval_stale", store_no_expire, req, None, "n1", "e1")

    store_expire_not_observed = SimpleNamespace(
        get_request=lambda *_a, **_k: approved_rec,
        consume_request=lambda *_a, **_k: approved_rec,
        revoke_request=lambda *_a, **_k: approved_rec,
        expire_request=lambda *_a, **_k: None,
    )
    with pytest.raises(FaultDeliveryError, match="expiry was not observed"):
        deliver_authorization_fault(
            ctrl, "approval_stale", store_expire_not_observed, req, None, "n1", "e1"
        )

    with patch(
        "eval_runner.mutations.approval_faults.validate_expiry",
        side_effect=ApprovalValidationError("OtherCode"),
    ):
        with pytest.raises(ApprovalValidationError):
            deliver_authorization_fault(
                ctrl, "approval_stale", store_no_expire, req, None, "n1", "e1"
            )

    store_consume_other = SimpleNamespace(
        get_request=lambda *_a, **_k: approved_rec,
        consume_request=MagicMock(side_effect=ApprovalValidationError("OtherCode")),
        revoke_request=lambda *_a, **_k: approved_rec,
    )
    with pytest.raises(ApprovalValidationError):
        deliver_authorization_fault(
            ctrl, "approval_mismatch", store_consume_other, req, None, "n1", "e1"
        )

    with pytest.raises(FaultDeliveryError, match="unexpectedly accepted"):
        deliver_authorization_fault(
            ctrl, "approval_mismatch", store_no_expire, req, None, "n1", "e1"
        )

    # Revocation replay changed / unexpectedly reapproved (runtime_faults 243-245)
    approved_rev = SimpleNamespace(
        run_id="run-1",
        status="APPROVED",
        outbound_payload_hash="h",
        checkpoint_id="c",
        scope_digest="s",
        metadata={"revocation": True},
        to_dict=lambda: {"status": "APPROVED"},
    )
    rejected_rev = SimpleNamespace(
        run_id="run-1",
        status="REJECTED",
        outbound_payload_hash="h",
        checkpoint_id="c",
        scope_digest="s",
        metadata={"revocation": True},
        to_dict=lambda: {"status": "REJECTED"},
    )
    seq_rev = [approved_rev, rejected_rev, approved_rev]
    store_rev_changed = SimpleNamespace(
        get_request=lambda *_a, **_k: seq_rev.pop(0) if seq_rev else approved_rev,
        revoke_request=lambda *_a, **_k: rejected_rev,
        resolve_request=MagicMock(side_effect=ValueError("already rejected")),
    )
    with pytest.raises(FaultDeliveryError, match="changed during replay"):
        ctrl._execute_approval_fault(
            "approval_revocation",
            store_rev_changed,
            SimpleNamespace(approval_token="t"),
            node_id="n1",
        )

    seq_reapp = [approved_rev, rejected_rev]
    store_reapproved = SimpleNamespace(
        get_request=lambda *_a, **_k: seq_reapp.pop(0) if seq_reapp else rejected_rev,
        revoke_request=lambda *_a, **_k: rejected_rev,
        resolve_request=MagicMock(return_value=approved_rev),
    )
    with pytest.raises(FaultDeliveryError, match="incorrectly reapproved"):
        ctrl._execute_approval_fault(
            "approval_revocation",
            store_reapproved,
            SimpleNamespace(approval_token="t"),
            node_id="n1",
        )

    # approval_replay guards (approval_faults 86-90, 113, 115)
    unspent_rec = SimpleNamespace(
        run_id="run-1",
        status="APPROVED",
        action_payload={"a": 1},
        outbound_payload_hash="h",
        metadata={},
        to_dict=lambda: {"status": "APPROVED"},
    )
    seq1 = [unspent_rec, approved_rec, None]
    store1 = SimpleNamespace(
        get_request=lambda *_a, **_k: seq1.pop(0),
        consume_request=MagicMock(
            side_effect=[
                ApprovalValidationError("ApprovalReplayBlocked"),
                ApprovalValidationError("ApprovalReplayBlocked"),
            ]
        ),
        revoke_request=lambda *_a, **_k: approved_rec,
    )
    with pytest.raises(FaultDeliveryError, match="record disappeared"):
        deliver_authorization_fault(ctrl, "approval_replay", store1, req, None, "n1", "e1")

    mutated_rec = SimpleNamespace(
        run_id="run-1",
        status="APPROVED",
        action_payload={"a": 1},
        outbound_payload_hash="h",
        metadata={
            "consumption": {"run_id": "run-1", "payload_hash": "h", "authorization_id": "other"}
        },
        to_dict=lambda: {"status": "APPROVED"},
    )
    seq2 = [approved_rec, mutated_rec]
    store2 = SimpleNamespace(
        get_request=lambda *_a, **_k: seq2.pop(0),
        consume_request=MagicMock(side_effect=ApprovalValidationError("ApprovalReplayBlocked")),
        revoke_request=lambda *_a, **_k: approved_rec,
    )
    with pytest.raises(FaultDeliveryError, match="changed the spent authorization"):
        deliver_authorization_fault(ctrl, "approval_replay", store2, req, None, "n1", "e1")

    # approval_race contender re-raises ValueError if status stays PENDING (runtime_faults 277)
    pending_rec = SimpleNamespace(
        run_id="run-1",
        status="PENDING",
        outbound_payload_hash="h",
        checkpoint_id="c",
        scope_digest="s",
        to_dict=lambda: {},
    )
    store_race_err = SimpleNamespace(
        get_request=lambda *_a, **_k: pending_rec,
        revoke_request=lambda *_a, **_k: pending_rec,
        resolve_request=MagicMock(side_effect=ValueError("still pending")),
    )
    with patch(
        "eval_runner.mutations.approval_faults.validate_expiry",
        side_effect=[None, ApprovalValidationError("OtherCode")],
    ):
        with pytest.raises(ApprovalValidationError):
            deliver_authorization_fault(
                ctrl, "approval_stale", store_expire_not_observed, req, None, "n1", "e1"
            )

    store_replay_other = SimpleNamespace(
        get_request=lambda *_a, **_k: unspent_rec,
        consume_request=MagicMock(side_effect=ApprovalValidationError("OtherCode")),
        revoke_request=lambda *_a, **_k: approved_rec,
    )
    with pytest.raises(ApprovalValidationError):
        deliver_authorization_fault(
            ctrl, "approval_replay", store_replay_other, req, None, "n1", "e1"
        )

    with pytest.raises(ValueError, match="still pending"):
        ctrl._execute_approval_fault(
            "approval_race", store_race_err, SimpleNamespace(approval_token="t"), node_id="n1"
        )
