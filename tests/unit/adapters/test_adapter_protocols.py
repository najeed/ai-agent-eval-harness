from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.adapters.autogen import AutoGenAdapterPlugin
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

    mock_response = MockResponse(json_data={"choices": [{"message": {"content": "Hello world"}}]})

    with patch("eval_runner.adapters.common.SessionManager.get_session") as mock_get_session:
        session_instance = MagicMock()
        mock_get_session.return_value = session_instance
        session_instance.post.return_value = mock_response

        payload = {"api_key": "test", "task": "hi"}
        res = await adapter.execute_openai_query(payload)

        assert res["status"] == "success"
        assert res["output"] == "Hello world"


@pytest.mark.asyncio
async def test_openai_adapter_error():
    """Test OpenAI error handling (401 Unauthorized)."""
    adapter = OpenAIAdapterPlugin()

    mock_response = MockResponse(status=401, text_data="Invalid API Key")

    with patch("eval_runner.adapters.common.SessionManager.get_session") as mock_get_session:
        session_instance = MagicMock()
        mock_get_session.return_value = session_instance
        session_instance.post.return_value = mock_response

        # Patch retries so it fails fast
        with patch.object(adapter, "max_retries", 1), patch("asyncio.sleep", AsyncMock()):
            res = await adapter.execute_openai_query({"api_key": "wrong"})
            assert res["status"] == "error"
            assert "401" in res["message"]


@pytest.mark.asyncio
async def test_claude_adapter_success():
    """Test Anthropic Claude adapter."""
    adapter = ClaudeAdapterPlugin()

    mock_response = MockResponse(json_data={"content": [{"text": "Claude response"}]})

    with patch("eval_runner.adapters.common.SessionManager.get_session") as mock_get_session:
        session_instance = MagicMock()
        mock_get_session.return_value = session_instance
        session_instance.post.return_value = mock_response

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

    mock_response = MockResponse(json_data={"message": {"content": "Ollama response"}})

    with patch("eval_runner.adapters.common.SessionManager.get_session") as mock_get_session:
        session_instance = MagicMock()
        mock_get_session.return_value = session_instance
        session_instance.post.return_value = mock_response
        res = await adapter.execute_ollama_query({"task": "hi"})
        assert res["status"] == "success"


@pytest.mark.asyncio
async def test_grok_adapter_success():
    """Test xAI Grok adapter."""
    adapter = GrokAdapterPlugin()

    mock_response = MockResponse(json_data={"choices": [{"message": {"content": "Grok response"}}]})

    with patch("eval_runner.adapters.common.SessionManager.get_session") as mock_get_session:
        session_instance = MagicMock()
        mock_get_session.return_value = session_instance
        session_instance.post.return_value = mock_response
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

    # Test entry point error handling (fallback path when SDK is missing)
    with (
        patch.dict("sys.modules", {"autogen": None}),
        patch("eval_runner.adapters.autogen.config") as mock_cfg,
    ):
        mock_cfg.AUTOGEN_API_URL = None
        res = await adapter.execute_autogen_query({"message": "hi"})
        assert res["status"] == "error"
        assert "not installed" in res["message"]
