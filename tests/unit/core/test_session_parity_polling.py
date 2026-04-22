from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.session import SessionManager


@pytest.mark.asyncio
async def test_session_parity_polling_success():
    """Verify that _verify_state_parity polls until success."""
    scenario = {"id": "test", "workflow": {"nodes": []}}
    session = SessionManager("run", scenario)

    node = {
        "expected_outcome": [{"target": "shim:db", "property": "count", "expected": 1}],
        "timeout": 5,
    }

    sandbox = MagicMock()
    # Mock _get_shim_snapshots to fail first then succeed
    session._get_shim_snapshots = AsyncMock()
    session._get_shim_snapshots.side_effect = [
        {"db": {"count": 0}},  # Turn 1 failure
        {"db": {"count": 1}},  # Turn 2 success
    ]

    # We also need to patch asyncio.sleep to speed up test
    with patch("asyncio.sleep", new_callable=AsyncMock):
        success = await session._verify_state_parity(node, sandbox, [])
        assert success is True
        assert session._get_shim_snapshots.call_count == 2


@pytest.mark.asyncio
async def test_session_parity_polling_timeout():
    """Verify that _verify_state_parity fails after timeout."""
    scenario = {"id": "test", "workflow": {"nodes": []}}
    session = SessionManager("run", scenario)

    node = {
        "expected_outcome": [{"target": "shim:db", "property": "count", "expected": 1}],
        "timeout": 1,
    }

    sandbox = MagicMock()
    session._get_shim_snapshots = AsyncMock(return_value={"db": {"count": 0}})

    # Patch time to simulate timeout
    with patch("asyncio.get_event_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_loop.time.side_effect = [0, 0, 2]  # start, check 1, check 2 (timeout)
        mock_get_loop.return_value = mock_loop

        with patch("asyncio.sleep", new_callable=AsyncMock):
            success = await session._verify_state_parity(node, sandbox, [])
            assert success is False


@pytest.mark.asyncio
async def test_session_parity_unsupported_target():
    """Verify that _verify_state_parity fails immediately on unsupported target."""
    scenario = {"id": "test", "workflow": {"nodes": []}}
    session = SessionManager("run", scenario)

    node = {"expected_outcome": [{"target": "unknown_target", "expected": 1}]}

    sandbox = MagicMock()
    session._get_shim_snapshots = AsyncMock(return_value={})

    success = await session._verify_state_parity(node, sandbox, [])
    assert success is False
