from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
async def test_openai_adapter_success():
    plugin = OpenAIAdapterPlugin()
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value = MockResponse(
            json_data={"choices": [{"message": {"content": "ok"}}]}
        )
        res = await plugin.execute_openai_query(
            {"task": "hi", "api_key": "test"}, base_url="http://test"
        )
        assert res["status"] == "success"
        assert res["action"] == "final_answer"
        assert res["output"] == "ok"


@pytest.mark.asyncio
async def test_claude_adapter_system_prompt_and_task():
    plugin = ClaudeAdapterPlugin()
    payload = {"task": "do thing", "system_prompt": "be helper"}
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value = MockResponse(json_data={"content": [{"text": "ok"}]})
        res = await plugin.execute_claude_query(payload, "http://claude")
        assert res["status"] == "success"
        assert res["action"] == "final_answer"
        sent_json = mock_post.call_args[1]["json"]
        assert sent_json["system"] == "be helper"


@pytest.mark.asyncio
async def test_gemini_adapter_vertex_detection():
    plugin = GeminiAdapterPlugin()
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_resp = MagicMock()
        mock_resp.text = "ok"
        mock_resp.usage_metadata = None
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

        # Test Vertex detection via URL
        await plugin.execute_gemini_query({}, url="http://vertex-api")
        mock_client_cls.assert_called_with(api_key=None, vertexai=True)


@pytest.mark.asyncio
async def test_grok_adapter_error_reporting():
    plugin = GrokAdapterPlugin()
    # Missing API key path
    with patch("os.getenv", return_value=None):
        res = await plugin.execute_grok_query({})
        assert res["status"] == "error"
        assert res["action"] == "error"
        assert "key missing" in res["message"]


@pytest.mark.asyncio
async def test_ollama_adapter_translation():
    plugin = OllamaAdapterPlugin()
    payload = {"task": "tell joke"}
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value = MockResponse(json_data={"message": {"content": "haha"}})
        res = await plugin.execute_ollama_query(payload, "http://ollama")
        assert res["status"] == "success"
        assert res["action"] == "final_answer"
        sent_json = mock_post.call_args[1]["json"]
        assert sent_json["messages"][0]["content"] == "tell joke"
