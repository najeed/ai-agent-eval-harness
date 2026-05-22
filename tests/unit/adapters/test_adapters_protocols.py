from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from eval_runner.adapters import http_adapter, local_subprocess_adapter, socket_adapter
from eval_runner.adapters.claude import ClaudeAdapterPlugin
from eval_runner.adapters.gemini import GeminiAdapterPlugin
from eval_runner.adapters.openai import OpenAIAdapterPlugin


class MockAsyncContextManager:
    def __init__(self, status=200, json_data=None):
        self.status = status
        self._json_data = json_data or {}

    async def json(self):
        return self._json_data

    def raise_for_status(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
async def test_http_adapter_core():
    mock_response = MockAsyncContextManager(json_data={"k": "v"})
    with patch("aiohttp.ClientSession.post", return_value=mock_response):
        # We need to mock the session context manager too
        with patch(
            "aiohttp.ClientSession.__aenter__",
            return_value=MagicMock(post=MagicMock(return_value=mock_response)),
        ):
            out = await http_adapter({"task": "hi"}, "http://url")
            assert out["k"] == "v"


@pytest.mark.asyncio
async def test_local_subprocess_adapter():
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b'{"test": "pass"}', b"")
    mock_proc.returncode = 0
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        res = await local_subprocess_adapter({}, "python agent.py")
        assert res["test"] == "pass"


@pytest.mark.asyncio
async def test_socket_adapter_tcp():
    mock_reader = AsyncMock()
    mock_reader.readline.return_value = b'{"response": "ok"}'
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        res = await socket_adapter({}, "tcp:localhost:5000")
        assert res["response"] == "ok"


def test_adapters_protocols_discovery():
    from eval_runner.engine import AgentAdapterRegistry

    # Force reset discovery
    AgentAdapterRegistry._discovered = False
    AgentAdapterRegistry._adapters = {}

    with patch(
        "eval_runner.config.RegistryManager.get_resolved_registry",
        return_value={"adapters": {"active_protocols": ["http", "local", "socket"]}},
    ):
        AgentAdapterRegistry._discover()
        assert "http" in AgentAdapterRegistry._adapters
        assert "local" in AgentAdapterRegistry._adapters
        assert "socket" in AgentAdapterRegistry._adapters


def test_adapters_protocols_discovery_hooks():
    registry = MagicMock()

    OpenAIAdapterPlugin().on_discover_adapters(registry)
    registry.register.assert_any_call("openai", ANY)

    ClaudeAdapterPlugin().on_discover_adapters(registry)
    registry.register.assert_any_call("claude", ANY)

    GeminiAdapterPlugin().on_discover_adapters(registry)
    registry.register.assert_any_call("gemini", ANY)


@pytest.mark.asyncio
async def test_call_agent_protocol_selection():
    from eval_runner.engine import AgentAdapterRegistry

    payload = {"test": "data"}
    AgentAdapterRegistry._discovered = False
    AgentAdapterRegistry._discover()

    with patch.dict(
        AgentAdapterRegistry._adapters,
        {"local": AsyncMock(return_value={"action": "final_answer", "content": "ok"})},
    ):
        result = await AgentAdapterRegistry.call_agent("local", "echo 'test'", str(payload), [])
        assert result["content"] == "ok"


@pytest.mark.asyncio
async def test_call_agent_env_fallback():
    import os

    from eval_runner.engine import AgentAdapterRegistry

    payload = {"test": "data"}
    AgentAdapterRegistry._discovered = False
    AgentAdapterRegistry._discover()

    with patch.dict(os.environ, {"AGENT_LOCAL_CMD": "python mock_agent.py"}):
        with patch.dict(
            AgentAdapterRegistry._adapters,
            {"local": AsyncMock(return_value={"action": "final_answer", "content": "env_ok"})},
        ):
            result = await AgentAdapterRegistry.call_agent("local", None, str(payload), [])
            assert result["content"] == "env_ok"
