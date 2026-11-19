"""Independent boundary regressions identified by the Linux sampled CI run."""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agentv_runtime.interfaces import ApprovalRequest
from eval_runner.approval_validation import ApprovalValidationError
from eval_runner.mutations.approval_faults import deliver_authorization_fault
from eval_runner.mutations.mutation_evidence import evidence_hash
from eval_runner.mutations.mutation_rules import valid_extended_observations
from eval_runner.mutations.runtime_faults import FaultDeliveryError
from eval_runner.mutations.tool_contracts import FORBIDDEN_PROPERTY
from eval_runner.mutations.tool_faults import ToolFaultExecutor
from eval_runner.session_components.state_parity import SessionStateParityVerifier


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["node_id", "execution_instance_id", "tool"])
async def test_prepared_tool_ticket_requires_each_ownership_binding(mismatch):
    plan = {
        "tool_contract_violation": True,
        "node_id": "review",
        "execution_instance_id": "review:1",
    }
    controller = SimpleNamespace(_observe=Mock(return_value={}))
    sandbox = SimpleNamespace(
        plugin_manager=SimpleNamespace(trigger_interceptor=Mock(return_value={"fault_plan": plan})),
        fault_controller=controller,
        scenario={
            "tools": {"write": {"input_schema": {"type": "object", "additionalProperties": False}}}
        },
    )
    executor = ToolFaultExecutor(sandbox)
    arguments = {FORBIDDEN_PROPERTY: True}
    prepared = {
        "identity": {"node_id": "review", "execution_instance_id": "review:1"},
        "refs": [],
        "observed": {
            "tool": "write",
            "modified_hash": evidence_hash(arguments),
            "original_arguments": {},
        },
    }
    if mismatch == "tool":
        prepared["observed"]["tool"] = "different-tool"
    else:
        prepared["identity"][mismatch] = "different-owner"
    executor.argument_context.set(prepared)
    operation = AsyncMock(return_value={"ok": True})
    with pytest.raises(RuntimeError, match="Tool argument mutation does not own this invocation"):
        await executor.execute(
            {"tool_name": "write", "params": arguments, "agent_name": "agent"}, operation
        )
    operation.assert_not_awaited()


@pytest.mark.parametrize("reread", ["missing", "different_run"])
def test_expired_approval_must_be_durably_observed_under_the_same_run(reread):
    request = ApprovalRequest(
        approval_token="approval",
        run_id="run",
        status="APPROVED",
        outbound_payload_hash="digest",
        metadata={"expires_at": time.time() + 600},
    )
    changed = (
        None
        if reread == "missing"
        else ApprovalRequest(
            approval_token="approval",
            run_id="another-run",
            status="APPROVED",
            outbound_payload_hash="digest",
            metadata={"expires_at": 0},
        )
    )
    store = SimpleNamespace(
        get_request=Mock(side_effect=[request, changed]),
        consume_request=Mock(),
        revoke_request=Mock(),
        expire_request=Mock(),
    )
    controller = SimpleNamespace(run_id="run", _identity=Mock(return_value={}), _observe=Mock())
    with pytest.raises(FaultDeliveryError, match="Expired authorization was not durably observed"):
        deliver_authorization_fault(
            controller, "approval_stale", store, request, None, "review", "review:1"
        )
    store.expire_request.assert_called_once()
    store.consume_request.assert_not_called()
    store.revoke_request.assert_not_called()
    assert (
        controller._observe.call_count == 1
    )  # Request observation only, no delivered-fault claim.


