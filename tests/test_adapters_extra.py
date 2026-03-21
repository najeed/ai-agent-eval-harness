import pytest
from unittest.mock import patch, MagicMock
from eval_runner.adapters.claude import ClaudeAdapterPlugin
from eval_runner.adapters.gemini import GeminiAdapterPlugin
from eval_runner.adapters.langchain import LangChainAdapterPlugin
from eval_runner.adapters.ollama import OllamaAdapterPlugin

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

# --- Claude Tests ---
@pytest.mark.asyncio
async def test_claude_success(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(
        status=200, 
        json_data={"content": [{"text": "claude response"}]}
    )
    
    plugin = ClaudeAdapterPlugin()
    res = await plugin.execute_claude_query({
        "api_key": "test_key",
        "task": "hello",
        "system_prompt": "sys"
    })
    
    assert res["status"] == "success"
    assert res["output"] == "claude response"
    assert res["metadata"]["framework"] == "claude"

@pytest.mark.asyncio
async def test_claude_error(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(
        status=500, 
        text_data="Bad Request"
    )
    
    plugin = ClaudeAdapterPlugin()
    res = await plugin.execute_claude_query({"task": "hi"})
    assert res["status"] == "error"
    assert "Bad Request" in res["message"]

@pytest.mark.asyncio
async def test_claude_exception(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(throw_exc=Exception("Network failure"))
    
    plugin = ClaudeAdapterPlugin()
    res = await plugin.execute_claude_query({"task": "hi"})
    assert res["status"] == "error"
    assert "Network failure" in res["message"]


# --- Gemini Tests ---
@pytest.mark.asyncio
async def test_gemini_success(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(
        status=200, 
        json_data={"candidates": [{"content": {"parts": [{"text": "gemini response"}]}}]}
    )
    
    plugin = GeminiAdapterPlugin()
    res = await plugin.execute_gemini_query({
        "api_key": "test_key",
        "messages": [{"role": "user", "content": "hello msg"}, {"role": "model", "content": "hi back"}]
    })
    
    assert res["status"] == "success"
    assert res["output"] == "gemini response"
    assert res["metadata"]["framework"] == "gemini"

@pytest.mark.asyncio
async def test_gemini_error(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(status=500, text_data="API err")
    plugin = GeminiAdapterPlugin()
    res = await plugin.execute_gemini_query({"task": "hi"})
    assert res["status"] == "error"

@pytest.mark.asyncio
async def test_gemini_exception(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(throw_exc=Exception("GCP err"))
    plugin = GeminiAdapterPlugin()
    res = await plugin.execute_gemini_query({"task": "hi"})
    assert res["status"] == "error"


# --- LangChain Tests ---
@pytest.mark.asyncio
async def test_langchain_success(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(
        status=200, 
        json_data={"output": "langchain response"}
    )
    
    plugin = LangChainAdapterPlugin()
    res = await plugin.execute_langserve_query({
        "url": "http://localhost:8000/mychain",
        "input": "test input"
    })
    
    assert res["status"] == "success"
    assert res["output"] == "langchain response"

@pytest.mark.asyncio
async def test_langchain_bad_url():
    plugin = LangChainAdapterPlugin()
    res = await plugin.execute_langserve_query({"input": "test_input"})
    assert res["status"] == "error"
    assert "Missing 'url'" in res["message"]

@pytest.mark.asyncio
async def test_langchain_error(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(status=500, text_data="Server Error")
    plugin = LangChainAdapterPlugin()
    res = await plugin.execute_langserve_query({"url": "http://localhost/", "task": "hi"})
    assert res["status"] == "error"
    assert "500" in res["message"]

@pytest.mark.asyncio
async def test_langchain_exception(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(throw_exc=Exception("Timeout"))
    plugin = LangChainAdapterPlugin()
    res = await plugin.execute_langserve_query({"url": "http://localhost/", "task": "hi"})
    assert res["status"] == "error"


# --- Ollama Tests ---
@pytest.mark.asyncio
async def test_ollama_success(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(
        status=200, 
        json_data={"message": {"content": "ollama response"}}
    )
    
    plugin = OllamaAdapterPlugin()
    res = await plugin.execute_ollama_query({"task": "hello"})
    assert res["status"] == "success"
    assert res["output"] == "ollama response"

@pytest.mark.asyncio
async def test_ollama_error(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(status=500, text_data="Err")
    plugin = OllamaAdapterPlugin()
    res = await plugin.execute_ollama_query({"task": "hello"})
    assert res["status"] == "error"

@pytest.mark.asyncio
async def test_ollama_exception(mock_aiohttp_session):
    mock_aiohttp_session.post.return_value = MockAsyncContextManager(throw_exc=Exception("Localhost err"))
    plugin = OllamaAdapterPlugin()
    res = await plugin.execute_ollama_query({"task": "hello"})
    assert res["status"] == "error"

