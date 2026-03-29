# tests/test_langchain_adapter.py
import pytest
from unittest.mock import MagicMock
from eval_runner.adapters.langchain import LangChainAdapterPlugin

@pytest.mark.asyncio
async def test_langchain_adapter_registration():
    """Verify registry hook."""
    adapter = LangChainAdapterPlugin()
    registry = MagicMock()

@pytest.mark.asyncio
async def test_langchain_adapter_success(aiohttp_client):
    """Test successful LangServe invocation."""
    from aiohttp import web
    
    async def mock_handler(request):
        return web.json_response({"output": "LangChain response"})
        
    app = web.Application()
    app.router.add_post("/invoke", mock_handler)
    client = await aiohttp_client(app)
    url = str(client.make_url("/invoke"))
    
    adapter = LangChainAdapterPlugin()
    payload = {"input": "hello", "url": url}
    
    result = await adapter.execute_langserve_query(payload)
    
    assert result["status"] == "success"
    assert result["output"] == "LangChain response"
    assert result["metadata"]["endpoint"] == url

@pytest.mark.asyncio
async def test_langchain_adapter_base_url_auto_invoke(aiohttp_client):
    """Test base_url without /invoke suffix."""
    from aiohttp import web
    
    async def mock_handler(request):
        return web.json_response({"output": "Auto-invoke response"})
        
    app = web.Application()
    app.router.add_post("/invoke", mock_handler)
    client = await aiohttp_client(app)
    base_url = str(client.make_url("/"))
    
    adapter = LangChainAdapterPlugin()
    # Use base_url instead of url
    payload = {"input": "hello", "base_url": base_url}
    
    result = await adapter.execute_langserve_query(payload)
    
    assert result["status"] == "success"
    assert result["output"] == "Auto-invoke response"
    assert result["metadata"]["endpoint"] == base_url.rstrip("/") + "/invoke"

@pytest.mark.asyncio
async def test_langchain_adapter_missing_url():
    """Test error when no URL is provided."""
    adapter = LangChainAdapterPlugin()
    payload = {"input": "hello"}
    result = await adapter.execute_langserve_query(payload)
    
    assert result["status"] == "error"
    assert "Missing 'url' or 'base_url'" in result["message"]

@pytest.mark.asyncio
async def test_langchain_adapter_error_status(aiohttp_client):
    """Test non-200 response from LangServe."""
    from aiohttp import web
    
    async def mock_handler(request):
        return web.Response(status=500, text="Internal Server Error")
        
    app = web.Application()
    app.router.add_post("/invoke", mock_handler)
    client = await aiohttp_client(app)
    url = str(client.make_url("/invoke"))
    
    adapter = LangChainAdapterPlugin()
    payload = {"input": "hello", "url": url}
    
    result = await adapter.execute_langserve_query(payload)
    
    assert result["status"] == "error"
    assert "returned 500" in result["message"]

@pytest.mark.asyncio
async def test_langchain_adapter_exception():
    """Test exception during request (e.g., invalid URL)."""
    adapter = LangChainAdapterPlugin()
    # Invalid URL scheme
    payload = {"input": "hello", "url": "not-a-url"}
    
    result = await adapter.execute_langserve_query(payload)
    
    assert result["status"] == "error"
    assert "not-a-url" in result["message"] or "InvalidURL" in str(result.get("message"))
