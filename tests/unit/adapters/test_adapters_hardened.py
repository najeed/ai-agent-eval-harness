from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.adapters.autogen import AutoGenAdapterPlugin
from eval_runner.adapters.claude import ClaudeAdapterPlugin
from eval_runner.adapters.gemini import GeminiAdapterPlugin
from eval_runner.adapters.grok import GrokAdapterPlugin
from eval_runner.adapters.ollama import OllamaAdapterPlugin
from eval_runner.adapters.openai import OpenAIAdapterPlugin


@pytest.mark.asyncio
async def test_openai_adapter_success():
    """Test successful OpenAI query execution."""
    adapter = OpenAIAdapterPlugin()

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json.return_value = {"choices": [{"message": {"content": "Hello world"}}]}

    # Mock aiohttp ClientSession
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value.__aenter__.return_value = mock_response

        payload = {"api_key": "test", "task": "hi"}
        res = await adapter.execute_openai_query(payload)

        assert res["status"] == "success"
        assert res["output"] == "Hello world"


@pytest.mark.asyncio
async def test_openai_adapter_error():
    """Test OpenAI error handling (401 Unauthorized)."""
    adapter = OpenAIAdapterPlugin()

    mock_response = AsyncMock()
    mock_response.status = 401
    mock_response.text.return_value = "Invalid API Key"

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value.__aenter__.return_value = mock_response

        res = await adapter.execute_openai_query({"api_key": "wrong"})
        assert res["status"] == "error"
        assert "401" in res["message"]


@pytest.mark.asyncio
async def test_claude_adapter_success():
    """Test Anthropic Claude adapter."""
    adapter = ClaudeAdapterPlugin()

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json.return_value = {"content": [{"text": "Claude response"}]}

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value.__aenter__.return_value = mock_response

        res = await adapter.execute_claude_query({"api_key": "test", "task": "hi"})
        assert res["status"] == "success"
        assert "Claude" in res["output"]


@pytest.mark.asyncio
async def test_gemini_adapter_success():
    """Test Google Gemini adapter."""
    adapter = GeminiAdapterPlugin()

    mock_response = AsyncMock()
    # Mocking semantic mapping for missing lines in gemini.py
    mock_response.status = 200
    mock_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "Gemini response"}]}}]
    }

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value.__aenter__.return_value = mock_response
        res = await adapter.execute_gemini_query({"api_key": "test", "task": "hi"})
        assert res["status"] == "success"
        assert "Gemini" in res["output"]


@pytest.mark.asyncio
async def test_ollama_adapter_success():
    """Test Ollama local adapter."""
    adapter = OllamaAdapterPlugin()

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json.return_value = {"message": {"content": "Ollama response"}}

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value.__aenter__.return_value = mock_response
        res = await adapter.execute_ollama_query({"task": "hi"})
        assert res["status"] == "success"


@pytest.mark.asyncio
async def test_grok_adapter_success():
    """Test xAI Grok adapter."""
    adapter = GrokAdapterPlugin()

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json.return_value = {"choices": [{"message": {"content": "Grok response"}}]}

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value.__aenter__.return_value = mock_response
        res = await adapter.execute_grok_query({"api_key": "test", "task": "hi"})
        assert res["status"] == "success"


def test_adapter_discovery_hooks():
    """Test on_discover_adapters for all major plugins."""
    registry = MagicMock()

    OpenAIAdapterPlugin().on_discover_adapters(registry)
    registry.register.assert_any_call("openai", pytest.any_call)

    ClaudeAdapterPlugin().on_discover_adapters(registry)
    registry.register.assert_any_call("claude", pytest.any_call)

    GeminiAdapterPlugin().on_discover_adapters(registry)
    registry.register.assert_any_call("gemini", pytest.any_call)


@pytest.mark.asyncio
async def test_autogen_adapter_fallback():
    """Test AutoGen adapter initialization and execute entry point."""
    adapter = AutoGenAdapterPlugin()
    # Test discovery
    reg = MagicMock()
    adapter.on_discover_adapters(reg)
    reg.register.assert_any_call("autogen", adapter.execute_autogen_task)

    # Test entry point error handling
    res = await adapter.execute_autogen_task({"no_params": True})
    # Since it needs real autogen libs or complex mocks, we test it handles missing config
    assert res["status"] == "error"
