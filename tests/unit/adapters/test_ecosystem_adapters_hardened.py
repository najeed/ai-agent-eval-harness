from unittest.mock import AsyncMock, patch

import pytest

from eval_runner.adapters.claude import ClaudeAdapterPlugin
from eval_runner.adapters.common import AESCallbackHandler
from eval_runner.adapters.gemini import GeminiAdapterPlugin
from eval_runner.adapters.grok import GrokAdapterPlugin
from eval_runner.adapters.ollama import OllamaAdapterPlugin


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
async def test_claude_adapter_system_prompt_and_task():
    plugin = ClaudeAdapterPlugin()
    payload = {"task": "do thing", "system_prompt": "be helper"}

    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value = MockResponse(json_data={"content": [{"text": "ok"}]})
        res = await plugin.execute_claude_query(payload, "http://claude")

        assert res["status"] == "success"
        args, kwargs = mock_post.call_args
        sent_json = kwargs["json"]
        assert sent_json["system"] == "be helper"
        assert sent_json["messages"][0]["content"] == "do thing"


@pytest.mark.asyncio
async def test_claude_adapter_error_handling():
    plugin = ClaudeAdapterPlugin()
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value = MockResponse(status=403, text_data="Forbidden")
        res = await plugin.execute_claude_query({}, "http://claude")
        assert res["status"] == "error"
        assert "403" in res["message"]


@pytest.mark.asyncio
async def test_gemini_adapter_vertex_detection():
    plugin = GeminiAdapterPlugin()
    # Mock the SDK client
    with patch("google.genai.Client") as mock_client_cls:
        # Test Vertex detection via URL
        await plugin.execute_gemini_query({}, url="http://vertex-api")
        mock_client_cls.assert_called_with(api_key=None, vertexai=True)

        # Test Vertex detection via metadata
        await plugin.execute_gemini_query({"metadata": {"vertexai": True}}, url="http://standard")
        mock_client_cls.assert_called_with(api_key=None, vertexai=True)


@pytest.mark.asyncio
async def test_gemini_adapter_full_messages():
    plugin = GeminiAdapterPlugin()
    payload = {
        "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    }
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.aio.models.generate_content = AsyncMock()

        await plugin.execute_gemini_query(payload)
        args, kwargs = mock_client.aio.models.generate_content.call_args
        contents = kwargs["contents"]
        assert len(contents) == 2
        assert contents[0].role == "user"
        assert contents[1].role == "model"


@pytest.mark.asyncio
async def test_grok_adapter_missing_key():
    plugin = GrokAdapterPlugin()
    with patch("os.getenv", return_value=None):
        res = await plugin.execute_grok_query({})
        assert res["status"] == "error"
        assert "key missing" in res["message"]


@pytest.mark.asyncio
async def test_ollama_adapter_translation():
    plugin = OllamaAdapterPlugin()
    payload = {"task": "tell joke"}
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value = MockResponse(json_data={"message": {"content": "haha"}})
        res = await plugin.execute_ollama_query(payload, "http://ollama")

        assert res["status"] == "success"
        sent_json = mock_post.call_args[1]["json"]
        assert sent_json["messages"][0]["content"] == "tell joke"


def test_common_telemetry_hashing_error():
    # Trigger TypeError in json.dumps by passing something non-serializable
    handler = AESCallbackHandler("test", "id123")
    with patch("eval_runner.adapters.common.emit") as mock_emit:
        handler.on_chain_start({}, {"bad": object()})
        assert mock_emit.called
        event_data = mock_emit.call_args[0][1]
        assert event_data["state_hash"] == "error_hashing"


def test_common_telemetry_node_discovery():
    handler = AESCallbackHandler("test", "id123")
    with patch("eval_runner.adapters.common.emit") as mock_emit:
        # Success path
        handler.on_node_start({"id": ["root", "node1"]}, {})
        assert mock_emit.call_args[0][1]["node_id"] == "node1"

        # Missing ID path
        handler.on_node_start({}, {})
        assert mock_emit.call_args[0][1]["node_id"] == "unknown"

        # Non-dict path
        handler.on_node_start("not_a_dict", {})
        assert mock_emit.call_args[0][1]["node_id"] == "unknown"
