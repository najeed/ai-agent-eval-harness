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

    # Mocking semantic mapping for Gemini SDK
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Gemini response"
    mock_response.usage_metadata = None

    # generate_content is async in the SDK's aio namespace
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch("google.genai.Client", return_value=mock_client):
        res = await adapter.execute_gemini_query({"api_key": "test", "task_description": "hi"})
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
    registry = MagicMock()
    from unittest.mock import ANY

    OpenAIAdapterPlugin().on_discover_adapters(registry)
    registry.register.assert_any_call("openai", ANY)

    ClaudeAdapterPlugin().on_discover_adapters(registry)
    registry.register.assert_any_call("claude", ANY)

    GeminiAdapterPlugin().on_discover_adapters(registry)
    registry.register.assert_any_call("gemini", ANY)


@pytest.mark.asyncio
async def test_autogen_adapter_fallback():
    """Test AutoGen adapter initialization and execute entry point."""
    adapter = AutoGenAdapterPlugin()
    # Test discovery
    reg = MagicMock()
    adapter.on_discover_adapters(reg)
    reg.register.assert_any_call("autogen", adapter.execute_autogen_query)

    # Test entry point error handling (fallback path)
    res = await adapter.execute_autogen_query({"message": "hi"})
    assert res["status"] == "error"
