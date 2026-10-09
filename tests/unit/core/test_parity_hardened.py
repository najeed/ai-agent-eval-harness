"""
test_parity_hardened.py

Verifies parallelization and forensic tagging in the state parity verification engine.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.events import CoreEvents
from eval_runner.session import SessionManager


@pytest.fixture
def scenario():
    return {
        "id": "parity-test",
        "workflow": {"nodes": []},
        "expected_outcome": [
            {"target": "shim:db", "property": "active", "expected": True},
            {"target": "shim:git", "property": "branch", "expected": "main"},
        ],
        "timeout": 0.1,
    }


@pytest.mark.asyncio
async def test_verify_state_parity_parallel(scenario):
    active_count = 0
    max_active_count = 0

    async def slow_db():
        nonlocal active_count, max_active_count
        active_count += 1
        max_active_count = max(max_active_count, active_count)
        await asyncio.sleep(0.1)
        active_count -= 1
        return {"active": True}

    mock_db = AsyncMock()
    mock_db.get_snapshot.side_effect = slow_db

    async def slow_git():
        nonlocal active_count, max_active_count
        active_count += 1
        max_active_count = max(max_active_count, active_count)
        await asyncio.sleep(0.1)
        active_count -= 1
        return {"branch": "main"}

    mock_git = AsyncMock()
    mock_git.get_snapshot.side_effect = slow_git

    simulators = {"db": mock_db, "git": mock_git}
    mock_sandbox = MagicMock()
    mock_sandbox.get_active_simulators.return_value = simulators

    session = SessionManager("test_run", scenario)

    # Execute the parity check logic
    success, _evidence = await session._verify_state_parity(scenario, mock_sandbox, [])

    assert success is True
    # Logical proof of concurrency: both tasks must be active on the event loop simultaneously
    assert max_active_count == 2, "Execution was not concurrent/parallelized."
    assert mock_db.get_snapshot.call_count == 1
    assert mock_git.get_snapshot.call_count == 1


@pytest.mark.asyncio
async def test_verify_state_parity_forensics(scenario):
    # Setup failure to check forensic tagging
    mock_db = AsyncMock()
    mock_db.get_snapshot.return_value = {"active": False}  # Mismatch

    simulators = {
        "db": mock_db,
        "git": AsyncMock(get_snapshot=AsyncMock(return_value={"branch": "main"})),
    }
    mock_sandbox = MagicMock()
    mock_sandbox.get_active_simulators.return_value = simulators

    session = SessionManager("test_run", scenario)

    with patch.object(session.event_bus, "emit") as mock_emit:
        success, _evidence = await session._verify_state_parity(scenario, mock_sandbox, [])

        assert success is False
        # Check if ADAPTER_DEBUG with root_cause was emitted
        debug_emits = [
            args[0][1]
            for args in mock_emit.call_args_list
            if args[0][0] == CoreEvents.ADAPTER_DEBUG
        ]

        failure_event = next((e for e in debug_emits if e.get("is_root_cause")), None)
        assert failure_event is not None
        assert failure_event["category"] == "PARITY_STATE_DIVERGENCE"
        assert "Parity FAILED" in failure_event["message"]
        assert "shim:db.active" in failure_event["message"]


@pytest.mark.asyncio
async def test_verify_state_parity_missing_shim(scenario):
    # Only git exists, db missing
    simulators = {"git": AsyncMock(get_snapshot=AsyncMock(return_value={"branch": "main"}))}
    mock_sandbox = MagicMock()
    mock_sandbox.get_active_simulators.return_value = simulators

    session = SessionManager("test_run", scenario)

    success, _evidence = await session._verify_state_parity(scenario, mock_sandbox, [])
    assert success is False  # Missing shim should cause failure if target is shim:db


@pytest.mark.asyncio
async def test_parity_divergence_emits_strict_state_comparison(scenario):
    """[P0-12] The divergence event carries the strict StateComparison payload.

    Contract: expected / actual / comparison / assertions / source / timestamp.
    No field may be absent — debugger rendering must never fall back to
    message-text guessing when this payload exists (and must NOT synthesize a
    diff when it does not).
    """
    mock_db = AsyncMock()
    mock_db.get_snapshot.return_value = {"active": False}

    simulators = {
        "db": mock_db,
        "git": AsyncMock(get_snapshot=AsyncMock(return_value={"branch": "main"})),
    }
    mock_sandbox = MagicMock()
    mock_sandbox.get_active_simulators.return_value = simulators

    session = SessionManager("test_run", scenario)

    with patch.object(session.event_bus, "emit") as mock_emit:
        success, evidence = await session._verify_state_parity(scenario, mock_sandbox, [])

        assert success is False
        assert evidence, "transition evidence rows must accompany a divergence"

        debug_emits = [
            args[0][1]
            for args in mock_emit.call_args_list
            if args[0][0] == CoreEvents.ADAPTER_DEBUG
        ]
        failure_event = next(
            (e for e in debug_emits if e.get("category") == "PARITY_STATE_DIVERGENCE"),
            None,
        )
        assert failure_event is not None

        sc = failure_event["state_comparison"]
        assert set(sc.keys()) >= {
            "expected",
            "actual",
            "comparison",
            "assertions",
            "source",
            "timestamp",
        }
        assert sc["source"] == "state_parity.transition_verification"
        assert isinstance(sc["timestamp"], str) and sc["timestamp"]
        assert len(sc["assertions"]) == len(evidence)
        # Expected/actual vectors are aligned per-assertion with the evidence rows.
        assert len(sc["expected"]) == len(evidence)
        assert len(sc["actual"]) == len(evidence)
        assert sc["comparison"]["kind"] == "transition_verification"
        assert "shim:db.active" in sc["comparison"]["failed_assertion"]


@pytest.mark.asyncio
async def test_state_parity_verifier_external_evidence_target_and_prestate():
    from eval_runner.session_components.state_parity import SessionStateParityVerifier

    # Setup mock session manager with scenario metadata policies
    mock_sm = MagicMock()
    mock_sm.scenario = {
        "metadata": {
            "policies": {
                "pol_valid": {"evidence_target": "external_state"},
                "pol_empty": {"evidence_target": ""},
                "pol_no_target": {},
            }
        }
    }
    verifier = SessionStateParityVerifier(mock_sm)

    # 1. _external_evidence_target branches
    assert verifier._external_evidence_target({"target": "policy:pol_valid"}) == "external_state"
    assert verifier._external_evidence_target({"target": "policy:pol_empty"}) is None
    assert verifier._external_evidence_target({"target": "policy:pol_no_target"}) is None
    assert verifier._external_evidence_target({"target": "policy:pol_missing"}) is None
    assert verifier._external_evidence_target({"target": "unsupported_prefix"}) is None

    # 2. capture_external_prestate with unobserved/unsupported target and non-dict assertion
    node = {
        "expected_outcome": [
            "not_a_dict_assertion",
            {"target": "state_authority", "property": "unknown_prop"},
        ]
    }
    mock_sandbox = MagicMock()
    # Force _resolve_target to return __unobserved_source__ for state_authority
    with patch.object(
        verifier, "_resolve_target", AsyncMock(return_value=(None, "__unobserved_source__"))
    ):
        prestate = await verifier.capture_external_prestate(node, mock_sandbox, [])
        assert "state_authority" in prestate
        assert prestate["state_authority"] == {"invalid": True}


@pytest.mark.asyncio
async def test_state_parity_verifier_shim_snapshots_edge_cases():
    from eval_runner.session_components.state_parity import SessionStateParityVerifier

    verifier = SessionStateParityVerifier(MagicMock())

    # 1. Sandbox does not declare get_active_simulators
    sandbox_no_get = object()
    res1 = await verifier.get_shim_snapshots(sandbox_no_get, ["db"])
    assert res1 == {}

    # 2. get_active_simulators is an awaitable returning a dict
    async def async_simulators():
        return {
            "s_coro": SimpleNamespace(
                get_snapshot=lambda: asyncio.sleep(0.001, result={"active": True})
            ),
            "s_sync_snap": SimpleNamespace(get_snapshot=lambda: {"snap": 1}),
            "s_coro_state": SimpleNamespace(
                get_state=lambda: asyncio.sleep(0.001, result={"state_coro": True})
            ),
            "s_sync_state": SimpleNamespace(get_state=lambda: {"sync": 2}),
            "s_prop": SimpleNamespace(state={"prop": 3}),
            "s_empty": SimpleNamespace(),
        }

    mock_sandbox_async = MagicMock()
    mock_sandbox_async.get_active_simulators = async_simulators

    res2 = await verifier.get_shim_snapshots(
        mock_sandbox_async,
        ["s_coro", "s_sync_snap", "s_coro_state", "s_sync_state", "s_prop", "s_empty", "s_missing"],
    )
    assert res2["s_coro"] == {"active": True}
    assert res2["s_sync_snap"] == {"snap": 1}
    assert res2["s_coro_state"] == {"state_coro": True}
    assert res2["s_sync_state"] == {"sync": 2}
    assert res2["s_prop"] == {"prop": 3}
    assert "s_empty" not in res2
    assert "s_missing" not in res2

    # 3. get_active_simulators returns non-dict
    mock_sandbox_bad = MagicMock()
    mock_sandbox_bad.get_active_simulators = lambda: "not_a_dict"
    res3 = await verifier.get_shim_snapshots(mock_sandbox_bad, ["db"])
    assert res3 == {}


@pytest.mark.asyncio
async def test_state_parity_verifier_policy_spec_resolution_branches():
    from eval_runner.session_components.state_parity import SessionStateParityVerifier

    mock_sm = MagicMock()
    mock_sm.scenario = {
        "metadata": {
            "policies": {
                "pol_mismatched_oracle": {
                    "required": True,
                    "oracle_id": "expected_oracle_1",
                    "evidence_target": "shim:db",
                },
                "pol_no_evidence": {
                    "required": False,
                    "evidence_target": None,
                },
                "pol_unobservable_source": {
                    "required": False,
                    "evidence_target": "shim:missing_source",
                },
                "pol_violations_and_reason": {
                    "required": False,
                    "evidence_target": "shim:valid_source",
                    "condition": {"type": "field_check", "field": "x", "expected": 1},
                },
            }
        }
    }
    verifier = SessionStateParityVerifier(mock_sm)
    sandbox = MagicMock()
    history = []
    shim_snapshots = {"valid_source": {"x": 2}}

    # 1. Required policy with mismatched oracle ID
    val1, path1 = await verifier._resolve_target(
        {"target": "policy:pol_mismatched_oracle", "oracle_id": "wrong_oracle"},
        sandbox,
        history,
        shim_snapshots,
    )
    assert val1 is None
    assert path1 == "__unobserved_source__"

    # 2. Policy without explicit evidence_target
    val2, path2 = await verifier._resolve_target(
        {"target": "policy:pol_no_evidence"},
        sandbox,
        history,
        shim_snapshots,
    )
    assert val2 is None
    assert path2 == "__unobserved_source__"

    # 3. Policy evidence target unobservable
    val3, path3 = await verifier._resolve_target(
        {"target": "policy:pol_unobservable_source"},
        sandbox,
        history,
        shim_snapshots,
    )
    assert val3 is None
    assert path3 == "__unobserved_source__"

    # 4. Property path is 'violations'
    val_viol, path_viol = await verifier._resolve_target(
        {"target": "policy:pol_violations_and_reason", "property": "violations"},
        sandbox,
        history,
        shim_snapshots,
    )
    assert path_viol is None
    assert isinstance(val_viol, list)

    # 5. Property path is 'reason'
    val_reason, path_reason = await verifier._resolve_target(
        {"target": "policy:pol_violations_and_reason", "property": "reason"},
        sandbox,
        history,
        shim_snapshots,
    )
    assert path_reason is None
    assert isinstance(val_reason, str)


@pytest.mark.asyncio
async def test_state_parity_verifier_message_and_state_projection_branches():
    from eval_runner.session_components.state_parity import SessionStateParityVerifier

    verifier = SessionStateParityVerifier(object())
    sandbox = MagicMock()

    # 1. target == 'message' with non-string, non-dict content
    history = [
        {"role": "agent", "content": 12345},
    ]
    val_msg, path_msg = await verifier._resolve_target(
        {"target": "message"},
        sandbox,
        history,
        {},
    )
    assert val_msg == ""

    # 2. target == 'state' unprojected assertion rejected by a bounded-capable sandbox
    async def get_bounded_state(projection):
        return {"k": 1}

    bounded_sandbox = SimpleNamespace(get_bounded_state=get_bounded_state)
    val_state, path_state = await verifier._resolve_target(
        {"target": "state"},
        bounded_sandbox,
        history,
        {},
    )
    assert val_state is None
    assert path_state == "__unobserved_source__"


@pytest.mark.asyncio
async def test_state_parity_verifier_timeout_without_event_bus():
    from eval_runner.session_components.state_parity import SessionStateParityVerifier

    # SessionManager without event_bus handles timeout safely
    mock_sm = object()
    verifier = SessionStateParityVerifier(mock_sm)

    node = {
        "id": "node_to_timeout",
        "expected_outcome": [
            {"target": "shim:db.flag", "expected": True},
        ],
        "timeout": 0.001,
        "poll_interval": 0.001,
    }
    sandbox = MagicMock()
    sandbox.get_active_simulators.return_value = {
        "db": MagicMock(get_snapshot=lambda: {"flag": False})
    }

    success, evidence = await verifier.verify_state_parity(node, sandbox, [])
    assert success is False
    assert len(evidence) > 0
