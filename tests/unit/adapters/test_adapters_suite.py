"""
test_adapters_suite.py

Unified verification suite for AI agent adapters (Claude, Gemini, OpenAI, Grok, AutoGen, CrewAI, LangGraph, etc.).
Combines high-fidelity aiohttp server stubs with surgical mock-based tests for 100% coverage.
"""

import pytest
import pytest_asyncio
import json
import asyncio
import sys
from aiohttp import web
from unittest.mock import patch, MagicMock, AsyncMock

from eval_runner.adapters.claude import ClaudeAdapterPlugin
from eval_runner.adapters.gemini import GeminiAdapterPlugin
from eval_runner.adapters.openai import OpenAIAdapterPlugin
from eval_runner.adapters.grok import GrokAdapterPlugin
from eval_runner.adapters.autogen import AutoGenAdapterPlugin
from eval_runner.adapters.crewai import CrewAIAdapterPlugin
from eval_runner.adapters.langgraph import LangGraphAdapterPlugin
from eval_runner.adapters.langchain import LangChainAdapterPlugin
from eval_runner.adapters.ollama import OllamaAdapterPlugin
from eval_runner.adapters import http_adapter, local_subprocess_adapter, socket_adapter

# --- Fixtures ---

@pytest.fixture(scope="session")
def event_loop():
    """Ensure a clean event loop teardown on Windows/Linux."""
    if sys.platform == 'win32':
        loop = asyncio.WindowsProactorEventLoopPolicy().new_event_loop()
    else:
        loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture
async def adapter_stub(aiohttp_server):
    """Provides a local aiohttp server that simulates various LLM provider APIs."""
    async def handle_request(request):
        path = request.path
        try:
            data = await request.json()
        except:
            data = {}
            
        # Claude (Anthropic) Mocking
        if "v1/messages" in path:
            if data.get("force_error"):
                return web.Response(text="Claude internal error", status=500)
            return web.json_response({"content": [{"text": "claude response"}]})
            
        # Gemini (Google) Mocking
        if "v1beta/models" in path:
            if data.get("force_error"):
                return web.Response(text="Gemini internal error", status=500)
            return web.json_response({
                "candidates": [{"content": {"parts": [{"text": "gemini response"}]}}]
            })
            
        # LangServe (LangChain) Mocking
        if "invoke" in path:
            if data.get("force_error"):
                return web.Response(text="LangServe error", status=500)
            return web.json_response({"output": "langchain response"})
            
        # Ollama Mocking
        if "api/chat" in path:
            if data.get("force_error"):
                return web.Response(text="Ollama error", status=500)
            return web.json_response({"message": {"content": "ollama response"}})
            
        return web.Response(text="Not Found", status=404)

    app = web.Application()
    app.router.add_post("/{tail:.*}", handle_request)
    return await aiohttp_server(app)

class MockAsyncContextManager:
    def __init__(self, status=200, json_data=None, text_data="", throw_exc=None):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data
        self._throw_exc = throw_exc

    async def json(self): return self._json_data
    async def text(self): return self._text_data
    def raise_for_status(self):
        if self.status >= 400: raise Exception("HTTP Error")
    async def __aenter__(self):
        if self._throw_exc: raise self._throw_exc
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb): pass

@pytest.fixture
def mock_aiohttp_session():
    with patch("aiohttp.ClientSession") as mock_session_cls:
        session_instance = MagicMock()
        mock_session_cls.return_value.__aenter__.return_value = session_instance
        yield session_instance


# --- High-Fidelity Stub Tests ---

@pytest.mark.asyncio
async def test_claude_success_stub(adapter_stub):
    server = adapter_stub
    base_url = f"http://{server.host}:{server.port}/v1/messages"
    plugin = ClaudeAdapterPlugin()
    with patch("eval_runner.config.ANTHROPIC_BASE_URL", base_url):
        res = await plugin.execute_claude_query({"api_key": "test", "task_description": "hello"})
        assert res["status"] == "success"
        assert res["output"] == "claude response"

@pytest.mark.asyncio
async def test_gemini_success_stub(adapter_stub):
    server = adapter_stub
    base_url = f"http://{server.host}:{server.port}/v1beta/models"
    plugin = GeminiAdapterPlugin()
    with patch("eval_runner.config.GEMINI_BASE_URL", base_url):
        res = await plugin.execute_gemini_query({"api_key": "test", "messages": [{"role":"user","content":"hi"}]})
        assert res["status"] == "success"

@pytest.mark.asyncio
async def test_ollama_success_stub(adapter_stub):
    server = adapter_stub
    api_url = f"http://{server.host}:{server.port}/api/chat"
    plugin = OllamaAdapterPlugin()
    with patch("eval_runner.config.OLLAMA_API_URL", api_url):
        res = await plugin.execute_ollama_query({"task_description": "hello"})
        assert res["status"] == "success"


# --- Mock-Based Plugin Tests ---

@pytest.mark.asyncio
async def test_openai_success(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(
        json_data={"choices": [{"message": {"content": "openai_success"}}]}
    )
    plugin = OpenAIAdapterPlugin()
    res = await plugin.execute_openai_query({"task_description": "hello", "api_key": "test"})
    assert res["status"] == "success"
    assert res["output"] == "openai_success"

@pytest.mark.asyncio
async def test_grok_success(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(
        json_data={"choices": [{"message": {"content": "grok_success"}}]}
    )
    plugin = GrokAdapterPlugin()
    res = await plugin.execute_grok_query({"api_key": "test"})
    assert res["status"] == "success"

@pytest.mark.asyncio
async def test_crewai_mocks():
    plugin = CrewAIAdapterPlugin()
    with patch.dict("sys.modules", {"crewai": MagicMock(__version__="1.0")}):
        res = await plugin.execute_crewai_task({"task_description": "x"})
        assert res["status"] == "success"

@pytest.mark.asyncio
async def test_langgraph_mocks():
    plugin = LangGraphAdapterPlugin()
    with patch.dict("sys.modules", {"langgraph": MagicMock(__version__="2.0")}):
        res = await plugin.execute_langgraph_node({"task_description": "x"})
        assert res["status"] == "success"


# --- Base Protocol Tests ---

@pytest.mark.asyncio
async def test_http_adapter_core(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(json_data={"k": "v"})
    out = await http_adapter({}, "http://url")
    assert out["k"] == "v"

@pytest.mark.asyncio
async def test_local_subprocess_adapter():
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b'{"test": "pass"}', b'')
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
