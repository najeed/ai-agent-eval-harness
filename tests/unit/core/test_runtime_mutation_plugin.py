"""
tests.unit.core.test_runtime_mutation_plugin
============================================
Comprehensive test suite for RuntimeMutationPlugin and the Southbound
Interception Architecture across tool dispatch, state commits, rollbacks,
and human-in-the-loop approvals.
"""

from __future__ import annotations

import asyncio
import copy
from unittest.mock import MagicMock, patch

import pytest

from agentv_runtime.interfaces import ApprovalRequest
from eval_runner.events import EventEmitter
from eval_runner.mutations.approval_faults import deliver_authorization_fault
from eval_runner.mutations.mutation_evidence import (
    _valid_fault_observations,
    evidence_hash,
    fault_receipt_failures,
)
from eval_runner.mutations.mutation_rules import valid_extended_observations
from eval_runner.mutations.mutator_plugin import RuntimeMutationPlugin
from eval_runner.mutations.runtime_faults import (
    FaultDeliveryController,
    FaultDeliveryError,
)
from eval_runner.mutations.tool_faults import ToolFaultExecutor
from eval_runner.plugins import PluginManager
from eval_runner.reference.approval_store import FileApprovalStore, SQLiteApprovalStore
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.session_components.approval_manager import SessionApprovalManager
from eval_runner.tool_sandbox import ToolSandbox


@pytest.mark.parametrize(
    "declaration",
    [
        {"approval_replay": True},
        {"mutations": {"approval_replay": True}},
        {"adversarial_mutation": {"approval_fault": "approval_replay"}},
        {"approval_fault": "approval_replay"},
    ],
)
def test_runtime_and_certification_compile_the_same_approval_fault(tmp_path, declaration):
    from eval_runner.mutations.mutation_registry import required_deliveries

    provider, bus = _recorded_fault_environment(tmp_path)
    scenario = {"workflow": [{"id": "transfer", **declaration}]}
    plugin = RuntimeMutationPlugin(scenario)
    plugins = PluginManager()
    plugins.plugins = [plugin]
    plugin.on_step_start(None, "transfer", declaration)
    selected = plugin.on_approval_preflight(None, declaration)
    assert selected["runtime_fault"]["fault"] == "approval_replay"
    assert selected.get("allowed", True) is True
    required = required_deliveries(scenario)
    assert required == {("approval_replay", "transfer")}
    assert fault_receipt_failures([], required)
    manager = SessionApprovalManager(
        run_id="fault-run",
        approval_store=FileApprovalStore(tmp_path / "approvals"),
        plugin_manager=plugins,
        event_bus=bus,
        run_store=provider,
    )
    with pytest.raises(PermissionError, match="observed approval_replay"):
        manager.create_durable_request(
            turn_index=1, action_payload={"amount": 100}, metadata={"task_id": "transfer"}
        )
    assert (
        fault_receipt_failures(provider.get_events("fault-run"), required, run_id="fault-run") == []
    )


@pytest.mark.parametrize(
    "fault",
    [
        "approval_stale",
        "approval_mismatch",
        "approval_replay",
        "approval_revocation",
        "approval_race",
    ],
)
def test_approval_selection_never_substitutes_a_synthetic_preflight_failure(fault):
    plugin = RuntimeMutationPlugin()
    plugin.on_step_start(None, "n", {fault: True})
    decision = plugin.on_approval_preflight(None, {"id": "n"})
    assert decision == {
        "runtime_fault": {"fault": fault, "node_id": "n", "execution_instance_id": None}
    }


def test_security_assertion_cannot_waive_receipts_for_other_executions():
    events = [
        {
            "event": "assertion_evaluated",
            "oracle_id": "security:approval_revocation",
            "node_id": "n",
            "outcome": "FAIL",
            "execution_instance_id": "n:1",
        },
        *[
            {
                "event": "execution_graph_node",
                "scenario_node_id": "n",
                "status": "failed",
                "execution_instance_id": instance,
            }
            for instance in ("n:1", "n:2")
        ],
    ]
    assert fault_receipt_failures(events, [("approval_revocation", "n")]) == [
        "MutationDeliveryEvidenceMissing:approval_revocation:n"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("schema_mode", ["strict", "permissive", "absent"])
async def test_tool_contract_requires_observed_schema_rejection_and_consumer_receipt(
    tmp_path, schema_mode
):
    from eval_runner.certification_truth import state_claim_failures

    provider, session, turn = _tool_fault_session(
        tmp_path, {"tool_contract_violation": True}, changes=[{"path": "a", "value": 1}]
    )
    if schema_mode != "absent":
        session.sandbox.scenario["tools"]["write"]["input_schema"] = {
            "type": "object",
            "additionalProperties": schema_mode == "permissive",
        }
    history = []
    await session._handle_tool_call(
        1, {"tool_name": "write"}, session.sandbox, history, {"used_tools": []}, turn
    )
    events = provider.get_events("fault-run")
    assert fault_receipt_failures(events) == []
    scenario = {"workflow": [{"id": "transfer", "tool_contract_violation": True}]}
    failures = state_claim_failures(scenario, events, run_id="fault-run")
    if schema_mode == "strict":
        assert failures == []
        assert history[-1]["content"]["error_code"] == "TOOL_SCHEMA_VIOLATION"
        assert session.sandbox.state["a"] == 0
    else:
        assert any("MutationDeliveryEvidenceMissing" in failure for failure in failures)
        assert session.sandbox.state["a"] == 1


@pytest.mark.asyncio
async def test_timeout_observation_cannot_be_padded_to_the_configured_deadline(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    provider, session, _ = _tool_fault_session(tmp_path, {"timeout_boundary_ms": 5})

    async def slow_operation(**kwargs):
        await asyncio.sleep(0.05)

    monkeypatch.setattr(session.sandbox, "_execute_core", slow_operation)
    monkeypatch.setattr(
        "eval_runner.mutations.tool_faults.time", SimpleNamespace(monotonic=lambda: 10.0)
    )
    with pytest.raises(TimeoutError):
        await session.sandbox.execute("write", {})
    assert not any(
        event["event"] == "mutation_delivery" for event in provider.get_events("fault-run")
    )


def test_catalog_capabilities_distinguish_scenario_edits_from_execution_proofs():
    from eval_runner.mutations.mutation_registry import capability
    from eval_runner.mutations.mutator import MUTATION_CATALOG

    assert all(
        capability(item.id)["kind"] in {"runtime_fault", "scenario_edit"}
        for item in MUTATION_CATALOG
    )
    assert capability("rollback_failure")["delivery_evidence_required"] is True
    assert capability("tool_contract")["delivery_evidence_required"] is True
    assert capability("enum_drift")["execution_delivery_claim"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
async def test_empty_malformed_payload_requires_a_bound_delivery_receipt(tmp_path, nested):
    from eval_runner.certification_truth import state_claim_failures
    from eval_runner.mutations.mutation_registry import required_deliveries

    flags = {"raw_payload_corrupted": ""}
    declaration = {"mutations": flags} if nested else flags
    scenario = {"workflow": [{"id": "transfer", **declaration}]}
    required = required_deliveries(scenario)
    assert required == {("malformed_payload", "transfer")}
    assert state_claim_failures(scenario, [], run_id="fault-run")
    provider, session, turn = _tool_fault_session(tmp_path, declaration)
    await session._handle_tool_call(
        1, {"tool_name": "write"}, session.sandbox, [], {"used_tools": []}, turn
    )
    assert (
        state_claim_failures(scenario, provider.get_events("fault-run"), run_id="fault-run") == []
    )


@pytest.mark.parametrize("scoped", [False, True])
def test_unknown_extension_fault_cannot_drop_its_evidence_requirement(scoped):
    from eval_runner.certification_truth import state_claim_failures
    from eval_runner.mutations.mutation_registry import capability, required_deliveries

    row = {"type": "plugin.custom_fault", **({"node_id": "n"} if scoped else {})}
    scenario = {"workflow": [{"id": "n"}], "metadata": {"applied_mutations": [row]}}
    assert capability(row["type"])["delivery_evidence_required"] is True
    assert required_deliveries(scenario) == {("plugin.custom_fault", "n" if scoped else None)}
    assert any(
        "MutationDeliveryEvidenceMissing:plugin.custom_fault" in error
        for error in state_claim_failures(scenario, [], run_id="r")
    )
    assert fault_receipt_failures(
        [
            {
                "event": "mutation_delivery",
                "mutation_receipt": {"fault": "plugin.custom_fault", "delivery": "DELIVERED"},
            }
        ]
    )


def test_all_core_aliases_have_explicit_capabilities():
    from eval_runner.mutations.mutation_registry import capability, required_deliveries
    from eval_runner.mutations.mutator import CoreMutator

    for name in CoreMutator.SUPPORTED_TYPES:
        classification = capability(name)
        assert classification["kind"] != "extension", name
        if classification["kind"] == "scenario_edit":
            assert (
                required_deliveries({"metadata": {"applied_mutations": [{"type": name}]}}) == set()
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"_unexpected_forbidden_property": {"violation": "additionalProperties_forbidden"}},
        {"already_invalid": True},
    ],
)
async def test_preexisting_contract_violation_cannot_be_reported_as_injected(tmp_path, arguments):
    provider, session, turn = _tool_fault_session(tmp_path, {"tool_contract_violation": True})
    session.sandbox.scenario["tools"]["write"]["input_schema"] = {
        "type": "object",
        "additionalProperties": False,
    }
    await session._handle_tool_call(
        1,
        {"tool_name": "write", "tool_params": arguments},
        session.sandbox,
        [],
        {"used_tools": []},
        turn,
    )
    events = provider.get_events("fault-run")
    assert fault_receipt_failures(events) == []
    receipt = next(
        event["mutation_receipt"] for event in events if event["event"] == "mutation_delivery"
    )
    assert receipt["delivery"] == "NOT_DELIVERED"
    assert fault_receipt_failures(events, [("tool_contract", "transfer")])


@pytest.mark.asyncio
async def test_duplicate_execution_composes_with_verified_response_corruption(tmp_path):
    from eval_runner.certification_truth import state_claim_failures

    flags = {"duplicate_execution": True, "tool_response_corrupted": True}
    provider, session, turn = _tool_fault_session(tmp_path, flags)
    history = []
    await session._handle_tool_call(
        1, {"tool_name": "write"}, session.sandbox, history, {"used_tools": []}, turn
    )
    assert session.sandbox.grounding_hits["tools"]["write"] == 2
    events = provider.get_events("fault-run")
    receipts = [
        event["mutation_receipt"] for event in events if event["event"] == "mutation_delivery"
    ]
    assert {row["fault"] for row in receipts if row["delivery"] == "DELIVERED"} == {
        "tool_duplicate",
        "tool_response_corruption",
    }
    scenario = {"workflow": [{"id": "transfer", **flags}]}
    assert state_claim_failures(scenario, events, run_id="fault-run") == []
    # The transformation is independently resolved, not accepted as an
    # unrelated final payload with a matching self-declared expected hash.
    source = next(
        event
        for event in events
        if event.get("evidence", {}).get("kind") == "tool_response_modified"
    )
    duplicate_only = [
        event
        for event in events
        if event is not source
        and (
            event["event"] != "mutation_delivery"
            or event["mutation_receipt"]["fault"] == "tool_duplicate"
        )
    ]
    failures = fault_receipt_failures(duplicate_only, [("tool_duplicate", "transfer")])
    duplicate_id = next(row["fault_id"] for row in receipts if row["fault"] == "tool_duplicate")
    assert f"InvalidMutationDeliveryEvidence:{duplicate_id}" in failures


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize(
    "tamper", [None, "missing_transformation", "wrong_source", "malformed_source_ref"]
)
async def test_replay_composes_with_bound_response_corruption(tmp_path, parallel, tamper):
    from eval_runner.certification_truth import state_claim_failures

    provider, session, turn = _tool_fault_session(tmp_path, {"replay_previous_event": True})
    history, actions = [], {"used_tools": []}

    async def call(index):
        if parallel:
            await session._handle_multiple_tools(
                index,
                {"tool_calls": [{"tool": "write", "params": {}}]},
                session.sandbox,
                history,
                actions,
                turn,
            )
        else:
            await session._handle_tool_call(
                index, {"tool_name": "write"}, session.sandbox, history, actions, turn
            )

    await call(1)
    flags = {"replay_previous_event": True, "tool_response_corrupted": True}
    session.plugin_manager.plugins[0].on_step_start(session, "transfer", flags)
    await call(2)
    assert session.sandbox.grounding_hits["tools"]["write"] == 1
    events = provider.get_events("fault-run")
    receipts = [e["mutation_receipt"] for e in events if e["event"] == "mutation_delivery"]
    assert {r["fault"] for r in receipts if r["delivery"] == "DELIVERED"} == {
        "tool_replay",
        "tool_response_corruption",
    }
    if tamper == "missing_transformation":
        events = [
            e for e in events if e.get("evidence", {}).get("kind") != "tool_response_modified"
        ]
    elif tamper in {"wrong_source", "malformed_source_ref"}:
        event = next(
            e for e in events if e.get("evidence", {}).get("kind") == "tool_response_replayed"
        )
        row = event["evidence"]["observation"]
        if tamper == "wrong_source":
            row["payload_hash"] = evidence_hash({"different": "response"})
        else:
            row["source_ref"] = ["invalid-reference"]
        event["evidence_hash"] = evidence_hash(event["evidence"])
        for receipt in receipts:
            for ref in receipt["evidence_refs"]:
                if ref["event_id"] == event["evidence"]["event_id"]:
                    ref["evidence_hash"] = event["evidence_hash"]
            receipt["receipt_hash"] = evidence_hash(
                {k: v for k, v in receipt.items() if k != "receipt_hash"}
            )
    failures = state_claim_failures(
        {"workflow": [{"id": "transfer", **flags}]}, events, run_id="fault-run"
    )
    assert bool(failures) == (tamper is not None)


def test_targeted_rollback_fault_does_not_require_injection_into_other_compensations(tmp_path):
    from eval_runner.mutations.compensation_faults import intercept_compensation
    from eval_runner.mutations.mutation_registry import required_deliveries

    provider, bus = _recorded_fault_environment(tmp_path)
    scenario = {
        "workflow": [{"id": "target", "rollback_handler_corrupted": True}, {"id": "other"}],
        "metadata": {"applied_mutations": [{"type": "rollback_failure"}]},
    }
    plugins = PluginManager()
    plugins.plugins = [RuntimeMutationPlugin(scenario)]
    intercept_compensation(
        "fault-run", bus, plugins, scenario, scenario["workflow"][0], "target:1", "parent:1"
    )
    events = provider.get_events("fault-run")
    for node in ("target", "other"):
        events.append(
            {
                "event": "execution_graph_node",
                "scenario_node_id": node,
                "execution_instance_id": node + ":1",
                "status": "failed" if node == "target" else "success",
                "compensating": True,
            }
        )
    required = required_deliveries(scenario)
    assert required == {("rollback_failure", "target")}
    assert fault_receipt_failures(events, required, run_id="fault-run") == []
    global_scenario = {**scenario, "metadata": {"rollback_handler_corrupted": True}}
    assert required_deliveries(global_scenario) == {("rollback_failure", None)}
    assert fault_receipt_failures(events, required_deliveries(global_scenario), run_id="fault-run")


@pytest.mark.asyncio
async def test_parallel_contract_injections_keep_original_argument_evidence_isolated(tmp_path):
    provider, session, turn = _tool_fault_session(tmp_path, {"tool_contract_violation": True})
    session.sandbox.scenario["tools"]["write"]["input_schema"] = {
        "type": "object",
        "properties": {"id": {"type": "integer"}},
        "additionalProperties": False,
    }
    await session._handle_multiple_tools(
        1,
        {
            "tool_calls": [
                {"tool": "write", "params": {"id": 1}},
                {"tool": "write", "params": {"id": 2}},
            ]
        },
        session.sandbox,
        [],
        {"used_tools": []},
        turn,
    )
    events = provider.get_events("fault-run")
    assert fault_receipt_failures(events, [("tool_contract", "transfer")], run_id="fault-run") == []
    originals = [
        event["evidence"]["observation"]["original_arguments"]["id"]
        for event in events
        if event.get("evidence", {}).get("kind") == "tool_arguments_modified"
    ]
    assert sorted(originals) == [1, 2]
    assert (
        sum(event.get("mutation_receipt", {}).get("delivery") == "DELIVERED" for event in events)
        == 2
    )


def _recorded_fault_environment(tmp_path, run_id="fault-run"):
    provider = LocalFileRunStore(tmp_path / "runs")
    provider.create_run(run_id, "boundary-faults")
    bus = EventEmitter(run_id=run_id, async_mode=False)
    bus.subscribe(lambda event: provider.append_events(run_id, [event.to_dict()]), required=True)
    return provider, bus


def _tool_fault_session(tmp_path, flags, *, changes=None, output=None):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from eval_runner.session import SessionManager

    provider, bus = _recorded_fault_environment(tmp_path)
    plugin = RuntimeMutationPlugin()
    plugins = PluginManager()
    plugins.plugins = [plugin]
    sandbox = ToolSandbox(
        {
            "run_id": "fault-run",
            "initial_state": {"a": 0, "b": 0},
            "tools": {
                "write": {"state_changes": changes or [], "output": output or {"status": "success"}}
            },
        },
        event_bus=bus,
        plugin_manager=plugins,
    )
    session = object.__new__(SessionManager)
    session.sandbox, session.event_bus, session.plugin_manager = sandbox, bus, plugins
    session.current_execution_instance_id = "transfer:attempt1"
    sandbox.current_execution_instance_id = session.current_execution_instance_id
    session.forensics = MagicMock()
    session._acquire_bounded_state = AsyncMock(return_value={})
    session._capture_telemetry = MagicMock()
    session.state_snapshots = []
    plugin.on_step_start(session, "transfer", flags)
    return provider, session, SimpleNamespace(span_context={})


@pytest.mark.asyncio
@pytest.mark.parametrize("parallel", [False, True])
@pytest.mark.parametrize(
    "flags,fault",
    [
        ({"timeout_boundary_ms": 5, "injected_latency_ms": 50}, "timeout_boundary"),
        ({"raw_payload_corrupted": '{"unterminated'}, "malformed_payload"),
        ({"injected_latency_ms": 2}, "latency_jitter"),
        ({"duplicate_execution": True}, "tool_duplicate"),
        ({"tool_response_corrupted": True}, "tool_response_corruption"),
    ],
)
async def test_faults_reach_real_session_consumer_with_bound_proofs(
    tmp_path, parallel, flags, fault
):
    provider, session, turn = _tool_fault_session(tmp_path, flags)
    history, actions = [], {"used_tools": []}
    if parallel:
        await session._handle_multiple_tools(
            1,
            {"tool_calls": [{"tool": "write", "params": {}}]},
            session.sandbox,
            history,
            actions,
            turn,
        )
    else:
        await session._handle_tool_call(
            1, {"tool_name": "write"}, session.sandbox, history, actions, turn
        )
    events = provider.get_events("fault-run")
    assert history[-1]["role"] == "environment"
    assert fault_receipt_failures(events, [(fault, "transfer")], run_id="fault-run") == []
    from eval_runner.certification_truth import state_claim_failures

    scenario = {"workflow": {"nodes": [{"id": "transfer", **flags}]}}
    assert state_claim_failures(scenario, events, run_id="fault-run") == []
    receipts = [
        event["mutation_receipt"] for event in events if event["event"] == "mutation_delivery"
    ]
    assert len(receipts) == 1
    assert receipts[0]["execution_instance_id"] == "transfer:attempt1"
    expected_calls = 2 if fault == "tool_duplicate" else 1
    assert session.sandbox.grounding_hits["tools"]["write"] == expected_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["one_field", "no_change", "mixed", "rollback"])
