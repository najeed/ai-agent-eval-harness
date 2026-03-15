import sys
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from eval_runner.doctor import check_agent_reachable, run_doctor

@pytest.mark.asyncio
async def test_check_agent_reachable_success():
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_post.return_value.__aenter__.return_value = mock_response
        
        result = await check_agent_reachable("http://test-agent")
        assert result is True

@pytest.mark.asyncio
async def test_check_agent_reachable_failure():
    with patch("aiohttp.ClientSession.post", side_effect=Exception("Connection Failed")):
        result = await check_agent_reachable("http://test-agent")
        assert result is False

@pytest.mark.asyncio
async def test_run_doctor_smoke(capsys):
    """Smoke test for the doctor command."""
    mock_sys = MagicMock()
    mock_sys.major = 3
    mock_sys.minor = 11
    mock_sys.micro = 0
    
    with patch("sys.version_info", mock_sys), \
         patch("builtins.__import__", side_effect=lambda name, *args: MagicMock()), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("eval_runner.doctor.check_agent_reachable", new_callable=AsyncMock) as mock_reachable:
        
        mock_reachable.return_value = True
        await run_doctor()
        
        captured = capsys.readouterr()
        assert "Environment Doctor" in captured.out
        assert "Python version OK" in captured.out
        assert "reachable" in captured.out
        assert "AES schema found" in captured.out
