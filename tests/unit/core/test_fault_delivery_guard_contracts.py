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