async def test_partial_commit_delivery_requires_committed_and_omitted_writes(
    tmp_path, monkeypatch, mode
):
    changes = [{"path": "a", "value": 0 if mode == "no_change" else 1}]
    if mode != "one_field":
        changes.append({"path": "b", "value": 0 if mode == "no_change" else 2})
    provider, session, _ = _tool_fault_session(
        tmp_path, {"partial_commit_simulated": True}, changes=changes
    )
    if mode == "rollback":

        def fail_write(path, value):
            session.sandbox.state[path] = value
            raise OSError("Write interrupted")

        monkeypatch.setattr(session.sandbox, "_set_state_path", fail_write)
    await session.sandbox.execute("write", {})
    events = provider.get_events("fault-run")
    assert fault_receipt_failures(events) == []
    proofs = fault_receipt_failures(events, [("partial_commit", "transfer")])
    assert bool(proofs) == (mode != "mixed")
    if mode == "mixed":
        assert session.sandbox.state == {"a": 1, "b": 0}
    elif mode in {"rollback", "no_change"}:
        assert session.sandbox.state == {"a": 0, "b": 0}


@pytest.mark.asyncio
async def test_stale_commit_uses_actual_revision_conflict(tmp_path):
    provider, session, _ = _tool_fault_session(
        tmp_path,
        {"stale_commit": True},
        changes=[{"path": "a", "value": 1}, {"path": "b", "value": 2}],
    )
    session.sandbox.scenario["tools"]["read"] = {}
    await session.sandbox.execute("read", {})
    assert session.sandbox.commit_boundary.revision == 0
    result = await session.sandbox.execute("write", {})
    assert result["error_code"] == "STATE_COMMIT_REJECTED"
    assert session.sandbox.commit_boundary.revision == 1
    assert session.sandbox.state == {"a": 1, "b": 0}
    assert (
        fault_receipt_failures(provider.get_events("fault-run"), [("stale_commit", "transfer")])
        == []
    )


@pytest.mark.parametrize("operation", ["shared_write", "shared_read"])
@pytest.mark.parametrize("allowed", [False, True])
@pytest.mark.parametrize("has_path", [False, True])
def test_commit_boundary_shared_access_and_atomic_rollback(tmp_path, operation, allowed, has_path):
    _, session, _ = _tool_fault_session(tmp_path, {})
    sandbox = session.sandbox
    sandbox.shared_state.topology = {
        "agent": {
            "writes": ["shared:*"] if allowed else [],
            "reads": ["shared:*"] if allowed else [],
        }
    }
    sandbox.shared_state.registry["shared:item"] = 10
    params = {operation: {"value": 20, **({"path": "shared:item"} if has_path else {})}}
    if has_path and not allowed:
        with pytest.raises(PermissionError, match="denied"):
            sandbox.commit_boundary.commit({"a": 1}, params, "agent")
        assert sandbox.state == {"a": 0, "b": 0}
        assert sandbox.shared_state.registry == {"shared:item": 10}
        assert sandbox.commit_boundary.revision == 0
    else:
        sandbox.commit_boundary.commit({"a": 1}, params, "agent")
        assert sandbox.state == {"a": 1, "b": 0}
        assert sandbox.shared_state.registry["shared:item"] == (
            20 if operation == "shared_write" and has_path else 10
        )
        assert sandbox.commit_boundary.revision == 1


@pytest.mark.parametrize(
    "after,applied,omitted",
    [
        ({"a": 9, "b": 0}, [], ["b"]),
        ({"a": 1, "b": 2}, ["a"], []),
        ({"a": 1, "b": 9}, ["a"], []),
    ],
)
def test_partial_commit_observation_rejects_wrong_or_fully_committed_values(
    tmp_path, after, applied, omitted
):
    _, session, _ = _tool_fault_session(tmp_path, {})
    boundary = session.sandbox.commit_boundary
    _, ticket = boundary.prepare_partial({"a": 1, "b": 2}, "transfer", "transfer:attempt1")
    session.sandbox.state.update(after)
    receipt = boundary.complete_partial(ticket)
    assert receipt["observed"]["applied_paths"] == applied
    assert receipt["observed"]["omitted_paths"] == omitted
    assert receipt["delivery"] == "NOT_DELIVERED"


@pytest.mark.asyncio
async def test_tool_replay_requires_prior_consumed_response_and_skips_redispatch(tmp_path):
    provider, session, turn = _tool_fault_session(tmp_path, {"replay_previous_event": True})
    history, actions = [], {"used_tools": []}
    await session._handle_tool_call(
        1, {"tool_name": "write"}, session.sandbox, history, actions, turn
    )
    assert fault_receipt_failures(provider.get_events("fault-run"), [("tool_replay", "transfer")])
    await session._handle_tool_call(
        2, {"tool_name": "write"}, session.sandbox, history, actions, turn
    )
    assert session.sandbox.grounding_hits["tools"]["write"] == 1
    assert (
        fault_receipt_failures(provider.get_events("fault-run"), [("tool_replay", "transfer")])
        == []
    )
    events = provider.get_events("fault-run")
    events = [
        event
        for event in events
        if not (event.get("evidence") or {}).get("kind") == "tool_response_delivered"
    ]
    assert fault_receipt_failures(events, [("tool_replay", "transfer")])


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["noop", "restored"])
async def test_response_corruption_cannot_claim_delivery_when_payload_unchanged(tmp_path, mode):
    corrupted = {
        "status": "error",
        "error": "InjectedToolResponseCorruption",
        "mutation_fault": "tool_response_corruption",
    }
    provider, session, _ = _tool_fault_session(
        tmp_path, {"tool_response_corrupted": True}, output=corrupted if mode == "noop" else None
    )
    original = await session.sandbox.execute("write", {})
    mutation = session.plugin_manager.trigger_interceptor("on_tool_result", None, "write", original)
    session.sandbox.tool_faults.acknowledge(
        session.sandbox.tool_faults.take_delivery_context(),
        mutation["result"] if mode == "noop" else original,
    )
    events = provider.get_events("fault-run")
    assert fault_receipt_failures(events) == []
    assert fault_receipt_failures(events, [("tool_response_corruption", "transfer")])
    assert (
        next(e["mutation_receipt"] for e in events if e["event"] == "mutation_delivery")["delivery"]
        == "NOT_DELIVERED"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flags,fault",
    [
        ({"timeout_boundary_ms": 500}, "timeout_boundary"),
        ({"raw_payload_corrupted": '{"valid":true}'}, "malformed_payload"),
    ],
)
async def test_no_timeout_or_parse_failure_does_not_claim_fault_delivery(tmp_path, flags, fault):
    provider, session, turn = _tool_fault_session(tmp_path, flags)
    await session._handle_tool_call(
        1, {"tool_name": "write"}, session.sandbox, [], {"used_tools": []}, turn
    )
    events = provider.get_events("fault-run")
    assert fault_receipt_failures(events) == []
    assert fault_receipt_failures(events, [(fault, "transfer")])


def test_unknown_or_unbound_delivery_is_rejected_for_every_mutation():
    assert fault_receipt_failures(
        [
            {
                "event": "mutation_delivery",
                "mutation_receipt": {"fault": "invented", "delivery": "DELIVERED"},
            }
        ]
    )


@pytest.mark.parametrize("kind", ["file", "sqlite"])
def test_atomic_approval_consumption_across_provider_instances(tmp_path, kind):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from agentv_runtime.interfaces import ApprovalRequest
    from eval_runner.approval_validation import ApprovalValidationError
    from eval_runner.mutations.mutation_evidence import evidence_hash

    def store():
        return (
            FileApprovalStore(tmp_path / "approvals")
            if kind == "file"
            else SQLiteApprovalStore(tmp_path / "approvals.db")
        )

    stores = [store(), store()]
    payload_hash = evidence_hash({"transfer": 100})
    stores[0].create_request(
        ApprovalRequest(
            approval_token="single-use", run_id="fault-run", outbound_payload_hash=payload_hash
        )
    )
    stores[0].resolve_request("single-use", "APPROVED")
    barrier = threading.Barrier(2)

    def spend(provider):
        barrier.wait(timeout=5)
        try:
            return provider.consume_request(
                "single-use", run_id="fault-run", payload_hash=payload_hash
            ).metadata["consumption"]
        except ApprovalValidationError as exc:
            assert exc.code == "ApprovalReplayBlocked"
            return None

    executor = ThreadPoolExecutor(max_workers=2)
    try:
        futures = [executor.submit(spend, provider) for provider in stores]
        outcomes = [future.result(timeout=10) for future in futures]
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    winner = next(result for result in outcomes if result is not None)
    assert sum(result is not None for result in outcomes) == 1
    assert all(
        provider.get_request("single-use").metadata["consumption"] == winner for provider in stores
    )
    with pytest.raises(ValueError, match="cannot be republished"):
        stores[0].create_request(ApprovalRequest(approval_token="single-use", run_id="fault-run"))


