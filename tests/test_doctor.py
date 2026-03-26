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


@pytest.mark.asyncio
async def test_run_doctor_old_python():
    from collections import namedtuple
    VersionInfo = namedtuple("VersionInfo", ["major", "minor", "micro"])
    with patch("sys.version_info", VersionInfo(3, 8, 0)):
        with patch("builtins.print") as mock_print:
            await run_doctor()
            # Verify it printed the version warning
            calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
            assert any("too old" in str(c) for c in calls)


@pytest.mark.asyncio
async def test_run_doctor_missing_deps(monkeypatch):
    with patch("builtins.__import__", side_effect=ImportError("Missing")):
        # We need to ensure we don't break other imports during the test
        # But run_doctor only calls __import__ inside its loop
        with patch("builtins.print") as mock_print:
            await run_doctor()
            calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
            assert any("missing" in str(c).lower() for c in calls)
