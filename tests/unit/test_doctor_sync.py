import pytest
import asyncio
from unittest.mock import MagicMock, patch
from eval_runner.doctor import check_agent_reachable

@pytest.mark.asyncio
async def test_doctor_sync_loop_drift():
    """Verify that doctor correctly uses the running event loop for aiohttp calls."""
    mock_url = "http://localhost:5001/status"
    
    # Mock aiohttp.ClientSession
    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value.__aenter__.return_value = mock_session
        
        # Mock the POST request
        mock_response = MagicMock()
        mock_response.status = 200
        mock_session.post.return_value.__aenter__.return_value = mock_response
        
        # 1. Run the check
        # This will test if check_agent_reachable correctly calls get_running_loop()
        # and passes it to the Session.
        result = await check_agent_reachable(mock_url)
        
        assert result is True
        # Verify that ClientSession was initialized with the current loop
        loop = asyncio.get_running_loop()
        mock_session_cls.assert_called_once_with(loop=loop)