@pytest.mark.parametrize("kind", ["file", "sqlite"])
@pytest.mark.parametrize(
    "fault,spent",
    [
        ("approval_mismatch", False),
        ("approval_replay", False),
        ("approval_stale", False),
        ("approval_replay", True),
    ],
)
def test_authorization_faults_exercise_existing_granted_requests(tmp_path, kind, fault, spent):
    from agentv_runtime.interfaces import ApprovalRequest
    from eval_runner.mutations.mutation_evidence import evidence_hash

    provider, bus = _recorded_fault_environment(tmp_path)
    approvals = (
        FileApprovalStore(tmp_path / "approvals")
        if kind == "file"
        else SQLiteApprovalStore(tmp_path / "approvals.db")
    )
    request = approvals.create_request(
        ApprovalRequest(
            approval_token="granted",
            run_id="fault-run",
            outbound_payload_hash=evidence_hash({"transfer": 100}),
        )
    )
    approvals.resolve_request(request.approval_token, "APPROVED")
    if spent:
        approvals.consume_request(
            "granted",
            run_id="fault-run",
            payload_hash=request.outbound_payload_hash.removeprefix("sha3_256:"),
        )
    before = approvals.get_request("granted").metadata.get("consumption")
    FaultDeliveryController("fault-run", bus).approval_fault(
        fault, approvals, request, node_id="transfer"
    )
    assert approvals.get_request("granted").status == "REJECTED"
    if spent:
        assert approvals.get_request("granted").metadata["consumption"] == before
    assert fault_receipt_failures(provider.get_events("fault-run"), [(fault, "transfer")]) == []


@pytest.mark.asyncio
async def test_composed_execution_faults_have_independent_receipts(tmp_path):
    provider, session, turn = _tool_fault_session(
        tmp_path, {"duplicate_execution": True, "injected_latency_ms": 2}
    )
    await session._handle_tool_call(
        1, {"tool_name": "write"}, session.sandbox, [], {"used_tools": []}, turn
    )
    assert (
        fault_receipt_failures(
            provider.get_events("fault-run"),
            [("tool_duplicate", "transfer"), ("latency_jitter", "transfer")],
        )
        == []
    )


@pytest.mark.asyncio
async def test_operation_timeout_error_is_not_runtime_deadline_delivery(tmp_path, monkeypatch):
    provider, session, _ = _tool_fault_session(tmp_path, {"timeout_boundary_ms": 500})

    async def fail_operation(**kwargs):
        raise TimeoutError("Operation's own timeout")

    monkeypatch.setattr(session.sandbox, "_execute_core", fail_operation)
    with pytest.raises(TimeoutError, match="Operation's own timeout"):
        await session.sandbox.execute("write", {})
    assert not any(e["event"] == "mutation_delivery" for e in provider.get_events("fault-run"))


def test_mutation_evidence_preserves_committed_bytes_for_provider_and_redacts_telemetry(tmp_path):
    from eval_runner.mutations.mutation_evidence import evidence_hash

    provider, bus = _recorded_fault_environment(tmp_path)
    telemetry = []
    bus.subscribe(lambda event: telemetry.append(event.to_dict()))
    controller = FaultDeliveryController("fault-run", bus)
    identity = controller._identity("malformed_payload", "transfer")
    raw = '{"key":"' + "sk-" + "a" * 40
    ref = controller._observe("tool_wire_received", identity, {"raw_payload": raw})
    persisted = provider.get_events("fault-run")[0]
    assert persisted["evidence"]["observation"]["raw_payload"] == raw
    assert (
        persisted["evidence_hash"] == ref["evidence_hash"] == evidence_hash(persisted["evidence"])
    )
    assert "[REDACTED_KEY]" in telemetry[0]["evidence"]["observation"]["raw_payload"]
    assert fault_receipt_failures(
        [
            {
                "event": "adapter_debug",
                "mutation_receipt": {"fault": "partial_commit", "delivery": "DELIVERED"},
            }
        ]
    )


@pytest.mark.parametrize("kind", ["file", "sqlite"])
@pytest.mark.parametrize(
    "fault",
    [
        "approval_race",
        "approval_revocation",
        "approval_stale",
        "approval_mismatch",
        "approval_replay",
    ],
)
def test_real_approval_faults_persist_transitions_and_bound_receipts(tmp_path, kind, fault):
    provider, bus = _recorded_fault_environment(tmp_path)
    approvals = (
        FileApprovalStore(tmp_path / "approvals")
        if kind == "file"
        else SQLiteApprovalStore(tmp_path / "approvals.db")
    )
    plugin = RuntimeMutationPlugin()
    plugins = PluginManager()
    plugins.plugins.append(plugin)
    plugin.on_step_start(None, "transfer", {fault: True})
    manager = SessionApprovalManager(
        run_id="fault-run",
        approval_store=approvals,
        plugin_manager=plugins,
        event_bus=bus,
        run_store=provider,
    )
    with pytest.raises(PermissionError, match="ApprovalRejected: observed"):
        manager.create_durable_request(
            turn_index=1, action_payload={"amount": 100}, metadata={"task_id": "transfer"}
        )
    request = approvals.get_request_by_run_id("fault-run")
    assert request.status == "REJECTED"
    with pytest.raises(ValueError, match="already resolved"):
        approvals.resolve_request(request.approval_token, "APPROVED")
    events = provider.get_events("fault-run")
    assert fault_receipt_failures(events, [(fault, "transfer")], run_id="fault-run") == []
    receipt = next(
        event["mutation_receipt"] for event in events if event["event"] == "mutation_delivery"
    )
    assert receipt["observed"]["approval_token"] == request.approval_token
    if fault == "approval_revocation":
        assert request.metadata["revocation"]["previous_status"] == "APPROVED"
        assert receipt["observed"]["replay_blocked"] is True
    elif fault == "approval_race":
        contenders = receipt["observed"]["contenders"]
        assert {row["decision"] for row in contenders} == {"APPROVED", "REJECTED"}
        assert sum(row["accepted"] for row in contenders) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "permission", "rollback", "unchanged"])
async def test_cancelled_commit_receipt_requires_observed_state_change(
    tmp_path, monkeypatch, failure
):
    provider, bus = _recorded_fault_environment(tmp_path)
    plugin = RuntimeMutationPlugin()
    plugins = PluginManager()
    plugins.plugins.append(plugin)
    sandbox = ToolSandbox(
        {
            "run_id": "fault-run",
            "initial_state": {"balance": 0},
            "tools": {
                "write": {
                    "state_changes": [
                        {"path": "balance", "value": 0 if failure == "unchanged" else 100}
                    ]
                }
            },
        },
        event_bus=bus,
        plugin_manager=plugins,
    )
    plugin.on_step_start(sandbox, "transfer", {"commit_after_cancel": True})
    if failure == "rollback":
        original = sandbox._set_state_path

        def fail_commit(path, value):
            original(path, value)
            raise PermissionError("Write failed during commit")

        monkeypatch.setattr(sandbox, "_set_state_path", fail_commit)
    if failure == "unchanged":
        with pytest.raises(FaultDeliveryError, match="state change was not observed"):
            await sandbox.execute("write", {})
    else:
        params = (
            {"shared_write": {"path": "denied:balance", "value": 1}}
            if failure == "permission"
            else {}
        )
        await sandbox.execute("write", params)
    assert sandbox.cancellation_event.is_set()
    assert sandbox.state["balance"] == (100 if failure is None else 0)
    events = provider.get_events("fault-run")
    failures = fault_receipt_failures(
        events, [("commit_after_cancel", "transfer")], run_id="fault-run"
    )
    if failure is None:
        assert failures == []
    else:
        assert any("MutationDeliveryEvidenceMissing" in row for row in failures)
        assert not any(event["event"] == "mutation_delivery" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["null", "nested_null", "boolean", "integer", "float"])
@pytest.mark.parametrize("drop_write", [False, True])
async def test_cancelled_commit_requires_every_canonical_write(tmp_path, mode, drop_write):
    path = "nested.field" if mode == "nested_null" else "field"
    value = {"null": None, "nested_null": None, "boolean": False, "integer": 1, "float": 1.0}[mode]
    provider, session, _ = _tool_fault_session(
        tmp_path,
        {"commit_after_cancel": True},
        changes=[{"path": "a", "value": 1}, {"path": path, "value": value}],
    )
    if mode not in {"null", "nested_null"}:
        session.sandbox.state["field"] = {"boolean": 0, "integer": True, "float": 1}[mode]

    class DropWrite:
        def on_before_commit(self, context, diff):
            return {"state_diff": {key: val for key, val in diff.items() if key != path}}

    # Canonical JSON normalizes 1 and 1.0 to the same number; booleans remain distinct.
    should_fail = drop_write and mode != "float"
    if drop_write:
        session.plugin_manager.plugins.append(DropWrite())
    if should_fail:
        with pytest.raises(FaultDeliveryError, match="state change was not observed"):
            await session.sandbox.execute("write", {})
    else:
        await session.sandbox.execute("write", {})
    events = provider.get_events("fault-run")
    assert (
        bool(fault_receipt_failures(events, [("commit_after_cancel", "transfer")])) == should_fail
    )
    assert any(e["event"] == "mutation_delivery" for e in events) != should_fail


@pytest.mark.asyncio
async def test_runtime_cancellation_blocks_unmutated_commits(tmp_path):
    _, bus = _recorded_fault_environment(tmp_path)
    sandbox = ToolSandbox(
        {
            "run_id": "fault-run",
            "initial_state": {"balance": 0},
            "tools": {"write": {"state_changes": [{"path": "balance", "value": 100}]}},
        },
        event_bus=bus,
    )
    sandbox.cancellation_event.set()
    result = await sandbox.execute("write", {})
    assert result["error_code"] == "EXECUTION_CANCELLED"
    assert sandbox.state == {"balance": 0}


@pytest.mark.parametrize(
    "tamper", ["missing", "hash", "cross_run", "cross_node", "order", "semantics"]
)
def test_fault_delivery_validation_rejects_unbound_or_forged_evidence(tmp_path, tamper):
    from eval_runner.mutations.mutation_evidence import evidence_hash

    provider, bus = _recorded_fault_environment(tmp_path)
    controller = FaultDeliveryController("fault-run", bus)
    controller.cancel_at_tool_boundary("transfer", "write")
    events = copy.deepcopy(provider.get_events("fault-run"))
    assert fault_receipt_failures(events, [("cancel_race", "transfer")], run_id="fault-run") == []
    receipt = next(
        event["mutation_receipt"] for event in events if event["event"] == "mutation_delivery"
    )
    if tamper == "missing":
        events = [event for event in events if event["event"] != "runtime_fault_observation"]
    elif tamper == "hash":
        receipt["receipt_hash"] = "sha3_256:forged"
    elif tamper == "cross_run":
        receipt["run_id"] = "foreign-run"
    elif tamper == "cross_node":
        receipt["node_id"] = "foreign-node"
    elif tamper == "order":
        events.reverse()
    else:
        observation = events[0]["evidence"]
        observation["observation"]["cancelled"] = False
        events[0]["evidence_hash"] = evidence_hash(observation)
        receipt["evidence_refs"][0]["evidence_hash"] = events[0]["evidence_hash"]
    if tamper != "hash":
        receipt["receipt_hash"] = evidence_hash(
            {key: value for key, value in receipt.items() if key != "receipt_hash"}
        )
    assert fault_receipt_failures(events, [("cancel_race", "transfer")], run_id="fault-run")


@pytest.mark.parametrize(
    "field",
    [
        "delivery",
        "observed",
        "evidence_refs",
        "fault",
        "fault_id",
        "run_id",
        "node_id",
        "execution_instance_id",
    ],
)
@pytest.mark.parametrize("value", [["DELIVERED"], {"invalid": True}, True, 1, None])
def test_malformed_receipt_fields_return_verification_failures(tmp_path, field, value):
    from eval_runner.certification_truth import state_claim_failures

    provider, bus = _recorded_fault_environment(tmp_path)
    FaultDeliveryController("fault-run", bus).cancel_at_tool_boundary("transfer", "write")
    events = provider.get_events("fault-run")
    receipt = next(e["mutation_receipt"] for e in events if e["event"] == "mutation_delivery")
    receipt[field] = value
    receipt["receipt_hash"] = evidence_hash(
        {k: v for k, v in receipt.items() if k != "receipt_hash"}
    )
    failures = state_claim_failures(
        {"workflow": [{"id": "transfer", "cancel_at_boundary": True}]}, events, run_id="fault-run"
    )
    assert failures
    assert "MutationDeliveryEvidenceMissing:cancel_race:transfer" in failures


