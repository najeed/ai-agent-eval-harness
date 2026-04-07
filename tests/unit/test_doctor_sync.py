import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from eval_runner.doctor import check_agent_reachable


@pytest.mark.asyncio
async def test_doctor_sync_loop_drift():
    """Verify that doctor correctly uses the running event loop for aiohttp calls (Elegant)."""
    mock_url = "http://localhost:5001/status"

    # Mock aiohttp.ClientSession
    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_instance = MagicMock()
        mock_session_cls.return_value = mock_instance
        
        # 'async with ClientSession() as session:'
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__ = AsyncMock()
        
        # 'async with session.post(...) as response:'
        mock_post_context = MagicMock()
        mock_instance.post.return_value = mock_post_context
        mock_response = MagicMock(status=200)
        mock_post_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_context.__aexit__ = AsyncMock()

        # 1. Run the check
        result = await check_agent_reachable(mock_url)

        assert result is True
        # Verify that ClientSession was initialized with the current loop
        loop = asyncio.get_running_loop()
        mock_session_cls.assert_called_once()
        assert mock_session_cls.call_args.kwargs["loop"] == loop
