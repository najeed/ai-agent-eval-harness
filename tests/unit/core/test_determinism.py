from unittest.mock import AsyncMock, patch

import pytest

from eval_runner.runner import DefaultRunner


@pytest.mark.asyncio
async def test_incremental_seeding_protocol():
    """
    Verify the Industrial Seeding Protocol: Final Seed = Base Seed + (Attempt - 1)
    """
    base_seed = 100
    attempts = 3
    scenario = {"id": "test_scenario", "tasks": [{"id": "t1"}]}

    runner = DefaultRunner()

    # Patch the actual SessionManager in its source module
    with patch("eval_runner.session.SessionManager") as MockSession:
        # Use AsyncMock for execute_tasks since it is awaited
        mock_session_instance = MockSession.return_value
        mock_session_instance.execute_tasks = AsyncMock(
            return_value=[{"status": "success", "metrics": []}]
        )
        mock_session_instance.metadata = {}

        # Call runner.run with scenario and seed
        await runner.run(scenario, attempts=attempts, seed=base_seed)

        # Verify SessionManager was called with incremented seeds
        assert MockSession.call_count == attempts

        # Check call arguments for each attempt
        # Attempt 1: Seed 100
        args, kwargs = MockSession.call_args_list[0]
        assert kwargs["seed"] == 100

        # Attempt 2: Seed 101
        args, kwargs = MockSession.call_args_list[1]
        assert kwargs["seed"] == 101

        # Attempt 3: Seed 102
        args, kwargs = MockSession.call_args_list[2]
        assert kwargs["seed"] == 102