@pytest.mark.parametrize("fault", ["approval_replay", "approval_race"])
@pytest.mark.parametrize("value", [["invalid"], {"invalid": True}, True, 1])
def test_malformed_nested_authorization_evidence_returns_failures(tmp_path, fault, value):
    provider, bus = _recorded_fault_environment(tmp_path)
    approvals = FileApprovalStore(tmp_path / "approvals")
    request = approvals.create_request(
        ApprovalRequest(
            approval_token="malformed-proof",
            run_id="fault-run",
            outbound_payload_hash=evidence_hash({"amount": 1}),
        )
    )
    FaultDeliveryController("fault-run", bus).approval_fault(
        fault, approvals, request, node_id="transfer"
    )
    events = provider.get_events("fault-run")
    kind = "authorization_consumed" if fault == "approval_replay" else "approval_race_observed"
    event = next(e for e in events if e.get("evidence", {}).get("kind") == kind)
    observed = event["evidence"]["observation"]
    if fault == "approval_replay":
        observed["consumption"] = value
    else:
        observed["contenders"][0]["decision"] = value
    event["evidence_hash"] = evidence_hash(event["evidence"])
    receipt = next(e["mutation_receipt"] for e in events if e["event"] == "mutation_delivery")
    for ref in receipt["evidence_refs"]:
        if ref["event_id"] == event["evidence"]["event_id"]:
            ref["evidence_hash"] = event["evidence_hash"]
    receipt["receipt_hash"] = evidence_hash(
        {k: v for k, v in receipt.items() if k != "receipt_hash"}
    )
    failures = fault_receipt_failures(events, [(fault, "transfer")])
    assert f"InvalidMutationDeliveryEvidence:{receipt['fault_id']}" in failures
    assert f"MutationDeliveryEvidenceMissing:{fault}:transfer" in failures


@pytest.mark.parametrize("missing_sink", [True, False])
def test_fault_delivery_requires_successful_mandatory_evidence_acknowledgement(missing_sink):
    from eval_runner.events import EvidenceDeliveryError

    bus = EventEmitter(run_id="capture-failure", async_mode=False)
    recorded = []
    bus.subscribe(lambda event: recorded.append(event.to_dict()))
    if not missing_sink:

        def fail_capture(event):
            raise OSError("Evidence provider unavailable")

        bus.subscribe(fail_capture, required=True)
    controller = FaultDeliveryController("capture-failure", bus)
    with pytest.raises(EvidenceDeliveryError):
        controller.cancel_at_tool_boundary("transfer", "write")
    assert not any(event["event"] == "mutation_delivery" for event in recorded)


@pytest.mark.parametrize("kind", ["file", "sqlite"])
def test_revoked_approval_cannot_resume_execution(tmp_path, monkeypatch, kind):
    from unittest.mock import MagicMock

    from agentv_runtime.interfaces import ApprovalRequest
    from eval_runner.reference.inprocess_backend import InProcessExecutionBackend
    from eval_runner.reference.sqlite_checkpoint import SQLiteCheckpointStore

    provider, bus = _recorded_fault_environment(tmp_path)
    approvals = (
        FileApprovalStore(tmp_path / "approvals")
        if kind == "file"
        else SQLiteApprovalStore(tmp_path / "approvals.db")
    )
    pending = approvals.create_request(
        ApprovalRequest(
            approval_token="revoked-token",
            run_id="fault-run",
            action_payload={"amount": 100},
        )
    )
    FaultDeliveryController("fault-run", bus).approval_fault(
        "approval_revocation", approvals, pending, node_id="transfer"
    )
    with pytest.raises(ValueError, match="cannot be republished"):
        approvals.create_request(pending)
    checkpoints = SQLiteCheckpointStore(tmp_path / "checkpoints.db")
    checkpoints.save(
        "fault-run",
        "approval-checkpoint",
        {
            "status": "PAUSED_FOR_APPROVAL",
            "scenario_data": {"id": "scenario"},
            "session_state": {"approval_token": "revoked-token", "action_payload": {"amount": 100}},
        },
    )
    provider.update_run_status("fault-run", "PAUSED_FOR_APPROVAL")
    monkeypatch.setattr("eval_runner.runtime_services.resolve_approval_store", lambda: approvals)
    execute = MagicMock(side_effect=AssertionError("A revoked grant must not execute"))
    backend = InProcessExecutionBackend(
        run_store=provider,
        checkpoint_store=checkpoints,
        runner_callable=execute,
    )
    with pytest.raises(PermissionError, match="not been authoritatively approved"):
        backend.resume("fault-run", resumption_token="revoked-token", background=False)
    execute.assert_not_called()


@pytest.mark.parametrize("kind", ["file", "sqlite"])
def test_approval_decision_race_serializes_independent_provider_instances(tmp_path, kind):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from agentv_runtime.interfaces import ApprovalRequest

    if kind == "file":
        first, second = (FileApprovalStore(tmp_path / "approvals") for _ in range(2))
    else:
        first, second = (SQLiteApprovalStore(tmp_path / "approvals.db") for _ in range(2))
    first.create_request(ApprovalRequest(approval_token="competing", run_id="run"))
    barrier = Barrier(2)

    def decide(store, decision):
        barrier.wait(timeout=10)
        try:
            store.resolve_request("competing", decision)
        except ValueError as exc:
            assert "resolved" in str(exc)
            return None
        return decision

    with ThreadPoolExecutor(max_workers=2) as executor:
        approve = executor.submit(decide, first, "APPROVED")
        reject = executor.submit(decide, second, "REJECTED")
        winners = [
            result for result in (approve.result(timeout=15), reject.result(timeout=15)) if result
        ]
    assert len(winners) == 1
    assert first.get_request("competing").status == winners[0]
    assert second.get_request("competing").status == winners[0]


def test_each_execution_instance_requires_its_own_fault_observation(tmp_path):
    provider, bus = _recorded_fault_environment(tmp_path)
    controller = FaultDeliveryController("fault-run", bus)
    controller.cancel_at_tool_boundary("transfer", "write", execution_id="transfer:attempt:1")
    for attempt in (1, 2):
        bus.emit_evidence(
            "execution_graph_node",
            {
                "run_id": "fault-run",
                "scenario_node_id": "transfer",
                "status": "completed",
                "execution_instance_id": f"transfer:attempt:{attempt}",
            },
        )
    failures = fault_receipt_failures(
        provider.get_events("fault-run"), [("cancel_race", "transfer")], run_id="fault-run"
    )
    assert any("MutationDeliveryEvidenceMissing" in failure for failure in failures)
    controller.cancel_at_tool_boundary("transfer", "write", execution_id="transfer:attempt:2")
    assert (
        fault_receipt_failures(
            provider.get_events("fault-run"), [("cancel_race", "transfer")], run_id="fault-run"
        )
        == []
    )


def test_injected_cancellation_reaches_backend_terminal_status(tmp_path):
    from eval_runner.reference.inprocess_backend import InProcessExecutionBackend

    provider, bus = _recorded_fault_environment(tmp_path)

    def execute(scenario, **kwargs):
        FaultDeliveryController(
            "fault-run", bus, kwargs["cancellation_event"]
        ).cancel_at_tool_boundary("transfer", "write")
        return {"status": "completed"}

    backend = InProcessExecutionBackend(run_store=provider, runner_callable=execute)
    backend.submit(run_id="fault-run", scenario_data={"id": "scenario"}, background=False)
    assert backend.status("fault-run")["status"] == "ABORTED"
    assert provider.get_run("fault-run")["status"] == "ABORTED"


@pytest.mark.parametrize("workflow_list", [False, True])
@pytest.mark.parametrize("fault", ["commit_after_cancel", "approval_race", "approval_revocation"])
def test_boundary_mutations_compile_requests_without_fabricating_results(workflow_list, fault):
    from eval_runner.mutations.mutator import MutationService

    nodes = [{"id": "transfer"}]
    scenario = {"id": "scenario", "workflow": nodes if workflow_list else {"nodes": nodes}}
    mutated = MutationService().mutate_scenario(scenario, fault)
    node = mutated["workflow"][0] if workflow_list else mutated["workflow"]["nodes"][0]
    assert node[fault] is True
    assert "revocation_timestamp" not in node
    assert "approval_status" not in node
    assert "mutation_receipt" not in node


@pytest.fixture
def sample_node() -> dict:
    return {
        "id": "transfer_node",
        "task_description": "Transfer funds to beneficiary",
        "parameters": {"amount": 500.0, "account": "ACC_1001"},
    }


def test_plugin_step_lifecycle(sample_node):
    """Verifies on_step_start and on_step_end tracking."""
    plugin = RuntimeMutationPlugin()
    assert plugin.step_index == 0
    assert plugin.active_node_id is None

    plugin.on_step_start(None, "transfer_node", sample_node)
    assert plugin.step_index == 1
    assert plugin.active_node_id == "transfer_node"
    assert plugin.active_node_data == sample_node

    plugin.on_step_end(None, "transfer_node", "success")
    assert plugin.active_node_id is None
    assert plugin.active_node_data == {}


@pytest.mark.asyncio
async def test_parallel_nodes_keep_mutation_context_isolated(sample_node, tmp_path):
    plugin = RuntimeMutationPlugin()

    async def invoke(node_id, node):
        _, bus = _recorded_fault_environment(tmp_path / node_id, node_id)
        sandbox = ToolSandbox({"run_id": node_id}, event_bus=bus)
        plugin.on_step_start(sandbox, node_id, node)
        await asyncio.sleep(0)
        request = plugin.on_tool_request(None, "execute_wire", {})
        return request if isinstance(request, dict) else plugin.on_tool_execution(None, {})

    timeout, cancellation = await asyncio.gather(
        invoke("timeout", dict(sample_node, timeout_boundary_ms=10)),
        invoke("cancel", dict(sample_node, cancel_at_boundary=True)),
    )

    assert timeout["fault_plan"]["timeout_boundary_ms"] == 10
    assert cancellation["short_circuit_result"]["fault"] == "cancel_race"


def test_tool_timeout_boundary_interception(sample_node):
    """Selecting a deadline must not fabricate a timed-out execution."""
    node = dict(sample_node, timeout_boundary_ms=100)
    plugin = RuntimeMutationPlugin()
    plugin.on_step_start(None, "node_1", node)

    res = plugin.on_tool_request(None, "execute_wire", {"amount": 500.0})
    assert res is True
    assert plugin.on_tool_execution(None, {})["fault_plan"]["timeout_boundary_ms"] == 100
    assert plugin.applied_mutations == []


def test_tool_cancel_race_interception(sample_node, tmp_path):
    """Verifies cancel_race condition short-circuits tool execution."""
    node = dict(sample_node, cancel_at_boundary=True)
    plugin = RuntimeMutationPlugin()
    _, bus = _recorded_fault_environment(tmp_path, "cancel-race")
    sandbox = ToolSandbox({"run_id": "cancel-race"}, event_bus=bus)
    plugin.on_step_start(sandbox, "node_1", node)

    res = plugin.on_tool_request(None, "execute_wire", {"amount": 500.0})
    assert isinstance(res, dict)
    assert "short_circuit_result" in res
    err = res["short_circuit_result"]
    assert err["fault"] == "cancel_race"
    assert "TaskCancelled" in err["error"]
    assert sandbox.cancellation_event.is_set()


def test_tool_malformed_payload_interception(sample_node):
    """Verifies raw malformed payload injection."""
    node = dict(sample_node, raw_payload_corrupted='{"unclosed_json: true')
    plugin = RuntimeMutationPlugin()
    plugin.on_step_start(None, "node_1", node)

    res = plugin.on_tool_request(None, "execute_wire", {"amount": 500.0})
    assert res is True
    assert (
        plugin.on_tool_execution(None, {})["fault_plan"]["raw_payload_corrupted"]
        == node["raw_payload_corrupted"]
    )
    assert plugin.applied_mutations == []


@pytest.mark.asyncio
async def test_tool_response_corruption_is_applied_after_execution(sample_node, tmp_path):
    plugin = RuntimeMutationPlugin()
    provider, bus = _recorded_fault_environment(tmp_path)
    plugins = PluginManager()
    plugins.plugins = [plugin]
    sandbox = ToolSandbox(
        {
            "run_id": "fault-run",
            "tools": {"execute_wire": {"output": {"status": "success", "amount": 500}}},
        },
        event_bus=bus,
        plugin_manager=plugins,
    )
    plugin.on_step_start(sandbox, "node_1", dict(sample_node, tool_response_corrupted=True))
    original = await sandbox.execute("execute_wire", {})

    result = plugin.on_tool_result(None, "execute_wire", original)

    assert result["result"]["status"] == "error"
    assert result["result"]["mutation_fault"] == "tool_response_corruption"
    assert "mutation_receipt" not in result
    assert not any(
        event["event"] == "mutation_delivery" for event in provider.get_events("fault-run")
    )
    sandbox.tool_faults.acknowledge(sandbox.tool_faults.take_delivery_context(), result["result"])
    assert (
        fault_receipt_failures(
            provider.get_events("fault-run"), [("tool_response_corruption", "node_1")]
        )
        == []
    )


def test_tool_contract_violation_interception(sample_node, tmp_path):
    """Verifies tool contract violation mutates arguments with forbidden properties."""
    node = dict(sample_node, tool_contract_violation=True)
    plugin = RuntimeMutationPlugin()
    _, bus = _recorded_fault_environment(tmp_path)
    sandbox = ToolSandbox({"run_id": "fault-run"}, event_bus=bus)
    plugin.on_step_start(sandbox, "node_1", node)

    res = plugin.on_tool_request(None, "execute_wire", {"amount": 500.0})
    assert isinstance(res, dict)
    assert "arguments" in res
    assert "_unexpected_forbidden_property" in res["arguments"]


def test_state_partial_commit_interception(sample_node, tmp_path):
    """Verifies partial_commit drops all keys after the first step."""
    node = dict(sample_node, partial_commit_simulated=True)
    plugin = RuntimeMutationPlugin()
    plugin.on_step_start(None, "node_1", node)

    state_diff = {"balance": 9500.0, "status": "completed", "ledger_id": "L123"}
    _, bus = _recorded_fault_environment(tmp_path)
    sandbox = ToolSandbox({"run_id": "fault-run"}, event_bus=bus)
    res = plugin.on_before_commit(sandbox, state_diff)
    assert isinstance(res, dict)
    assert res["partial_ticket"]["applicable"] is True
    assert "mutation_receipt" not in res
    assert len(res["state_diff"]) == 1
    assert "balance" in res["state_diff"]
    assert "status" not in res["state_diff"]


