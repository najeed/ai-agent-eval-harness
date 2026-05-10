import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.adapters.autogen import AG2AdapterPlugin
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
async def test_langchain_adapter_simulation_fallback():
    plugin = LangChainAdapterPlugin()
    # Missing both URL and chain_path -> simulation fallback
    res = await plugin.execute_langchain_query({"input": {}})
    assert res["status"] == "success"
    assert "Simulation" in res["output"]


@pytest.mark.asyncio
async def test_langchain_adapter_sdk_fallback_error():
    plugin = LangChainAdapterPlugin()
    # Mock SDK missing
    with patch.dict("sys.modules", {"langchain": None}):
        res = await plugin._execute_local_sdk("id", {}, "module:chain")
        assert res["status"] == "error"
        assert "SDK not installed" in res["message"]


@pytest.mark.asyncio
async def test_langchain_adapter_remote_error():
    plugin = LangChainAdapterPlugin()
    with patch("eval_runner.adapters.common.SessionManager.get_session") as mock_get_session:
        session_instance = MagicMock()
        mock_get_session.return_value = session_instance
        # Mock immediate 500 error after retries (or just one failure for test)
        session_instance.post.return_value = MockResponse(status=500)

        # We patch retries to 1 for speed
        with patch.object(plugin, "max_retries", 1), patch("asyncio.sleep", AsyncMock()):
            res = await plugin._execute_remote_langserve("http://langserve", {}, {})
            assert res["status"] == "error"
            assert "500" in res["message"] or "Error" in res["message"]


@pytest.mark.asyncio
async def test_autogen_adapter_sdk_fallback_to_remote():
    plugin = AG2AdapterPlugin()
    # Mock SDK missing, trigger remote fallback
    with patch.dict("sys.modules", {"ag2": None, "autogen": None}):
        with patch("eval_runner.adapters.common.SessionManager.get_session") as mock_get_session:
            session_instance = MagicMock()
            mock_get_session.return_value = session_instance
            session_instance.post.return_value = MockResponse(
                json_data={"output": "remote_success"}
            )
            res = await plugin.execute_autogen_query({"message": "hi"}, url="http://autogen-api")
            assert res["status"] == "success"
            assert res["output"] == "remote_success"


@pytest.mark.asyncio
async def test_autogen_adapter_missing_all():
    plugin = AG2AdapterPlugin()
    with patch.dict("sys.modules", {"ag2": None, "autogen": None}):
        with patch("eval_runner.config.AG2_API_URL", None):
            res = await plugin.execute_autogen_query({"message": "hi"})
            assert res["status"] == "error"
            assert "Native execution failed" in res["message"]


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
    # Adapter receives a single payload dict and endpoint as keyword
    payload = args[0]
    assert payload["protocol"] == "test"
    assert payload["task_description"] == '{"input": "x"}'
    assert kwargs["endpoint"] == "http://t"