@pytest.mark.parametrize("authorization_id", [42, True, ["id"], {"id": "value"}, ""])
def test_replay_requires_a_nonempty_string_authorization_identity(authorization_id):
    request = ApprovalRequest(
        approval_token="approval",
        run_id="run",
        status="APPROVED",
        outbound_payload_hash="digest",
        metadata={
            "consumption": {
                "run_id": "run",
                "payload_hash": "digest",
                "authorization_id": authorization_id,
            }
        },
    )
    store = SimpleNamespace(
        get_request=Mock(return_value=request),
        consume_request=Mock(side_effect=ApprovalValidationError("ApprovalReplayBlocked")),
        revoke_request=Mock(return_value=SimpleNamespace(status="REJECTED")),
    )
    controller = SimpleNamespace(
        run_id="run", _identity=Mock(return_value={}), _observe=Mock(), _receipt=Mock()
    )
    with pytest.raises(FaultDeliveryError, match="A bound prior consumption was not observed"):
        deliver_authorization_fault(
            controller, "approval_replay", store, request, None, "review", "review:1"
        )
    store.consume_request.assert_not_called()
    controller._receipt.assert_not_called()


@pytest.mark.parametrize("binding", ["run_id", "payload_hash"])
def test_replay_consumption_requires_each_independent_binding(binding):
    marker = {"run_id": "run", "payload_hash": "digest", "authorization_id": "spent-id"}
    marker[binding] = "unrelated"
    request = ApprovalRequest(
        approval_token="approval",
        run_id="run",
        status="APPROVED",
        outbound_payload_hash="digest",
        metadata={"consumption": marker},
    )
    store = SimpleNamespace(
        get_request=Mock(return_value=request),
        consume_request=Mock(),
        revoke_request=Mock(),
    )
    controller = SimpleNamespace(
        run_id="run", _identity=Mock(return_value={}), _observe=Mock(), _receipt=Mock()
    )
    with pytest.raises(FaultDeliveryError, match="A bound prior consumption was not observed"):
        deliver_authorization_fault(
            controller, "approval_replay", store, request, None, "review", "review:1"
        )
    store.consume_request.assert_not_called()
    store.revoke_request.assert_not_called()
    controller._receipt.assert_not_called()
    assert [call.args[0] for call in controller._observe.call_args_list] == [
        "authorization_request"
    ]


@pytest.mark.parametrize("defect", ["extra_before_key", "integer_exists"])
def test_partial_commit_requires_exact_keys_and_strict_boolean_existence(defect):
    before, after, proposed = {"a": 0, "b": 0}, {"a": 1, "b": 0}, {"a": 1, "b": 2}
    before_exists, after_exists = {"a": True, "b": True}, {"a": True, "b": True}
    commit = {
        "before": before,
        "after": after,
        "proposed": proposed,
        "before_exists": before_exists,
        "after_exists": after_exists,
        "applied_paths": ["a"],
        "omitted_paths": ["b"],
    }
    receipt = {"fault": "partial_commit", "observed": commit}
    bound = [
        {
            "kind": "commit_proposed",
            "observation": {
                "before": before,
                "before_exists": before_exists,
                "proposed": proposed,
                "applicable": True,
            },
        },
        {"kind": "partial_commit_observed", "observation": commit},
    ]
    assert valid_extended_observations(receipt, bound, {}, 0, evidence_hash) is True
    if defect == "extra_before_key":
        before_exists["not-proposed"] = True
    else:
        before_exists["b"] = 1  # Equality with True must not hide invalid existence metadata.
    assert valid_extended_observations(receipt, bound, {}, 0, evidence_hash) is False