@pytest.mark.asyncio
async def test_partial_commit_mutates_actual_sandbox_state(sample_node, tmp_path):
    plugin = RuntimeMutationPlugin()
    plugin.on_step_start(None, "node_1", dict(sample_node, partial_commit_simulated=True))
    manager = PluginManager()
    manager.plugins = [plugin]
    events = []
    scenario = {
        "id": "commit_fault",
        "run_id": "commit_fault_run",
        "tools": {
            "update": {
                "state_changes": [
                    {"path": "balance", "value": 900},
                    {"path": "status", "value": "completed"},
                ],
                "output": {"status": "success"},
            }
        },
    }
    from eval_runner.events import EventEmitter

    bus = EventEmitter(run_id="commit_fault_run")
    bus.subscribe(lambda event: events.append(event.to_dict()), required=True)
    sandbox = ToolSandbox(scenario, event_bus=bus, plugin_manager=manager, workspace_root=tmp_path)

    result = await sandbox.execute("update", {})

    assert result["status"] == "success"
    assert sandbox.state == {"balance": 900}
    assert any(event.get("event") == "mutation_delivery" for event in events)


def test_state_stale_commit_interception(sample_node):
    """Verifies stale_commit blocks commit with optimistic lock error."""
    node = dict(sample_node, stale_commit=True, expected_base_revision="rev_1970")
    plugin = RuntimeMutationPlugin()
    plugin.on_step_start(None, "node_1", node)

    res = plugin.on_before_commit(None, {"balance": 9000.0})
    assert isinstance(res, dict)
    assert res == {"stale_commit_requested": {"node_id": "node_1"}}
    assert plugin.applied_mutations == []


def test_rollback_failure_interception(sample_node):
    """Verifies rollback_failure blocks compensating rollback execution."""
    node = dict(sample_node, rollback_handler_corrupted=True)
    plugin = RuntimeMutationPlugin()
    plugin.on_step_start(None, "node_1", node)

    allowed = plugin.on_rollback(None, {"action": "undo_wire"})
    assert allowed["runtime_fault"]["fault"] == "rollback_failure"


def test_approval_interceptions_and_manager_integration(sample_node, tmp_path):
    """Verifies stale, mismatch, revocation, and race approval rejections in approval manager."""
    pm = PluginManager()
    plugin = RuntimeMutationPlugin()
    pm.plugins.append(plugin)

    run_store, bus = _recorded_fault_environment(tmp_path, "run_test")
    approval_mgr = SessionApprovalManager(
        run_id="run_test",
        plugin_manager=pm,
        run_store=run_store,
        event_bus=bus,
    )

    # 1. Stale Token
    plugin.on_step_start(None, "node_1", {"approval_stale": True})
    with pytest.raises(PermissionError, match="ApprovalRejected: observed approval_stale"):
        approval_mgr.create_durable_request(
            turn_index=1,
            action_payload={"tool_name": "wire_tool", "amount": 100},
            metadata={"task_id": "task_1"},
        )

    # 2. Transaction Mismatch
    plugin.on_step_start(None, "node_1", {"approval_mismatch": True})
    with pytest.raises(PermissionError, match="ApprovalRejected: observed approval_mismatch"):
        approval_mgr.create_durable_request(
            turn_index=1,
            action_payload={"tool_name": "wire_tool", "amount": 100},
            metadata={"task_id": "task_1"},
        )

    # 3. Revocation
    plugin.on_step_start(None, "node_1", {"approval_revocation": True})
    with pytest.raises(PermissionError, match="ApprovalRejected: observed approval_revocation"):
        approval_mgr.create_durable_request(
            turn_index=1,
            action_payload={"tool_name": "wire_tool", "amount": 100},
            metadata={"task_id": "task_1"},
        )

    # A fault introduced after the durable request exists must also prevent
    # the persisted decision from being resolved and resuming the workflow.
    plugin.on_step_start(None, "node_1", {})
    durable_request = approval_mgr.create_durable_request(turn_index=1)
    plugin.on_step_start(None, "node_1", {"approval_revocation": True})
    with pytest.raises(PermissionError, match="ApprovalRejected: observed approval_revocation"):
        approval_mgr.resolve_durable_request(durable_request.approval_token, "APPROVED")
    assert approval_mgr.get_durable_request(durable_request.approval_token).status == "REJECTED"

    # 5. Approval Race
    plugin.on_step_start(None, "node_1", {"approval_race": True})
    with pytest.raises(PermissionError, match="ApprovalRejected: observed approval_race"):
        approval_mgr.create_durable_request(
            turn_index=1,
            action_payload={"tool_name": "wire_tool", "amount": 100},
            metadata={"task_id": "task_1"},
        )


def test_runtime_mutation_before_evaluation_and_clean_fallbacks(tmp_path):
    # 1. context.scenario_data branch
    class ContextData:
        scenario_data = {"id": "scen_data_1"}

    p1 = RuntimeMutationPlugin()
    p1.before_evaluation(ContextData())
    assert p1.scenario == {"id": "scen_data_1"}

    # 2. context.scenario branch
    class ContextScen:
        scenario = {"id": "scen_fallback"}

    p2 = RuntimeMutationPlugin()
    p2.before_evaluation(ContextScen())
    assert p2.scenario == {"id": "scen_fallback"}

    # 3. on_tool_request default clean pass-through
    p3 = RuntimeMutationPlugin()
    p3.on_step_start(None, "n1", {})
    assert p3.on_tool_request(None, "any_tool", {"k": "v"}) is True

    # 4. on_before_commit with single-key diff in partial commit
    p4 = RuntimeMutationPlugin()
    p4.on_step_start(None, "n2", {"partial_commit_simulated": True})
    _, bus = _recorded_fault_environment(tmp_path)
    sandbox = ToolSandbox({"run_id": "fault-run"}, event_bus=bus)
    res_single = p4.on_before_commit(sandbox, {"single_key": 1})
    assert isinstance(res_single, dict)
    assert res_single["state_diff"] == {"single_key": 1}

    # 5. on_before_commit commit_after_cancel fault
    p5 = RuntimeMutationPlugin()
    p5.on_step_start(None, "n3", {"commit_after_cancel": True})
    with pytest.raises(FaultDeliveryError, match="actual sandbox boundary"):
        p5.on_before_commit(None, {"any": 2})
    assert p5.applied_mutations == []

    # 6. on_before_commit clean pass-through
    p6 = RuntimeMutationPlugin()
    p6.on_step_start(None, "n4", {})
    assert p6.on_before_commit(None, {"a": 1}) is True

    # 7. on_rollback clean pass-through and scenario policy corruption
    p7 = RuntimeMutationPlugin(scenario={"failure_policy": {"rollback_handler_corrupted": True}})
    p7.on_step_start(None, "n5", {})
    assert p7.on_rollback(None, {"action": "undo"})["runtime_fault"]["fault"] == "rollback_failure"

    p7_meta = RuntimeMutationPlugin(scenario={"metadata": {"rollback_handler_corrupted": True}})
    p7_meta.on_step_start(None, "n6", {})
    assert (
        p7_meta.on_rollback(None, {"action": "undo"})["runtime_fault"]["fault"]
        == "rollback_failure"
    )

    p7_clean = RuntimeMutationPlugin()
    p7_clean.on_step_start(None, "n7", {})
    assert p7_clean.on_rollback(None, {"action": "undo"}) is True

    # 8. on_approval_request clean pass-through
    p8 = RuntimeMutationPlugin()
    p8.on_step_start(None, "n8", {})
    assert p8.on_approval_request(None, {"token": "valid"}) is True


@pytest.mark.asyncio
async def test_tool_execute_latency_unjittered_when_timeout_set(tmp_path):
    provider, session, _ = _tool_fault_session(
        tmp_path, {"timeout_boundary_ms": 5000, "injected_latency_ms": 10}
    )
    res = await session.sandbox.execute("write", {})
    assert res["status"] == "success"
    events = provider.get_events("fault-run")
    delays = [
        e["evidence"]["observation"]
        for e in events
        if "evidence" in e and e["evidence"].get("kind") == "tool_delay_elapsed"
    ]
    assert len(delays) == 1
    # When timeout_boundary_ms is set, delay MUST be unjittered exact latency_ms / 1000
    assert delays[0]["requested_seconds"] == 0.010


@pytest.mark.asyncio
async def test_tool_execute_deadline_validation_and_premature_cancellation(tmp_path):
    # 1. Invalid negative or NaN timeout_ms
    _, s_neg_t, _ = _tool_fault_session(tmp_path, {"timeout_boundary_ms": -5})
    with pytest.raises(ValueError, match="Tool deadline must be a positive duration"):
        await s_neg_t.sandbox.execute("write", {})

    _, s_nan_t, _ = _tool_fault_session(tmp_path, {"timeout_boundary_ms": float("nan")})
    with pytest.raises(ValueError, match="Tool deadline must be a positive duration"):
        await s_nan_t.sandbox.execute("write", {})

    # 2. Invalid negative or NaN latency_ms
    _, s_neg_l, _ = _tool_fault_session(tmp_path, {"injected_latency_ms": -5})
    with pytest.raises(ValueError, match="Tool latency must be nonnegative"):
        await s_neg_l.sandbox.execute("write", {})

    _, s_nan_l, _ = _tool_fault_session(tmp_path, {"injected_latency_ms": float("nan")})
    with pytest.raises(ValueError, match="Tool latency must be nonnegative"):
        await s_nan_l.sandbox.execute("write", {})

    # 3. Premature cancellation before timeout expired re-raises TimeoutError
    _, s_premature, _ = _tool_fault_session(tmp_path, {"timeout_boundary_ms": 5000})

    async def cancel_self(**kwargs):
        asyncio.current_task().cancel()
        raise TimeoutError("Premature task cancellation")

    s_premature.sandbox._execute_core = cancel_self
    with pytest.raises(TimeoutError, match="Premature task cancellation"):
        await s_premature.sandbox.execute("write", {})


def test_prepare_corruption_mismatched_node_raises(tmp_path):
    provider, bus = _recorded_fault_environment(tmp_path)
    controller = FaultDeliveryController("fault-run", bus)

    class DummySandbox:
        fault_controller = controller
        plugin_manager = None

    executor = ToolFaultExecutor(DummySandbox())
    ticket = {
        "identity": {"fault": "tool_response_corruption", "node_id": "node_correct"},
        "refs": [],
    }
    executor.pending.set({"tickets": [ticket]})
    with pytest.raises(
        RuntimeError, match="Response mutation does not own the completed invocation"
    ):
        executor.prepare_corruption({"orig": 1}, {"mod": 2}, node="node_wrong", execution="exec1")


def test_runtime_fault_identity_empty_run_id_raises():
    # EventEmitter with matching run_id
    bus = EventEmitter(run_id="run-valid", async_mode=False)
    controller = FaultDeliveryController("run-valid", bus)

    # Mutant [1]: self.run_id == "" with matching bus.run_id == ""
    bus_empty = EventEmitter(run_id="", async_mode=False)
    c_empty_run = FaultDeliveryController("", bus_empty)
    with pytest.raises(
        FaultDeliveryError, match="Fault injection requires a run, node and evidence sink"
    ):
        c_empty_run._identity("some_fault", "n1")

    # Mutant [2]: node_id is not str (e.g. int)
    with pytest.raises(
        FaultDeliveryError, match="Fault injection requires a run, node and evidence sink"
    ):
        controller._identity("some_fault", 12345)

    # Mutant [3]: node_id is empty string
    with pytest.raises(
        FaultDeliveryError, match="Fault injection requires a run, node and evidence sink"
    ):
        controller._identity("some_fault", "")

    # Mutant [4]: execution_id is not str (e.g. int)
    with pytest.raises(
        FaultDeliveryError, match="Fault injection requires a run, node and evidence sink"
    ):
        controller._identity("some_fault", "n1", execution_id=12345)

    # Mutant [5]: event_bus is None
    c_no_bus = FaultDeliveryController("run-valid", None)
    with pytest.raises(
        FaultDeliveryError, match="Fault injection requires a run, node and evidence sink"
    ):
        c_no_bus._identity("some_fault", "n1")

    # Mutant [6]: bus has no callable emit_evidence
    c_bad_bus = FaultDeliveryController("run-valid", object())
    with pytest.raises(
        FaultDeliveryError, match="Fault injection requires a run, node and evidence sink"
    ):
        c_bad_bus._identity("some_fault", "n1")

    # Mutant [7]: bus run_id mismatch
    bus_mismatch = EventEmitter(run_id="run-other", async_mode=False)
    c_mismatch = FaultDeliveryController("run-valid", bus_mismatch)
    with pytest.raises(
        FaultDeliveryError, match="Fault injection requires a run, node and evidence sink"
    ):
        c_mismatch._identity("some_fault", "n1")


def test_runtime_fault_receipt_invalid_delivery_raises(tmp_path):
    provider, bus = _recorded_fault_environment(tmp_path)
    controller = FaultDeliveryController("fault-run", bus)
    identity = controller._identity("test_fault", "n1")
    ref = {"event_id": "e1", "evidence_hash": "h1"}
    with pytest.raises(FaultDeliveryError, match="A delivery decision requires bound observations"):
        controller._receipt(identity, [ref], {"obs": 1}, delivery="INVALID_STATUS")


def test_runtime_fault_observe_cancelled_commit_diff_mismatch_raises(tmp_path):
    provider, bus = _recorded_fault_environment(tmp_path)
    controller = FaultDeliveryController("fault-run", bus)
    controller.cancellation_event.set()
    ident = controller._identity("commit_after_cancel", "n1")
    ticket = {
        "identity": ident,
        "evidence_refs": [],
        "before_hash": evidence_hash({"before": 0}),
        "diff": {"target_field": "expected_value", "k2": "v2"},
    }
    with pytest.raises(FaultDeliveryError, match="Post-cancellation state change was not observed"):
        controller.observe_cancelled_commit(
            ticket, after={"before": 1, "target_field": "expected_value", "k2": "wrong_value"}
        )


