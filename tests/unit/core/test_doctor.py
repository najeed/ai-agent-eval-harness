import sys
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from eval_runner.doctor import check_agent_reachable, run_doctor


@pytest.mark.asyncio
async def test_check_agent_reachable_success():
    """Verify check_agent_reachable returns True on HTTP 200/400 (Elegant Mock)."""
    with patch("aiohttp.ClientSession") as mock_session_cls:
        # 1. Constructor returns an instance
        mock_instance = MagicMock()
        mock_session_cls.return_value = mock_instance
        
        # 2. 'async with ClientSession() as session:'
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__ = AsyncMock()
        
        # 3. 'async with session.post(...) as response:'
        mock_post_context = MagicMock()
        mock_instance.post.return_value = mock_post_context
        
        mock_response = MagicMock()
        mock_response.status = 200
        mock_post_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_context.__aexit__ = AsyncMock()
        
        result = await check_agent_reachable("http://localhost:5001")
        assert result is True


@pytest.mark.asyncio
async def test_check_agent_reachable_failure():
    """Verify check_agent_reachable returns False on Exception (Elegant Mock)."""
    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_session_cls.side_effect = Exception("Unreachable")
        result = await check_agent_reachable("http://localhost:5001")
        assert result is False


@pytest.mark.asyncio
async def test_run_doctor_smoke():
    # Smoke test to ensure it runs without crashing
    with patch("builtins.print") as mock_print:
        with patch("eval_runner.doctor.check_agent_reachable", new_callable=AsyncMock) as mock_reach:
            mock_reach.return_value = True
            await run_doctor()
            assert mock_print.called


@pytest.mark.asyncio
async def test_run_doctor_old_python():
    from collections import namedtuple

    VersionInfo = namedtuple("VersionInfo", ["major", "minor", "micro"])
    with patch("sys.version_info", VersionInfo(3, 8, 0)):
        with patch("builtins.print") as mock_print:
            with patch("eval_runner.doctor.check_agent_reachable", new_callable=AsyncMock) as mock_reach:
                mock_reach.return_value = True
                await run_doctor()
                # Verify it printed the version warning
                calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
                assert any("too old" in str(c).lower() for c in calls)


@pytest.mark.asyncio
async def test_run_doctor_missing_deps(monkeypatch):
    with patch("builtins.__import__", side_effect=ImportError("Missing")):
        # We need to ensure we don't break other imports during the test
        with patch("builtins.print") as mock_print:
            with patch("eval_runner.doctor.check_agent_reachable", new_callable=AsyncMock) as mock_reach:
                mock_reach.return_value = True
                await run_doctor()
                calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
                assert any("missing" in str(c).lower() for c in calls)