@pytest.mark.asyncio
async def test_mixed_authority_projections_capture_the_complete_required_prestate():
    verifier = SessionStateParityVerifier(SimpleNamespace(scenario={}))
    node = {
        "id": "review",
        "expected_outcome": [
            {"target": "authority:orders", "projection": ["status"]},
            {"target": "authority:orders"},
        ],
    }
    state = {"status": "pending", "approval": {"reviewed": False}}
    with patch.object(
        verifier, "_resolve_target", new_callable=AsyncMock, return_value=(state, None)
    ) as resolve:
        captured = await verifier.capture_external_prestate(node, None, [])
    assert resolve.await_args.args[0]["projection"] is None
    assert captured["authority:orders"]["state"] == state


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", [None, 42, "identity", []])
@pytest.mark.parametrize("invalid_phase", ["probe", "capture"])
async def test_invalid_authority_identity_is_typed_unobservable_evidence(identity, invalid_phase):
    from eval_runner.state_authority import state_authority_registry

    connector = SimpleNamespace(
        observation_identity=Mock(
            side_effect=[identity] if invalid_phase == "probe" else [{}, identity]
        ),
        fetch_state=AsyncMock(return_value={"status": "pending"}),
    )
    verifier = SessionStateParityVerifier(SimpleNamespace(scenario={}))
    with patch.object(state_authority_registry, "get_connector", return_value=connector):
        captured = await verifier.capture_external_prestate(
            {"id": "review", "expected_outcome": [{"target": "authority:orders"}]}, None, []
        )
    assert captured["authority:orders"]["invalid"] is True
    assert captured["authority:orders"]["error_type"] == "TypeError"
    if invalid_phase == "probe":
        connector.fetch_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_authority_identity_is_closed_and_rejected_before_fetch():
    from eval_runner.state_authority import state_authority_registry

    async def identity():
        return {}

    coroutine = identity()
    connector = SimpleNamespace(
        observation_identity=Mock(return_value=coroutine), fetch_state=AsyncMock()
    )
    verifier = SessionStateParityVerifier(SimpleNamespace(scenario={}))
    with patch.object(state_authority_registry, "get_connector", return_value=connector):
        captured = await verifier.capture_external_prestate(
            {"id": "review", "expected_outcome": [{"target": "authority:orders"}]}, None, []
        )
    assert captured["authority:orders"]["invalid"] is True
    assert coroutine.cr_frame is None
    connector.fetch_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_message_observation_ignores_later_user_and_system_entries():
    verifier = SessionStateParityVerifier(SimpleNamespace())
    state, _ = await verifier._resolve_target(
        {"target": "message"},
        None,
        [
            {"role": "agent", "content": "agent result"},
            {"role": "user", "content": "user prompt"},
            {"role": "system", "content": "system instruction"},
        ],
        {},
    )
    assert state == "agent result"


@pytest.mark.asyncio
async def test_state_acquisition_requires_a_coroutine_getter():
    getter = Mock(return_value={"status": "pending"})
    verifier = SessionStateParityVerifier(SimpleNamespace())
    observed, path = await verifier._resolve_target(
        {"target": "state", "projection": ["status"]},
        SimpleNamespace(get_bounded_state=getter),
        [],
        {},
    )
    assert observed is None and path == "__unobserved_source__"
    getter.assert_not_called()


@pytest.mark.asyncio
async def test_state_acquisition_rejects_missing_projection_before_dispatch():
    getter = AsyncMock(return_value={"status": "pending"})
    verifier = SessionStateParityVerifier(SimpleNamespace())
    observed, path = await verifier._resolve_target(
        {"target": "state"}, SimpleNamespace(get_bounded_state=getter), [], {}
    )
    assert observed is None and path == "__unobserved_source__"
    getter.assert_not_awaited()


@pytest.mark.asyncio
async def test_bounded_state_acquisition_preserves_valid_dictionary_result():
    getter = AsyncMock(return_value={"status": "pending", "unrelated": "private"})
    verifier = SessionStateParityVerifier(SimpleNamespace())
    observed, path = await verifier._resolve_target(
        {"target": "state", "projection": ["status"]},
        SimpleNamespace(get_bounded_state=getter),
        [],
        {},
    )
    assert observed == {"status": "pending"}
    assert path != "__unobserved_source__"
    getter.assert_awaited_once_with(["status"])


