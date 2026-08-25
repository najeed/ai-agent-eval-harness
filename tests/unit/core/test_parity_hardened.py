"""
test_parity_hardened.py

Verifies parallelization and forensic tagging in the state parity verification engine.
"""

import asyncio
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
