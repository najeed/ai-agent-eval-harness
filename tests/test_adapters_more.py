import pytest
import json
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from eval_runner.adapters.openai import OpenAIAdapterPlugin
from eval_runner.adapters.grok import GrokAdapterPlugin
from eval_runner.adapters.autogen import AutoGenAdapterPlugin
from eval_runner.adapters.crewai import CrewAIAdapterPlugin
from eval_runner.adapters.langgraph import LangGraphAdapterPlugin
from eval_runner.adapters import http_adapter, local_subprocess_adapter, socket_adapter

class MockAsyncContextManager:
    def __init__(self, status=200, json_data=None, text_data="", throw_exc=None):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data
        self._throw_exc = throw_exc

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text_data

    # specifically for __init__.py raise_for_status
    def raise_for_status(self):
        if self.status >= 400:
            raise Exception("HTTP Error")

    async def __aenter__(self):
        if self._throw_exc:
            raise self._throw_exc
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

@pytest.fixture
def mock_aiohttp_session():
    with patch("aiohttp.ClientSession") as mock_session_cls:
        session_instance = MagicMock()
        mock_session_cls.return_value.__aenter__.return_value = session_instance
        yield session_instance


# === OpenAI Adapter ===
@pytest.mark.asyncio
async def test_openai_success(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(
        json_data={"choices": [{"message": {"content": "openai_success"}}]}
    )
    plugin = OpenAIAdapterPlugin()
    res = await plugin.execute_openai_query({"task": "hello", "api_key": "test"})
    assert res["status"] == "success"
    assert res["output"] == "openai_success"

@pytest.mark.asyncio
async def test_openai_err_and_exc(mock_aiohttp_session):
    plugin = OpenAIAdapterPlugin()
    
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(status=500, text_data="Err")
    res1 = await plugin.execute_openai_query({"api_key": "x"})
    assert res1["status"] == "error"
    
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(throw_exc=Exception("Net fail"))
    res2 = await plugin.execute_openai_query({"api_key": "x"})
    assert res2["status"] == "error"


# === Grok Adapter ===
@pytest.mark.asyncio
async def test_grok_success(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(
        json_data={"choices": [{"message": {"content": "grok_success"}}]}
    )
    plugin = GrokAdapterPlugin()
    res = await plugin.execute_grok_query({"api_key": "test"})
    assert res["status"] == "success"

@pytest.mark.asyncio
async def test_grok_err_missing_exc(mock_aiohttp_session):
    plugin = GrokAdapterPlugin()
    # Missing API key
    res_no_key = await plugin.execute_grok_query({})
    assert res_no_key["status"] == "error"

    mock_aiohttp_session.post.return_value = MockAsyncContextManager(status=401)
    res_err = await plugin.execute_grok_query({"api_key": "x"})
    assert res_err["status"] == "error"

    mock_aiohttp_session.post.return_value = MockAsyncContextManager(throw_exc=Exception())
    res_exc = await plugin.execute_grok_query({"api_key": "x"})
    assert res_exc["status"] == "error"


# === AutoGen Adapter ===
@pytest.mark.asyncio
async def test_autogen_success(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(
        json_data={"output": "autogen_result"}
    )
    plugin = AutoGenAdapterPlugin()
    res = await plugin.execute_autogen_query({"url": "http://auto"})
    assert res["status"] == "success"

@pytest.mark.asyncio
async def test_autogen_err_exc(mock_aiohttp_session):
    plugin = AutoGenAdapterPlugin()
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(status=500)
    res_err = await plugin.execute_autogen_query({"url": "http://auto"})
    assert res_err["status"] == "error"

    mock_aiohttp_session.post.return_value = MockAsyncContextManager(throw_exc=Exception())
    res_exc = await plugin.execute_autogen_query({"url": "http://auto"})
    assert res_exc["status"] == "error"


# === CrewAI / LangGraph Adapters ===
@pytest.mark.asyncio
async def test_crewai_mocks():
    plugin = CrewAIAdapterPlugin()
    # Import success mock
    with patch.dict("sys.modules", {"crewai": MagicMock(__version__="1.0")}):
        res_ok = await plugin.execute_crewai_task({"task": "x"})
        assert res_ok["status"] == "success"
    # Import fail mock (remove entirely using None mapping for importlib)
    # the easiest way to mock ImportError is to hide module.
    with patch.dict("sys.modules", {"crewai": None}):
        res_fail = await plugin.execute_crewai_task({"task": "x"})
        assert res_fail["status"] == "mock_success"

@pytest.mark.asyncio
async def test_langgraph_mocks():
    plugin = LangGraphAdapterPlugin()
    with patch.dict("sys.modules", {"langgraph": MagicMock(__version__="2.0")}):
        assert (await plugin.execute_langgraph_node({"task": "x"}))["status"] == "success"
    with patch.dict("sys.modules", {"langgraph": None}):
        assert (await plugin.execute_langgraph_node({"task": "x"}))["status"] == "mock_success"


# === Base Interface (__init__.py) ===

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
    with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
        res = await local_subprocess_adapter({}, "cmd")
        assert res["test"] == "pass"

@pytest.mark.asyncio
async def test_local_subprocess_errors():
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b'err', b'stderr')
    mock_proc.returncode = 1
    with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
        with pytest.raises(RuntimeError):
            await local_subprocess_adapter({}, "cmd")
            
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b'not_json!', b'')
    with patch("asyncio.create_subprocess_shell", return_value=mock_proc):
        with pytest.raises(RuntimeError):
            await local_subprocess_adapter({}, "cmd")


@pytest.mark.asyncio
async def test_socket_adapter_unix_and_tcp():
    mock_reader = AsyncMock()
    mock_reader.readline.return_value = b'{"response": "ok"}'
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()
    
    with patch("asyncio.open_unix_connection", return_value=(mock_reader, mock_writer), create=True):
        res_unix = await socket_adapter({}, "unix:/path")
        assert res_unix["response"] == "ok"
        
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        res_tcp = await socket_adapter({}, "tcp:localhost:5000")
        assert res_tcp["response"] == "ok"
        
    with pytest.raises(ValueError):
        await socket_adapter({}, "http://bad")
