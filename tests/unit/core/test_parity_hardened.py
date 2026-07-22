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
    # Setup slow mocks to prove parallelization
    mock_db = AsyncMock()

    async def slow_db():
        await asyncio.sleep(0.5)
        return {"active": True}

    mock_db.get_snapshot.side_effect = slow_db

    mock_git = AsyncMock()

    async def slow_git():
        await asyncio.sleep(0.5)
        return {"branch": "main"}

    mock_git.get_snapshot.side_effect = slow_git

    simulators = {"db": mock_db, "git": mock_git}
    mock_sandbox = MagicMock()
    mock_sandbox.get_active_simulators.return_value = simulators

    session = SessionManager("test_run", scenario)

    import time

    start = time.time()
    # Execute the parity check logic
    success = await session._verify_state_parity(scenario, mock_sandbox, [])
    end = time.time()

    assert success is True
    # Sequential would take >= 1.0s (2 x 0.5s). Parallel takes ~0.5s.
    # Threshold of 0.75s gives generous headroom for CI/coverage overhead
    # while still clearly distinguishing sequential from concurrent execution.
    assert (end - start) < 0.75, f"Execution was too slow ({end - start:.2f}s), likely sequential."
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