@pytest.mark.asyncio
@pytest.mark.parametrize("include_message", [False, True])
async def test_prestate_observes_each_authority_once_and_skips_non_authorities(include_message):
    verifier = SessionStateParityVerifier(SimpleNamespace(scenario={}))
    assertions = [
        {"target": "authority:orders", "projection": ["status"]},
        {"target": "authority:orders", "projection": ["approval"]},
    ]
    if include_message:
        assertions.insert(0, {"target": "message", "expected": "submitted"})
    node = {"id": "review", "expected_outcome": assertions}
    state = {"status": "pending", "approval": {"reviewed": False}}
    with patch.object(
        verifier, "_resolve_target", new_callable=AsyncMock, return_value=(state, None)
    ) as resolve:
        captured = await verifier.capture_external_prestate(node, None, [])
    resolve.assert_awaited_once()
    assert resolve.await_args.args[0]["target"] == "authority:orders"
    assert resolve.await_args.args[0]["projection"] == ["approval", "status"]
    assert set(captured) == {"authority:orders"}
    assert captured["authority:orders"]["state"] == state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evidence_target", [None, "", 42, True, [], ["state"], {}, {"target": "state"}, "state"]
)
async def test_policy_evidence_target_is_a_nonempty_string_before_dispatch(evidence_target):
    policy = {
        "required": True,
        "oracle_id": "policy:review",
        "evidence_target": evidence_target,
        "projection": ["status"],
    }
    verifier = SessionStateParityVerifier(
        SimpleNamespace(
            scenario={"metadata": {"policies": {"review": policy}}},
        )
    )
    getter = AsyncMock(return_value={"status": "pending"})
    evaluator = SimpleNamespace(evaluate_policy=Mock(return_value=SimpleNamespace(allowed=True)))
    with (
        patch("eval_runner.runtime_services.resolve_policy_evaluator", return_value=evaluator),
        patch.object(
            verifier,
            "_resolve_target",
            wraps=verifier._resolve_target,
        ) as resolve,
    ):
        observed, path = await resolve(
            {"target": "policy:review", "oracle_id": "policy:review"},
            SimpleNamespace(get_bounded_state=getter),
            [],
            {},
        )
    if evidence_target == "state":
        assert observed is True
        getter.assert_awaited_once_with(["status"])
        evaluator.evaluate_policy.assert_called_once_with(policy, {"status": "pending"})
        assert resolve.await_count == 2
    else:
        assert observed is None and path == "__unobserved_source__"
        assert resolve.await_count == 1
        getter.assert_not_awaited()
        evaluator.evaluate_policy.assert_not_called()


@pytest.mark.asyncio
async def test_explicit_agent_message_does_not_invoke_summary_fallback():
    summary = Mock(return_value="unrelated fallback")
    verifier = SessionStateParityVerifier(SimpleNamespace(_extract_agent_summary=summary))
    observed, _ = await verifier._resolve_target(
        {"target": "message"},
        None,
        [{"role": "agent", "content": "agent result"}],
        {},
    )
    assert observed == "agent result"
    summary.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", [None, "response_digest", "phase"])
async def test_prestate_receipt_requires_digest_and_phase_independently(defect):
    from eval_runner.state_authority import bound_state_snapshot

    state = {"status": "pending"}
    _, digest = bound_state_snapshot(state)
    receipt = {"response_digest": digest, "phase": "pre"}
    if defect:
        receipt[defect] = "unrelated"
    verifier = SessionStateParityVerifier(SimpleNamespace(scenario={}))
    verifier._observation_identities.set({"authority:orders": {"connector_receipt": receipt}})
    with patch.object(
        verifier, "_resolve_target", new_callable=AsyncMock, return_value=(state, None)
    ):
        captured = await verifier.capture_external_prestate(
            {"id": "review", "expected_outcome": [{"target": "authority:orders"}]},
            None,
            [],
        )
    observation = captured["authority:orders"]
    if defect:
        assert observation["invalid"] is True
        assert observation["error_type"] == "ObservationReceiptMismatch"
    else:
        assert observation["state"] == state
        assert observation["snapshot_hash"] == digest