def test_runtime_approval_fault_cleanup_on_approved(tmp_path):
    provider, bus = _recorded_fault_environment(tmp_path, run_id="fault-run")
    controller = FaultDeliveryController("fault-run", bus)
    mock_store = MagicMock()
    req = ApprovalRequest(
        approval_token="tok-cleanup", run_id="fault-run", status="PENDING", metadata={}
    )
    req_approved = ApprovalRequest(
        approval_token="tok-cleanup", run_id="fault-run", status="APPROVED", metadata={}
    )
    mock_store.get_request.return_value = req_approved
    with patch.object(
        controller, "_execute_approval_fault", side_effect=RuntimeError("Simulated failure")
    ):
        with pytest.raises(RuntimeError, match="Simulated failure"):
            controller.approval_fault("approval_race", mock_store, req, None, node_id="n1")
    mock_store.revoke_request.assert_called_with(
        "tok-cleanup", decided_by="fault-cleanup", scope=None
    )


def test_runtime_execute_approval_fault_matrix(tmp_path):
    provider, bus = _recorded_fault_environment(tmp_path, run_id="fault-run")
    controller = FaultDeliveryController("fault-run", bus)

    # Mutant [45]: current.run_id != self.run_id in _execute_approval_fault
    mock_store = MagicMock()
    req_cross = ApprovalRequest(
        approval_token="tok-cross", run_id="other-run", status="PENDING", metadata={}
    )
    mock_store.get_request.return_value = req_cross
    with pytest.raises(FaultDeliveryError, match="Approval fault does not own the durable request"):
        controller._execute_approval_fault(
            "approval_revocation", mock_store, req_cross, node_id="n1"
        )

    # Mutant [61]: approval_revocation replay reapproves with status="APPROVED"
    req_own = ApprovalRequest(
        approval_token="tok-rev", run_id="fault-run", status="PENDING", metadata={}
    )
    req_granted = ApprovalRequest(
        approval_token="tok-rev", run_id="fault-run", status="APPROVED", metadata={}
    )
    req_revoked = ApprovalRequest(
        approval_token="tok-rev",
        run_id="fault-run",
        status="REJECTED",
        metadata={"revocation": True},
    )
    mock_store.get_request.side_effect = [req_own, req_revoked, req_revoked]
    mock_store.resolve_request.side_effect = [req_granted, ValueError("Cannot reapprove")]
    mock_store.revoke_request.return_value = req_revoked
    controller._execute_approval_fault("approval_revocation", mock_store, req_own, node_id="n1")
    assert mock_store.resolve_request.call_args_list[1][0][1] == "APPROVED"

    # Mutant [79]: len(winners) != 1 with observed.status matching winners[0]["decision"]
    req_race = ApprovalRequest(
        approval_token="tok-race", run_id="fault-run", status="PENDING", metadata={}
    )
    req_app = ApprovalRequest(
        approval_token="tok-race", run_id="fault-run", status="APPROVED", metadata={}
    )
    mock_store_race = MagicMock()
    mock_store_race.get_request.side_effect = [req_race, req_app]
    # Both contenders resolve with decision="APPROVED" (so winners has 2 items,
    # and decisions match):
    mock_store_race.resolve_request.side_effect = [
        ApprovalRequest(
            approval_token="tok-race", run_id="fault-run", status="APPROVED", metadata={}
        ),
        ApprovalRequest(
            approval_token="tok-race", run_id="fault-run", status="APPROVED", metadata={}
        ),
    ]
    with pytest.raises(
        FaultDeliveryError, match="Approval provider did not serialize competing decisions"
    ):
        controller._execute_approval_fault("approval_race", mock_store_race, req_race, node_id="n1")

    # Mutant [80]: observed.status != winners[0]["decision"]
    mock_store_mismatch = MagicMock()
    req_app = ApprovalRequest(
        approval_token="tok-race", run_id="fault-run", status="APPROVED", metadata={}
    )
    req_rej = ApprovalRequest(
        approval_token="tok-race", run_id="fault-run", status="REJECTED", metadata={}
    )
    mock_store_mismatch.get_request.side_effect = [req_race, req_app, req_rej]
    # Use side_effect function based on decision argument so thread order doesn't matter:
    mock_store_mismatch.resolve_request.side_effect = lambda token, dec, **kw: (
        req_app if dec == "APPROVED" else (_ for _ in ()).throw(ValueError("Race lost"))
    )
    with pytest.raises(
        FaultDeliveryError, match="Approval provider did not serialize competing decisions"
    ):
        controller._execute_approval_fault(
            "approval_race", mock_store_mismatch, req_race, node_id="n1"
        )

    # Mutant [85]: if observed.status == "APPROVED" in race, cleanup revokes it
    mock_store_app_win = MagicMock()
    mock_store_app_win.get_request.side_effect = [req_race, req_app, req_app]
    mock_store_app_win.resolve_request.side_effect = lambda token, dec, **kw: (
        req_app if dec == "APPROVED" else (_ for _ in ()).throw(ValueError("Race lost"))
    )
    mock_store_app_win.revoke_request.return_value = req_rej
    receipt = controller._execute_approval_fault(
        "approval_race", mock_store_app_win, req_race, node_id="n1"
    )
    assert receipt["observed"]["winner"] == "APPROVED"
    assert receipt["observed"]["status"] == "REJECTED"
    mock_store_app_win.revoke_request.assert_called_with(
        "tok-race", decided_by="fault-race-cleanup", scope=None
    )


def test_approval_revocation_requires_rejected_status_and_metadata(tmp_path):
    provider, bus = _recorded_fault_environment(tmp_path)
    controller = FaultDeliveryController("fault-run", bus)

    # Subcase 1: status is APPROVED (not REJECTED) after revocation
    mock_store = MagicMock()
    req_approved = ApprovalRequest(
        approval_token="tok1", run_id="fault-run", status="APPROVED", metadata={}
    )
    req_after_approved = ApprovalRequest(
        approval_token="tok1",
        run_id="fault-run",
        status="APPROVED",
        metadata={"revocation": True},
    )
    mock_store.get_request.side_effect = [req_approved, req_after_approved]
    with pytest.raises(FaultDeliveryError, match="Revocation was not durably observed"):
        controller._execute_approval_fault(
            "approval_revocation",
            mock_store,
            req_approved,
            scope=None,
            node_id="n1",
            execution_id="e1",
        )

    # Subcase 2: status is REJECTED but metadata has no revocation flag
    req_after_no_meta = ApprovalRequest(
        approval_token="tok1", run_id="fault-run", status="REJECTED", metadata={}
    )
    mock_store.get_request.side_effect = [req_approved, req_after_no_meta]
    with pytest.raises(FaultDeliveryError, match="Revocation was not durably observed"):
        controller._execute_approval_fault(
            "approval_revocation",
            mock_store,
            req_approved,
            scope=None,
            node_id="n1",
            execution_id="e1",
        )


def test_deliver_authorization_fault_cross_run_ownership_mismatch(tmp_path):
    provider, bus = _recorded_fault_environment(tmp_path, run_id="run-A")
    controller = FaultDeliveryController("run-A", bus)
    mock_store = MagicMock()
    req = ApprovalRequest(approval_token="tok-cross", run_id="run-B", status="PENDING", metadata={})
    mock_store.get_request.return_value = req
    with pytest.raises(
        FaultDeliveryError, match="Authorization fault does not own the durable request"
    ):
        deliver_authorization_fault(controller, "approval_stale", mock_store, req, None, "n1", "e1")


def test_deliver_authorization_fault_guards_and_stale_pre_approved(tmp_path):
    import time

    from eval_runner.approval_validation import ApprovalValidationError

    provider, bus = _recorded_fault_environment(tmp_path)
    controller = FaultDeliveryController("fault-run", bus)

    # 1. Store has consume_request but lacks revoke_request
    mock_store_no_revoke = MagicMock(spec=["get_request", "consume_request"])
    req = ApprovalRequest(approval_token="tok1", run_id="fault-run", status="PENDING", metadata={})
    mock_store_no_revoke.get_request.return_value = req
    with pytest.raises(FaultDeliveryError, match="Provider lacks atomic consumption or revocation"):
        deliver_authorization_fault(
            controller, "approval_stale", mock_store_no_revoke, req, None, "n1", "e1"
        )

    # 2. Store has revoke_request but lacks consume_request
    mock_store_no_consume = MagicMock(spec=["get_request", "revoke_request"])
    mock_store_no_consume.get_request.return_value = req
    with pytest.raises(FaultDeliveryError, match="Provider lacks atomic consumption or revocation"):
        deliver_authorization_fault(
            controller, "approval_stale", mock_store_no_consume, req, None, "n1", "e1"
        )

    # 3. Request already APPROVED for approval_stale does not re-resolve
    mock_store = MagicMock()
    mock_store.consume_request.side_effect = ApprovalValidationError("ApprovalExpired")
    mock_store.revoke_request.return_value = ApprovalRequest(
        approval_token="tok1", run_id="fault-run", status="REJECTED", metadata={}
    )
    req_approved = ApprovalRequest(
        approval_token="tok1",
        run_id="fault-run",
        status="APPROVED",
        metadata={"expires_at": time.time() - 100},
    )
    mock_store.get_request.return_value = req_approved

    receipt = deliver_authorization_fault(
        controller, "approval_stale", mock_store, req_approved, None, "n1", "e1"
    )
    assert receipt.get("delivery") == "DELIVERED"
    assert not mock_store.resolve_request.called


def test_valid_fault_observations_rejects_mixed_non_mapping():
    receipt = {
        "fault": "cancel_race",
        "observed": {"tool_dispatched": False, "cancelled": True, "tool": "t"},
    }
    obs = {
        "cancellation_requested": {
            "cancelled": True,
            "tool_dispatched": False,
            "tool": "t",
        },
        "corrupted_extra": "not_a_mapping",
    }
    assert _valid_fault_observations(receipt, obs) is False


def test_valid_fault_observations_approval_and_race_matrix():
    # 1. Approval token validation:
    valid_rev_observed = {
        "approval_token": "tok1",
        "status": "REJECTED",
        "replay_blocked": True,
    }
    valid_rev_obs = {
        "approval_granted": {"approval_token": "tok1", "status": "APPROVED"},
        "approval_revoked": {"approval_token": "tok1", "status": "REJECTED"},
        "approval_replay_blocked": {"approval_token": "tok1", "blocked": True},
    }
    receipt_rev = {"fault": "approval_revocation", "observed": valid_rev_observed}
    assert _valid_fault_observations(receipt_rev, valid_rev_obs) is True

    # Mutant [89]: not token or any(...) -> not token and any(...)
    rev_obs_no_token = {
        "approval_granted": {"approval_token": "", "status": "APPROVED"},
        "approval_revoked": {"approval_token": "", "status": "REJECTED"},
        "approval_replay_blocked": {"approval_token": "", "blocked": True},
    }
    receipt_rev_no_token = {
        "fault": "approval_revocation",
        "observed": {"approval_token": "", "status": "REJECTED", "replay_blocked": True},
    }
    assert _valid_fault_observations(receipt_rev_no_token, rev_obs_no_token) is False

    # Mutant [91]: any -> all
    obs_one_mismatch = {
        "approval_granted": {"approval_token": "tok1", "status": "APPROVED"},
        "approval_revoked": {"approval_token": "tok_WRONG", "status": "REJECTED"},
        "approval_replay_blocked": {"approval_token": "tok1", "blocked": True},
    }
    assert _valid_fault_observations(receipt_rev, obs_one_mismatch) is False

    # 2. Contenders validation for approval_race
    c_approved = {"decision": "APPROVED", "accepted": False}
    c_rejected = {"decision": "REJECTED", "accepted": True}
    valid_race_obs = {
        "approval_token": "tok1",
        "contenders": [c_approved, c_rejected],
        "status": "REJECTED",
    }
    valid_receipt = {
        "fault": "approval_race",
        "observed": {
            "approval_token": "tok1",
            "contenders": [c_approved, c_rejected],
            "winner": "REJECTED",
            "status": "REJECTED",
        },
    }
    valid_obs_map = {
        "approval_before": {"approval_token": "tok1", "status": "PENDING"},
        "approval_race_observed": valid_race_obs,
    }
    assert _valid_fault_observations(valid_receipt, valid_obs_map) is True

    # Mutant [105]: len(contenders) != 2 or any(...) -> and
    c_extra_lose = {"decision": "REJECTED", "accepted": False}
    race_three_contenders = {
        "approval_token": "tok1",
        "contenders": [c_approved, c_rejected, c_extra_lose],
        "status": "REJECTED",
    }
    receipt_three = {
        "fault": "approval_race",
        "observed": {
            "approval_token": "tok1",
            "contenders": [c_approved, c_rejected, c_extra_lose],
            "winner": "REJECTED",
            "status": "REJECTED",
        },
    }
    obs_three_c = {**valid_obs_map, "approval_race_observed": race_three_contenders}
    assert _valid_fault_observations(receipt_three, obs_three_c) is False

    # Mutant [106] & [109]: any(not isinstance(row, Mapping) for row in contenders) -> all
    race_mixed_contenders = {**valid_race_obs, "contenders": [c_approved, "not_a_map"]}
    obs_mixed_c = {**valid_obs_map, "approval_race_observed": race_mixed_contenders}
    assert _valid_fault_observations(valid_receipt, obs_mixed_c) is False

    # Mutant [112]: any(type(row.get("accepted")) is not bool for row in contenders) -> all
    race_int_accepted = {
        "approval_token": "tok1",
        "contenders": [{"decision": "APPROVED", "accepted": 0}, c_rejected],
        "status": "REJECTED",
    }
    receipt_int = {
        "fault": "approval_race",
        "observed": {
            "approval_token": "tok1",
            "contenders": [{"decision": "APPROVED", "accepted": 0}, c_rejected],
            "winner": "REJECTED",
            "status": "REJECTED",
        },
    }
    obs_int_accepted = {**valid_obs_map, "approval_race_observed": race_int_accepted}
    assert _valid_fault_observations(receipt_int, obs_int_accepted) is False

    # Mutant [131]: approval state REJECTED -> APPROVED at line 258
    c_app_win = {"decision": "APPROVED", "accepted": True}
    c_rej_lose = {"decision": "REJECTED", "accepted": False}
    race_approved_winner = {
        "approval_token": "tok1",
        "contenders": [c_app_win, c_rej_lose],
        "status": "APPROVED",
    }
    receipt_app_winner = {
        "fault": "approval_race",
        "observed": {
            "approval_token": "tok1",
            "contenders": [c_app_win, c_rej_lose],
            "winner": "APPROVED",
            "status": "REJECTED",
        },
    }
    obs_cleanup_approved = {
        "approval_before": {"approval_token": "tok1", "status": "PENDING"},
        "approval_race_observed": race_approved_winner,
        "approval_race_cleanup": {"approval_token": "tok1", "status": "APPROVED"},
    }
    assert _valid_fault_observations(receipt_app_winner, obs_cleanup_approved) is False


