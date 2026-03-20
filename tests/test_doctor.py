import pytest
import os
from unittest.mock import patch, AsyncMock
from eval_runner.doctor import check_agent_reachable, run_doctor


@pytest.mark.asyncio
async def test_check_agent_reachable_success():
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value.__aenter__.return_value.status = 200
        result = await check_agent_reachable("http://localhost:5001")
        assert result is True


@pytest.mark.asyncio
async def test_check_agent_reachable_failure():
    with patch("aiohttp.ClientSession.post", side_effect=Exception("Unreachable")):
        result = await check_agent_reachable("http://localhost:5001")
        assert result is False


@pytest.mark.asyncio
async def test_run_doctor_smoke():
    # Smoke test to ensure it runs without crashing
    with patch("builtins.print") as mock_print:
        with patch("eval_runner.doctor.check_agent_reachable", return_value=True):
            await run_doctor()
            assert mock_print.called
