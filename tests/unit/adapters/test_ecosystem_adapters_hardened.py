from unittest.mock import AsyncMock, MagicMock, patch

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
async def test_claude_adapter_system_prompt_and_task():
    plugin = ClaudeAdapterPlugin()
    payload = {"api_key": "test", "task": "do thing", "system_prompt": "be helper"}

    with patch.object(plugin, "_post", new_callable=AsyncMock) as post:
        post.return_value = {
            "__claude_response__": {"content": [{"type": "text", "text": "ok"}]},
            "__response_headers__": {},
        }
        res = await plugin.execute_claude_query(payload, "http://claude")

        assert res["status"] == "success"
        sent_json = post.call_args.args[2]
        assert sent_json["system"] == "be helper"
        assert sent_json["messages"][0]["content"] == "do thing"


@pytest.mark.asyncio
async def test_claude_adapter_error_handling():
    plugin = ClaudeAdapterPlugin()
    res = await plugin.execute_claude_query({}, "http://claude")
    assert res["status"] == "error"
    assert "received no input" in res["message"]


@pytest.mark.asyncio
async def test_gemini_adapter_vertex_detection():
    plugin = GeminiAdapterPlugin()
    # Mock the SDK client
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_resp = MagicMock()
        mock_resp.text = "ok"
        mock_resp.usage_metadata = None
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)
        # Test Vertex detection via URL
        await plugin.execute_gemini_query({}, url="http://vertex-api")
        mock_client_cls.assert_called_with(vertexai=True, location="us-central1")

        # Test Vertex detection via metadata
        await plugin.execute_gemini_query({"metadata": {"vertexai": True}}, url="http://standard")
        mock_client_cls.assert_called_with(vertexai=True, location="us-central1")


@pytest.mark.asyncio
async def test_gemini_adapter_full_messages():
    plugin = GeminiAdapterPlugin()
    payload = {
        "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    }
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.aio.interactions.create = AsyncMock(
            return_value={"id": "interaction-1", "status": "completed", "output_text": "hello"}
        )

        result = await plugin.execute_gemini_query({"api_key": "test", **payload})
        assert result["status"] == "success"
        assert mock_client.aio.interactions.create.called


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
    with patch.object(plugin, "call_with_retry", new_callable=AsyncMock) as retry:
        retry.return_value = {"message": {"content": "haha"}}
        res = await plugin.execute_ollama_query(payload, "http://ollama")

        assert res["status"] == "success"
        assert retry.await_count == 1


def test_common_telemetry_hashing_error():
    # Trigger TypeError in json.dumps by passing something non-serializable
    handler = AESCallbackHandler("test", "id123")
    with patch("eval_runner.adapters.common.emit") as mock_emit:
        handler.on_chain_start({}, {"bad": object()})
        assert mock_emit.called
        event_data = mock_emit.call_args[0][1]
        assert len(event_data["state_hash"]) == 64


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