def test_fault_receipt_failures_graph_node_parsing():
    # Mutant [2]: event == "execution_graph_node" or data.status in {...}
    ev_other = {
        "event": "unrelated_event",
        "status": "completed",
        "scenario_node_id": "node_x",
        "execution_instance_id": "exec_x",
    }
    # Mutant [5] & [6]: isinstance(node, str) and isinstance(execution, str) and execution
    ev_bad_node = {
        "event": "execution_graph_node",
        "data": {
            "status": "completed",
            "scenario_node_id": 12345,
            "execution_instance_id": "exec_1",
        },
    }
    ev_empty_exec = {
        "event": "execution_graph_node",
        "data": {
            "status": "completed",
            "scenario_node_id": "node_y",
            "execution_instance_id": "",
        },
    }
    ev_bad_status = {"event": "execution_graph_node", "data": {"status": ["completed"]}}
    # Also valid delivered receipt for cancel_race on node_x
    obs_cancel = {"cancelled": True, "tool_dispatched": False, "tool": "test_tool"}
    ev_obs = {
        "event": "runtime_fault_observation",
        "data": {
            "evidence": {
                "event_id": "ev_cancel_1",
                "kind": "cancellation_requested",
                "fault": "cancel_race",
                "fault_id": "fid_1",
                "run_id": "r1",
                "node_id": "node_x",
                "execution_instance_id": "exec_valid",
                "observation": obs_cancel,
            },
            "evidence_hash": evidence_hash(
                {
                    "event_id": "ev_cancel_1",
                    "kind": "cancellation_requested",
                    "fault": "cancel_race",
                    "fault_id": "fid_1",
                    "run_id": "r1",
                    "node_id": "node_x",
                    "execution_instance_id": "exec_valid",
                    "observation": obs_cancel,
                }
            ),
        },
    }
    receipt = {
        "fault": "cancel_race",
        "fault_id": "fid_1",
        "run_id": "r1",
        "node_id": "node_x",
        "execution_instance_id": "exec_valid",
        "delivery": "DELIVERED",
        "evidence_refs": [
            {"event_id": "ev_cancel_1", "evidence_hash": ev_obs["data"]["evidence_hash"]}
        ],
        "observed": obs_cancel,
    }
    receipt["receipt_hash"] = evidence_hash(receipt)
    ev_delivery = {"event": "mutation_delivery", "data": {"mutation_receipt": receipt}}

    # On original code: ev_other is ignored, so executions['node_x'] has no extra instances.
    # On mutant [2]: ev_other adds 'exec_x' to executions['node_x'], causing subset check to fail!
    failures = fault_receipt_failures(
        [ev_other, ev_bad_node, ev_empty_exec, ev_bad_status, ev_obs, ev_delivery],
        [("cancel_race", "node_x")],
    )
    assert failures == []

    # Mutant [5] & [6]: if node is None/int or execution is non-string
    # added to executions[None], then requirement with node=None fails subset check.
    ev_ghost = {
        "event": "execution_graph_node",
        "data": {
            "status": "completed",
            "scenario_node_id": None,
            "execution_instance_id": "ghost_exec",
        },
    }
    failures_ghost = fault_receipt_failures(
        [ev_ghost, ev_obs, ev_delivery],
        [("cancel_race", None)],
    )
    assert failures_ghost == []


def test_fault_receipt_failures_observation_schema_mutations():
    # Mutants [8], [9], [10]
    for bad_ev in [
        {"event_id": "", "kind": "cancellation_requested"},
        {"event_id": "valid_id", "kind": 12345},
        {"event_id": 12345, "kind": "cancellation_requested"},
    ]:
        ev = {"event": "runtime_fault_observation", "data": {"evidence": bad_ev}}
        failures = fault_receipt_failures([ev])
        assert "InvalidMutationObservation" in failures


def test_fault_receipt_failures_ref_not_mapping():
    # Mutant [30]: ref in refs is not a Mapping
    receipt = {
        "fault": "cancel_race",
        "fault_id": "f_ref_test",
        "run_id": "r1",
        "node_id": "n1",
        "execution_instance_id": "e1",
        "delivery": "DELIVERED",
        "evidence_refs": ["not_a_mapping"],
        "observed": {},
    }
    receipt["receipt_hash"] = evidence_hash(receipt)
    event = {"event": "mutation_delivery", "data": {"mutation_receipt": receipt}}
    failures = fault_receipt_failures([event], [("cancel_race", "n1")])
    assert "InvalidMutationDeliveryEvidence:f_ref_test" in failures


def test_fault_receipt_failures_preflight_rejection_matrix():
    # Mutant [46]: event == "assertion_evaluated" or ...
    ev_not_assertion = {
        "event": "other_event",
        "oracle_id": "security:cancel_race",
        "node_id": "node_1",
        "outcome": "FAIL",
    }
    f_not_assertion = fault_receipt_failures([ev_not_assertion], [("cancel_race", "node_1")])
    assert "MutationDeliveryEvidenceMissing:cancel_race:node_1" in f_not_assertion

    # Mutant [47]: ... and outcome == "FAIL" -> or outcome == "FAIL"
    ev_pass = {
        "event": "assertion_evaluated",
        "oracle_id": "security:cancel_race",
        "node_id": "node_1",
        "outcome": "PASS",
    }
    f_pass = fault_receipt_failures([ev_pass], [("cancel_race", "node_1")])
    assert "MutationDeliveryEvidenceMissing:cancel_race:node_1" in f_pass

    ev_fail_unrelated = {
        "event": "assertion_evaluated",
        "oracle_id": "business_logic_oracle",
        "resolver": "standard_evaluator",
        "node_id": "node_1",
        "outcome": "FAIL",
    }
    f_unrelated = fault_receipt_failures([ev_fail_unrelated], [("cancel_race", "node_1")])
    assert "MutationDeliveryEvidenceMissing:cancel_race:node_1" in f_unrelated

    # Mutant [49]: startswith("security:") or resolver == "security_preflight" -> or -> and
    ev_preflight = {
        "event": "assertion_evaluated",
        "oracle_id": "cancel_race",
        "resolver": "security_preflight",
        "node_id": "node_1",
        "outcome": "FAIL",
    }
    assert "MutationDeliveryEvidenceMissing:cancel_race:node_1" in fault_receipt_failures(
        [ev_preflight], [("cancel_race", "node_1")]
    )

    # Mutant [52], [55], [57]: node=None matching and cross-node isolation
    assert "MutationDeliveryEvidenceMissing:cancel_race:*" in fault_receipt_failures(
        [ev_preflight], ["cancel_race"]
    )

    ev_preflight_n2 = {
        "event": "assertion_evaluated",
        "oracle_id": "security:cancel_race",
        "node_id": "node_2",
        "outcome": "FAIL",
    }
    f_diff_node = fault_receipt_failures([ev_preflight_n2], [("cancel_race", "node_1")])
    assert "MutationDeliveryEvidenceMissing:cancel_race:node_1" in f_diff_node

    # Mutant [60]: found_fault == fault and (node is None or found_node == node) -> and -> or
    obs_c2 = {"cancelled": True, "tool_dispatched": False, "tool": "test_tool"}
    ev_obs_c2 = {
        "event": "runtime_fault_observation",
        "data": {
            "evidence": {
                "event_id": "ev_cancel_n2",
                "kind": "cancellation_requested",
                "fault": "cancel_race",
                "fault_id": "fid_n2",
                "run_id": "r1",
                "node_id": "node_2",
                "execution_instance_id": "exec_2",
                "observation": obs_c2,
            },
            "evidence_hash": evidence_hash(
                {
                    "event_id": "ev_cancel_n2",
                    "kind": "cancellation_requested",
                    "fault": "cancel_race",
                    "fault_id": "fid_n2",
                    "run_id": "r1",
                    "node_id": "node_2",
                    "execution_instance_id": "exec_2",
                    "observation": obs_c2,
                }
            ),
        },
    }
    receipt_c2 = {
        "fault": "cancel_race",
        "fault_id": "fid_n2",
        "run_id": "r1",
        "node_id": "node_2",
        "execution_instance_id": "exec_2",
        "delivery": "DELIVERED",
        "evidence_refs": [
            {"event_id": "ev_cancel_n2", "evidence_hash": ev_obs_c2["data"]["evidence_hash"]}
        ],
        "observed": obs_c2,
    }
    receipt_c2["receipt_hash"] = evidence_hash(receipt_c2)
    ev_delivery_c2 = {"event": "mutation_delivery", "data": {"mutation_receipt": receipt_c2}}

    # Requirement is cancel_race on node_1, but delivered was cancel_race on node_2:
    f_node_mismatch = fault_receipt_failures(
        [ev_obs_c2, ev_delivery_c2],
        [("cancel_race", "node_1")],
    )
    assert "MutationDeliveryEvidenceMissing:cancel_race:node_1" in f_node_mismatch


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["missing_null", "nested_null", "existing_null", "canonical_scalar"]
)
async def test_partial_commit_presence_and_canonical_value_evidence(tmp_path, mode):
    paths = ["new_a", "new_b"] if mode != "nested_null" else ["nested.a", "nested.b"]
    value = None
    if mode == "existing_null":
        paths = ["a", "b"]
    elif mode == "canonical_scalar":
        paths, value = ["a", "b"], False
    provider, session, _ = _tool_fault_session(
        tmp_path,
        {"partial_commit_simulated": True},
        changes=[{"path": path, "value": value} for path in paths],
    )
    if mode == "existing_null":
        session.sandbox.state.update(a=None, b=None)
    await session.sandbox.execute("write", {})
    events = provider.get_events("fault-run")
    failures = fault_receipt_failures(events, [("partial_commit", "transfer")])
    assert bool(failures) == (mode == "existing_null")
    if mode != "existing_null":
        receipt = next(e["mutation_receipt"] for e in events if e["event"] == "mutation_delivery")
        observed = receipt["observed"]
        assert observed["applied_paths"] == [paths[0]]
        assert observed["omitted_paths"] == [paths[1]]
        assert observed["after_exists"][paths[0]] is True
        assert observed["after_exists"][paths[1]] == (mode == "canonical_scalar")
        bound = [e["evidence"] for e in events if e["event"] == "runtime_fault_observation"]
        from eval_runner.mutations.mutation_evidence import evidence_hash

        assert valid_extended_observations(receipt, bound, {}, 1, evidence_hash)
        # Alter both the receipt and its observation, bypassing the outer digest check:
        # semantic verification must still reject a missing applied path.
        observed["after_exists"][paths[0]] = False
        next(row for row in bound if row["kind"] == "partial_commit_observed")["observation"][
            "after_exists"
        ][paths[0]] = False
        assert not valid_extended_observations(receipt, bound, {}, 1, evidence_hash)


@pytest.mark.parametrize("kind", ["file", "sqlite"])
def test_stale_fault_expires_existing_pending_request_at_resolution(tmp_path, kind):
    import time

    provider, bus = _recorded_fault_environment(tmp_path)
    approvals = (
        FileApprovalStore(tmp_path / "approvals")
        if kind == "file"
        else SQLiteApprovalStore(tmp_path / "approvals.db")
    )
    plugin, plugins = RuntimeMutationPlugin(), PluginManager()
    plugins.plugins.append(plugin)
    manager = SessionApprovalManager(
        run_id="fault-run",
        approval_store=approvals,
        plugin_manager=plugins,
        event_bus=bus,
        run_store=provider,
    )
    request = manager.create_durable_request(
        turn_index=1,
        action_payload={"amount": 100},
        metadata={"task_id": "transfer", "expires_at": time.time() + 3600},
    )
    plugin.on_step_start(None, "transfer", {"approval_stale": True})
    with pytest.raises(PermissionError, match="observed approval_stale"):
        manager.resolve_durable_request(request.approval_token, "APPROVED")
    expired = approvals.get_request(request.approval_token)
    assert expired.metadata["expires_at"] <= time.time()
    assert expired.outbound_payload_hash == request.outbound_payload_hash
    assert (
        expired.metadata["expiry_change"]["previous_expires_at"] == request.metadata["expires_at"]
    )
    assert (
        fault_receipt_failures(provider.get_events("fault-run"), [("approval_stale", "transfer")])
        == []
    )


def test_valid_extended_observations_rejects_mixed_non_mapping():
    before = {"k": 1, "o": 10}
    proposed = {"k": 2, "o": 20}
    after = {"k": 2, "o": 10}
    obs = {
        "before": before,
        "after": after,
        "proposed": proposed,
        "applied_paths": ["k"],
        "omitted_paths": ["o"],
    }
    receipt = {"fault": "partial_commit", "observed": obs}
    bound = [
        {
            "kind": "commit_proposed",
            "observation": {"before": before, "proposed": proposed, "applicable": True},
        },
        {
            "kind": "partial_commit_observed",
            "observation": obs,
        },
        {"kind": "corrupted_row", "observation": "not_a_mapping"},
    ]
    assert valid_extended_observations(receipt, bound, {}, 1, lambda x: "hash") is False


