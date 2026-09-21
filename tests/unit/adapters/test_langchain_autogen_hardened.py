import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from eval_runner.adapters.ag2 import AG2AdapterPlugin
from eval_runner.adapters.langchain import LangChainAdapterPlugin
from eval_runner.engine import AgentAdapterRegistry


class MockResponse:
    def __init__(self, status=200, json_data=None):
        self.status = status
        self._json_data = json_data or {}

    async def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status >= 400:
            from unittest.mock import MagicMock

            import aiohttp

            raise aiohttp.ClientResponseError(
                request_info=MagicMock(), history=(), status=self.status, message="Error"
            )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
async def test_langchain_adapter_missing_target_fails_closed():
    plugin = LangChainAdapterPlugin()
    # Missing both URL and chain_path must not synthesize a response.
    res = await plugin.execute_langchain_query({"input": {}})
    assert res["status"] == "error"
    assert "No LangChain execution target" in res["message"]


@pytest.mark.asyncio
async def test_langchain_adapter_invalid_local_target_error():
    plugin = LangChainAdapterPlugin()
    res = await plugin.execute_langchain_query({"metadata": {"chain_path": "invalid"}})
    assert res["status"] == "error"
    assert "Invalid LangChain target" in res["message"]


@pytest.mark.asyncio
async def test_langchain_adapter_remote_error():
    plugin = LangChainAdapterPlugin()
    with patch.object(plugin, "_remote_invoke", new_callable=AsyncMock) as remote_invoke:
        remote_invoke.side_effect = RuntimeError("HTTP 500")
        res = await plugin.execute_langchain_query({"input": {}, "url": "http://langserve"})

    assert res["status"] == "error"
    assert "HTTP 500" in res["message"]


@pytest.mark.asyncio
async def test_ag2_adapter_remote_requires_native_a2a_client():
    plugin = AG2AdapterPlugin()
    # AG2 endpoints are A2A Agent Cards, never generic JSON HTTP fallbacks.
    with patch.dict("sys.modules", {"ag2": None}):
        with patch("eval_runner.adapters.common.SessionManager.get_session"):
            res = await plugin.execute_ag2_query({"message": "hi"}, url="http://ag2-api")
            assert res["status"] == "error"


@pytest.mark.asyncio
async def test_ag2_adapter_missing_all():
    plugin = AG2AdapterPlugin()
    with patch.dict("sys.modules", {"ag2": None}):
        with patch("eval_runner.config.AG2_API_URL", None):
            res = await plugin.execute_ag2_query({"message": "hi"})
            assert res["status"] == "error"
            assert "AG2 SDK is not installed" in res["message"]


def test_registry_edge_cases():
    # Unknown protocol
    with pytest.raises(ValueError, match="Unsupported protocol 'ghost'"):
        # Industrial Signature: (protocol, endpoint, message, history, turn_ctx=None)
        asyncio.run(AgentAdapterRegistry.call_agent("ghost", "dummy", "{}", []))


@pytest.mark.asyncio
async def test_registry_call_agent_with_overrides():
    registry = AgentAdapterRegistry()
    mock_adapter = AsyncMock(return_value={"status": "success"})
    registry.register("test", mock_adapter)

    # Industrial Multi-Agent Signature: (protocol, endpoint, message, history, turn_ctx=None)
    # Overrides and other metadata should now be part of turn_ctx or message payload
    # in the v1.5.0 specification.
    await AgentAdapterRegistry.call_agent("test", "http://t", '{"input": "x"}', [])

    # Check that adapter was called with correct args
    args, kwargs = mock_adapter.call_args
    # Adapter receives a single payload dict and endpoint as keyword.
    # The wire payload contains only task_description (no harness-internal fields
    # like protocol, turn, metadata, or input_payload).
    payload = args[0]
    assert payload["task_description"] == '{"input": "x"}'
    assert "protocol" not in payload, "protocol must not leak onto the wire payload"
    assert "input_payload" not in payload, "input_payload must not leak onto the wire payload"
    assert kwargs["endpoint"] == "http://t"
