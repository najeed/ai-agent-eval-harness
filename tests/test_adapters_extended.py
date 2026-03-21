import pytest
import os
from unittest.mock import AsyncMock, patch
from eval_runner.adapters.autogen import AutoGenAdapterPlugin
from eval_runner.adapters.grok import GrokAdapterPlugin


@pytest.mark.asyncio
async def test_autogen_adapter():
    adapter = AutoGenAdapterPlugin()
    payload = {"task": "test", "url": "http://mock-autogen/execute"}

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {"output": "done"}
        mock_post.return_value.__aenter__.return_value = mock_response

        result = await adapter.execute_autogen_query(payload)
        assert result["status"] == "success"
        assert result["output"] == "done"


@pytest.mark.asyncio
async def test_grok_adapter():
    os.environ["XAI_API_KEY"] = "xai-test"
    adapter = GrokAdapterPlugin()
    payload = {"task": "test"}

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {"choices": [{"message": {"content": "grok response"}}]}
        mock_post.return_value.__aenter__.return_value = mock_response

        result = await adapter.execute_grok_query(payload)
        assert result["status"] == "success"
        assert result["output"] == "grok response"
