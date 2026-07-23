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
    success = await session._verify_state_parity(scenario, mock_sandbox, [])

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
        success = await session._verify_state_parity(scenario, mock_sandbox, [])

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

    success = await session._verify_state_parity(scenario, mock_sandbox, [])
    assert success is False  # Missing shim should cause failure if target is shim:db