def test_valid_extended_observations_approval_and_tool_rules():
    # 1. Mutants [23] & [25]: approval_ token checks
    valid_req = {"approval_token": "tok1", "expires_at": 100.0, "payload_hash": "digest"}
    valid_expiry = {
        "approval_token": "tok1",
        "expires_at": 100.0,
        "observed_at": 102.0,
        "payload_hash": "digest",
    }
    valid_att = {"approval_token": "tok1", "attempted_at": 105.0}
    valid_rej = {
        "approval_token": "tok1",
        "code": "ApprovalExpired",
        "blocked": True,
    }
    valid_clean = {"approval_token": "tok1", "status": "REJECTED"}
    receipt_stale = {"fault": "approval_stale", "observed": valid_rej}
    bound_stale = [
        {"kind": "authorization_request", "observation": valid_req},
        {"kind": "authorization_expiry_observed", "observation": valid_expiry},
        {"kind": "authorization_attempt", "observation": valid_att},
        {"kind": "authorization_rejected", "observation": valid_rej},
        {"kind": "authorization_cleanup", "observation": valid_clean},
    ]
    assert valid_extended_observations(receipt_stale, bound_stale, {}, 1, lambda x: "h") is True

    # Mutant [23]: empty token everywhere
    bound_no_token = [
        {"kind": "authorization_request", "observation": {**valid_req, "approval_token": ""}},
        {
            "kind": "authorization_expiry_observed",
            "observation": {**valid_expiry, "approval_token": ""},
        },
        {"kind": "authorization_attempt", "observation": {**valid_att, "approval_token": ""}},
        {"kind": "authorization_rejected", "observation": {**valid_rej, "approval_token": ""}},
        {"kind": "authorization_cleanup", "observation": {**valid_clean, "approval_token": ""}},
    ]
    receipt_no_token = {"fault": "approval_stale", "observed": {**valid_rej, "approval_token": ""}}
    assert (
        valid_extended_observations(receipt_no_token, bound_no_token, {}, 1, lambda x: "h") is False
    )

    # Mutant [25]: one token mismatch
    bound_one_mismatch = [
        {"kind": "authorization_request", "observation": valid_req},
        {"kind": "authorization_expiry_observed", "observation": valid_expiry},
        {
            "kind": "authorization_attempt",
            "observation": {**valid_att, "approval_token": "tok_OTHER"},
        },
        {"kind": "authorization_rejected", "observation": valid_rej},
        {"kind": "authorization_cleanup", "observation": valid_clean},
    ]
    assert (
        valid_extended_observations(receipt_stale, bound_one_mismatch, {}, 1, lambda x: "h")
        is False
    )

    # 2. Mutants [39], [40], [41]: tool_consumer_received guards
    valid_received = {
        "consumer_received": True,
        "payload_hash": "h_mod",
        "expected_hash": "h_mod",
    }
    valid_produced = {"payload_hash": "h_orig"}
    valid_modified = {"original_hash": "h_orig", "modified_hash": "h_mod"}
    receipt_corrupt = {"fault": "tool_response_corruption", "observed": valid_received}
    bound_corrupt = [
        {"kind": "tool_consumer_received", "observation": valid_received},
        {"kind": "tool_response_produced", "observation": valid_produced},
        {"kind": "tool_response_modified", "observation": valid_modified},
    ]
    assert valid_extended_observations(receipt_corrupt, bound_corrupt, {}, 1, lambda x: "h") is True

    # Mutant [39]: consumer_received is False
    rec_not_consumed = {**valid_received, "consumer_received": False}
    bound_not_consumed = [
        {"kind": "tool_consumer_received", "observation": rec_not_consumed},
        {"kind": "tool_response_produced", "observation": valid_produced},
        {"kind": "tool_response_modified", "observation": valid_modified},
    ]
    receipt_not_consumed = {"fault": "tool_response_corruption", "observed": rec_not_consumed}
    assert (
        valid_extended_observations(receipt_not_consumed, bound_not_consumed, {}, 1, lambda x: "h")
        is False
    )

    # Mutant [40]: payload_hash is empty string
    rec_empty_hash = {"consumer_received": True, "payload_hash": "", "expected_hash": ""}
    mod_empty_hash = {"original_hash": "h_orig", "modified_hash": ""}
    bound_empty_hash = [
        {"kind": "tool_consumer_received", "observation": rec_empty_hash},
        {"kind": "tool_response_produced", "observation": valid_produced},
        {"kind": "tool_response_modified", "observation": mod_empty_hash},
    ]
    receipt_empty_hash = {"fault": "tool_response_corruption", "observed": rec_empty_hash}
    assert (
        valid_extended_observations(receipt_empty_hash, bound_empty_hash, {}, 1, lambda x: "h")
        is False
    )

    # Mutant [41]: payload_hash != expected_hash
    rec_diff_hash = {**valid_received, "expected_hash": "h_different"}
    bound_diff_hash = [
        {"kind": "tool_consumer_received", "observation": rec_diff_hash},
        {"kind": "tool_response_produced", "observation": valid_produced},
        {"kind": "tool_response_modified", "observation": valid_modified},
    ]
    receipt_diff_hash = {"fault": "tool_response_corruption", "observed": rec_diff_hash}
    assert (
        valid_extended_observations(receipt_diff_hash, bound_diff_hash, {}, 1, lambda x: "h")
        is False
    )

    # 3. Mutant [53]: malformed_payload wire hash vs rejected hash
    wire_valid = {"raw_payload": "{bad json", "raw_hash": "hash_match"}
    rejected_mismatch_hash = {
        "raw_hash": "hash_different",
        "exception": "JSONDecodeError",
        "position": 1,
    }
    consumer_obs = {
        "consumer_received": True,
        "payload_hash": "h1",
        "expected_hash": "h1",
    }
    bound_malformed = [
        {
            "event_id": "available",
            "kind": "tool_response_available",
            "observation": {"payload_hash": "h1"},
        },
        {"kind": "tool_consumer_received", "observation": consumer_obs},
        {"kind": "tool_wire_received", "observation": wire_valid},
        {"kind": "tool_parse_rejected", "observation": rejected_mismatch_hash},
    ]
    receipt_malformed = {"fault": "malformed_payload", "observed": consumer_obs}
    assert (
        valid_extended_observations(
            receipt_malformed, bound_malformed, {}, 1, lambda x: "hash_match"
        )
        is False
    )

    # 4. Mutant [98]: approval_replay consumption mapping checks
    valid_cons = {
        "approval_token": "tok1",
        "consumption": {
            "run_id": "r1",
            "payload_hash": "digest",
            "authorization_id": "auth1",
        },
    }
    receipt_replay = {
        "fault": "approval_replay",
        "observed": {**valid_rej, "code": "ApprovalReplayBlocked"},
        "run_id": "r1",
    }
    bound_replay = [
        {"kind": "authorization_request", "observation": valid_req},
        {"kind": "authorization_consumed", "observation": valid_cons},
        {"kind": "authorization_attempt", "observation": {**valid_att, "payload_hash": "digest"}},
        {
            "kind": "authorization_rejected",
            "observation": {**valid_rej, "code": "ApprovalReplayBlocked"},
        },
        {"kind": "authorization_cleanup", "observation": valid_clean},
    ]
    assert valid_extended_observations(receipt_replay, bound_replay, {}, 1, lambda x: "h") is True

    # Mutant [98]: non-mapping consumption
    bound_cons_non_mapping = [
        {"kind": "authorization_request", "observation": valid_req},
        {
            "kind": "authorization_consumed",
            "observation": {"approval_token": "tok1", "consumption": "not_a_mapping"},
        },
        {"kind": "authorization_attempt", "observation": {**valid_att, "payload_hash": "digest"}},
        {
            "kind": "authorization_rejected",
            "observation": {**valid_rej, "code": "ApprovalReplayBlocked"},
        },
        {"kind": "authorization_cleanup", "observation": valid_clean},
    ]
    assert (
        valid_extended_observations(receipt_replay, bound_cons_non_mapping, {}, 1, lambda x: "h")
        is False
    )

    # 5. Mutants [144] & [145]: tool_replay source_ref checks
    req_obs = {"request_hash": "req_h"}
    rec_obs = {
        "consumer_received": True,
        "payload_hash": "pay_h",
        "expected_hash": "pay_h",
        "request_hash": "req_h",
    }
    avail_obs = {"payload_hash": "pay_h"}
    replayed_obs = {
        "request_hash": "req_h",
        "payload_hash": "pay_h",
        "tool_dispatched": False,
        "source_ref": {"event_id": "src_evt", "evidence_hash": "ev_h"},
    }
    receipt_tool_replay = {"fault": "tool_replay", "observed": rec_obs, "run_id": "r1"}
    bound_tool_replay = [
        {"event_id": "avail_evt", "kind": "tool_response_available", "observation": avail_obs},
        {"kind": "tool_execution_requested", "observation": req_obs},
        {"event_id": "rep_evt", "kind": "tool_response_replayed", "observation": replayed_obs},
        {"kind": "tool_consumer_received", "observation": rec_obs},
    ]
    source_obs = {"consumer_received": True, "request_hash": "req_h", "payload_hash": "pay_h"}
    index_replay = {
        "avail_evt": ("ev_avail", {}, 1),
        "rep_evt": ("ev_rep", {}, 3),
        "src_evt": (
            "ev_h",
            {"kind": "tool_response_delivered", "run_id": "r1", "observation": source_obs},
            2,
        ),
    }
    # Mutant [145]: valid tool_replay with mapping ref must return True
    assert (
        valid_extended_observations(
            receipt_tool_replay, bound_tool_replay, index_replay, 4, lambda x: "h"
        )
        is True
    )

    # Mutant [144]: non-string event_id in source_ref must be rejected (return False)
    replayed_non_str_event_id = {
        **replayed_obs,
        "source_ref": {"event_id": 9999, "evidence_hash": "ev_h"},
    }
    bound_non_str_event_id = [
        {"event_id": "avail_evt", "kind": "tool_response_available", "observation": avail_obs},
        {"kind": "tool_execution_requested", "observation": req_obs},
        {
            "event_id": "rep_evt",
            "kind": "tool_response_replayed",
            "observation": replayed_non_str_event_id,
        },
        {"kind": "tool_consumer_received", "observation": rec_obs},
    ]
    index_non_str = {
        **index_replay,
        9999: (
            "ev_h",
            {"kind": "tool_response_delivered", "run_id": "r1", "observation": source_obs},
            2,
        ),
    }
    assert (
        valid_extended_observations(
            receipt_tool_replay, bound_non_str_event_id, index_non_str, 4, lambda x: "h"
        )
        is False
    )

    # 6. Mutant [164]: timeout_boundary starts presence check
    req_timeout = {"request_hash": "req_h", "timeout_ms": 500}
    deadline_obs = {
        "timeout_ms": 500,
        "task_cancelled": True,
        "response_withheld": True,
        "elapsed_seconds": 1.0,
    }
    start_obs = {"request_hash": "req_h"}
    receipt_timeout = {"fault": "timeout_boundary", "observed": rec_obs}
    bound_timeout = [
        {"event_id": "avail_evt", "kind": "tool_response_available", "observation": avail_obs},
        {"kind": "tool_execution_requested", "observation": req_timeout},
        {"kind": "tool_invocation_started", "observation": start_obs},
        {"kind": "tool_deadline_expired", "observation": deadline_obs},
        {"kind": "tool_consumer_received", "observation": rec_obs},
    ]
    index_timeout = {"avail_evt": ("ev_avail", {}, 1)}
    # Mutant [164]: timeout_boundary with invocation starts must return True
    assert (
        valid_extended_observations(receipt_timeout, bound_timeout, index_timeout, 4, lambda x: "h")
        is True
    )


def test_intercept_compensation_requires_mandatory_rollback_interceptor():
    from unittest.mock import ANY

    from eval_runner.mutations.compensation_faults import intercept_compensation

    scenario = {"id": "s1", "failure_policy": {"rollback_failure": True}}
    node = {"id": "comp_node"}
    plugins = MagicMock()
    plugins.trigger_interceptor.return_value = {}
    with pytest.raises(RuntimeError, match="Selected rollback fault did not reach"):
        intercept_compensation("run-comp", MagicMock(), plugins, scenario, node, "exec-1", "p-1")
    plugins.trigger_interceptor.assert_any_call("on_step_end", ANY, "comp_node")


def test_runtime_mutation_plugin_edge_guards_and_error_paths():
    from types import SimpleNamespace

    from eval_runner.mutations.mutator_plugin import RuntimeMutationPlugin
    from eval_runner.mutations.runtime_faults import FaultDeliveryError

    plugin = RuntimeMutationPlugin()
    plugin.before_evaluation(object())
    plugin.on_step_start(None, None)
    plugin.on_step_end(None, None)
    assert plugin.active_node_id is None
    ctx = SimpleNamespace(scenario_data={"id": "scen-data"}, current_execution_instance_id="e1")
    plugin.on_step_start(ctx, "n1", {"cancel_at_boundary": True})
    assert plugin.scenario == {"id": "scen-data"}
    with pytest.raises(FaultDeliveryError, match="bound runtime controller"):
        plugin.on_tool_request(ctx, "write", {})

    plugin.on_step_start(ctx, "n2", {"partial_commit_simulated": True})
    with pytest.raises(FaultDeliveryError, match="actual sandbox boundary"):
        plugin.on_before_commit(ctx, {"k": 1})

    sandbox = SimpleNamespace(tool_faults=MagicMock())
    plugin.on_step_start(
        SimpleNamespace(scenario={"id": "s"}, sandbox=sandbox, current_execution_instance_id="e2"),
        "n3",
        {"tool_response_corrupted": True},
    )
    res = plugin.on_tool_result(ctx, tool="t1", result="raw-string")
    assert res["result"]["original_type"] == "str"

    plugin.on_step_start(ctx, "n4", {"approval_stale": True, "approval_mismatch": True})
    with pytest.raises(ValueError, match="one independently observable fault"):
        plugin._intercept_approval(ctx, {})
