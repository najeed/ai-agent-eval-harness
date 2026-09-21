from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.adapters.ag2 import AG2AdapterPlugin
from eval_runner.adapters.claude import ClaudeAdapterPlugin
from eval_runner.adapters.gemini import GeminiAdapterPlugin
from eval_runner.adapters.grok import GrokAdapterPlugin
from eval_runner.adapters.ollama import OllamaAdapterPlugin
from eval_runner.adapters.openai import OpenAIAdapterPlugin


class MockResponse:
    def __init__(self, status=200, json_data=None, text_data=""):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text_data

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
async def test_openai_adapter_success():
    """Test successful OpenAI query execution."""
    adapter = OpenAIAdapterPlugin()

    with patch.object(adapter, "_post_json", new_callable=AsyncMock) as post_json:
        post_json.return_value = (
            {"choices": [{"message": {"content": "Hello world"}}]},
            {},
        )
        payload = {"api_key": "test", "task": "hi", "api_mode": "chat_completions"}
        res = await adapter.execute_openai_query(payload)

        assert res["status"] == "success"
        assert res["output"] == "Hello world"


@pytest.mark.asyncio
async def test_openai_adapter_error():
    """Test OpenAI error handling (401 Unauthorized)."""
    adapter = OpenAIAdapterPlugin()

    with patch.object(adapter, "_post_json", new_callable=AsyncMock) as post_json:
        import aiohttp

        post_json.side_effect = aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=401, message="Invalid API Key", headers={}
        )
        res = await adapter.execute_openai_query({"api_key": "wrong", "task": "hi"})

    assert res["status"] == "error"
    assert "401" in res["message"]


@pytest.mark.asyncio
async def test_claude_adapter_success():
    """Test Anthropic Claude adapter."""
    adapter = ClaudeAdapterPlugin()

    with patch.object(adapter, "_post", new_callable=AsyncMock) as post:
        post.return_value = {
            "__claude_response__": {"content": [{"type": "text", "text": "Claude response"}]},
            "__response_headers__": {},
        }
        res = await adapter.execute_claude_query({"api_key": "test", "task": "hi"})

    assert res["status"] == "success"
    assert "Claude" in res["output"]


@pytest.mark.asyncio
async def test_gemini_adapter_success():
    """Test Google Gemini adapter."""
    adapter = GeminiAdapterPlugin()

    with patch("google.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.aio.aclose = AsyncMock()
        adapter._execute_interaction = AsyncMock(
            return_value={"status": "success", "output": "Gemini response", "metadata": {}}
        )
        res = await adapter.execute_gemini_query({"api_key": "test", "task_description": "hi"})
    assert res["status"] == "success"
    assert "Gemini" in res["output"]


@pytest.mark.asyncio
async def test_ollama_adapter_success():
    """Test Ollama local adapter."""
    adapter = OllamaAdapterPlugin()

    with patch.object(adapter, "call_with_retry", new_callable=AsyncMock) as call_with_retry:
        call_with_retry.return_value = {"message": {"content": "Ollama response"}}
        res = await adapter.execute_ollama_query({"task": "hi"})
    assert res["status"] == "success"


@pytest.mark.asyncio
async def test_grok_adapter_success():
    """Test xAI Grok adapter."""
    adapter = GrokAdapterPlugin()

    with patch.object(adapter, "_request", new_callable=AsyncMock) as request:
        request.return_value = {"status": "completed", "output_text": "Grok response"}
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
async def test_ag2_adapter_fallback():
    """Test AG2 adapter initialization and execute entry point."""
    adapter = AG2AdapterPlugin()
    # Test discovery
    reg = MagicMock()
    adapter.on_discover_adapters(reg)
    reg.register.assert_any_call("ag2", adapter.execute_ag2_query)

    # Test entry point error handling (fallback path when SDK is missing)
    with patch.object(adapter, "_import_ag2", side_effect=ImportError("AG2 SDK not installed")):
        res = await adapter.execute_ag2_query({"message": "hi"})
        assert res["status"] == "error"
        assert "not installed" in res["message"]
