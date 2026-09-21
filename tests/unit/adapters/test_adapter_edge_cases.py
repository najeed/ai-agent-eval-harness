import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.adapters.ag2 import AG2AdapterPlugin
from eval_runner.adapters.grok import GrokAdapterPlugin


@pytest.mark.asyncio
async def test_ag2_adapter():
    adapter = AG2AdapterPlugin()
    payload = {"task_description": "test", "url": "http://mock-ag2/execute"}

    result = await adapter.execute_ag2_query(payload)

    assert result["status"] == "error"
    assert result["metadata"]["mode"] == "remote"


@pytest.mark.asyncio
async def test_grok_adapter():
    os.environ["XAI_API_KEY"] = "xai-test"
    adapter = GrokAdapterPlugin()
    payload = {"task_description": "test"}

    with patch.object(adapter, "_request", new_callable=AsyncMock) as request:
        request.return_value = {"output_text": "grok response", "status": "completed"}

        result = await adapter.execute_grok_query(payload)

    assert result["status"] == "success"
    assert result["output"] == "grok response"


@pytest.mark.asyncio
async def test_grok_success_response_uses_bounded_common_reader():
    adapter = GrokAdapterPlugin()
    response = MagicMock(status=200)

    class RequestContext:
        async def __aenter__(self):
            return response

        async def __aexit__(self, exc_type, exc_value, traceback):
            return False

    session = MagicMock()
    session.post.return_value = RequestContext()
    adapter.session_pool.get_session = AsyncMock(return_value=session)

    with patch(
        "eval_runner.adapters.grok.read_response_bytes",
        new=AsyncMock(return_value=b'{"output": "complete"}'),
    ) as read_body:
        result = await adapter._request(
            endpoint="https://api.x.ai/v1/responses",
            headers={},
            body={},
            stream=False,
            timeout_seconds=1,
            api_mode="responses",
        )

    assert result == {"output": "complete"}
    assert read_body.await_count == 1
