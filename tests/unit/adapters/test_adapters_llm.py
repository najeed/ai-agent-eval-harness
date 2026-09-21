import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.adapters.claude import ClaudeAdapterPlugin
from eval_runner.adapters.gemini import GeminiAdapterPlugin
from eval_runner.adapters.grok import GrokAdapterPlugin
from eval_runner.adapters.langgraph import LangGraphAdapterPlugin
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
    with patch.object(plugin, "_post_json", new_callable=AsyncMock) as post:
        post.return_value = ({"choices": [{"message": {"content": "ok"}}]}, {})
        res = await plugin.execute_openai_query(
            {"task": "hi", "api_key": "test", "api_mode": "chat_completions"},
            base_url="http://test",
        )
        assert res["status"] == "success"
        assert res["action"] == "final_answer"
        assert res["output"] == "ok"


@pytest.mark.asyncio
async def test_openai_adapter_awaitable_json():
    """Test OpenAI query handling when json_data or raise_for_status need await."""
    plugin = OpenAIAdapterPlugin()
    with patch.object(plugin, "_post_json", new_callable=AsyncMock) as post:
        post.return_value = ({"choices": [{"message": {"content": "ok"}}]}, {})
        res = await plugin.execute_openai_query(
            {"task": "hi", "api_key": "test", "api_mode": "chat_completions"},
            base_url="http://test",
        )
        assert res["status"] == "success"
        assert res["output"] == "ok"


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
        assert res["action"] == "final_answer"
        sent_json = post.call_args.args[2]
        assert sent_json["system"] == "be helper"


@pytest.mark.asyncio
async def test_claude_adapter_usage_telemetry():
    """Test Claude adapter telemetry emit when usage is provided."""
    plugin = ClaudeAdapterPlugin()
    payload = {"api_key": "test", "task": "do thing"}
    with patch.object(plugin, "_post", new_callable=AsyncMock) as post:
        post.return_value = {
            "__claude_response__": {
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 10, "output_tokens": 20},
            },
            "__response_headers__": {},
        }
        with patch("eval_runner.adapters.claude.emit") as mock_emit:
            res = await plugin.execute_claude_query(payload, "http://claude")
            assert res["status"] == "success"
            assert mock_emit.called


@pytest.mark.asyncio
async def test_gemini_adapter_vertex_detection():
    plugin = GeminiAdapterPlugin()
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.aio.aclose = AsyncMock()
        plugin._execute_interaction = AsyncMock(
            return_value={"status": "success", "output": "ok", "metadata": {}}
        )

        # Test Vertex detection via URL
        await plugin.execute_gemini_query({"api_key": "test"}, url="http://vertex-api")
        mock_client_cls.assert_called_with(api_key="test", vertexai=True, location="us-central1")


@pytest.mark.asyncio
async def test_gemini_adapter_empty_response():
    """Test Gemini adapter error return when response is empty."""
    plugin = GeminiAdapterPlugin()
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.aio.aclose = AsyncMock()
        plugin._execute_interaction = AsyncMock(
            return_value={"status": "error", "message": "empty"}
        )

        res = await plugin.execute_gemini_query({"api_key": "test"}, url="http://gemini-api")
        assert res["status"] == "error"
        assert res["message"] == "empty"


@pytest.mark.asyncio
async def test_gemini_adapter_usage_telemetry():
    """Test Gemini adapter telemetry emit when usage_metadata is present."""
    plugin = GeminiAdapterPlugin()
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.aio.aclose = AsyncMock()
        plugin._execute_interaction = AsyncMock(
            return_value={"status": "success", "output": "ok", "metadata": {}}
        )

        res = await plugin.execute_gemini_query({"api_key": "test"}, url="http://gemini-api")
        assert res["status"] == "success"
        assert res["output"] == "ok"


@pytest.mark.asyncio
async def test_gemini_adapter_exception():
    """Test Gemini adapter error handling when SDK client throws an exception."""
    plugin = GeminiAdapterPlugin()
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.aio.aclose = AsyncMock()
        plugin._execute_interaction = AsyncMock(side_effect=Exception("SDK crash"))
        res = await plugin.execute_gemini_query({"api_key": "test"}, url="http://gemini-api")
        assert res["status"] == "error"
        assert "SDK crash" in res["message"]


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
async def test_grok_adapter_success_with_usage():
    """Test Grok adapter success path with usage telemetry."""
    plugin = GrokAdapterPlugin()
    payload = {"api_key": "test_grok_key", "task_description": "grok task"}
    with patch.object(plugin, "_request", new_callable=AsyncMock) as request:
        request.return_value = {
            "status": "completed",
            "output_text": "grok output",
            "usage": {"input_tokens": 20, "output_tokens": 30, "total_tokens": 50},
        }
        with patch("eval_runner.adapters.grok.emit") as mock_emit:
            res = await plugin.execute_grok_query(payload)
            assert res["status"] == "success"
            assert res["output"] == "grok output"
            assert mock_emit.called


@pytest.mark.asyncio
async def test_grok_adapter_request_failure():
    """Test Grok adapter exception block when post fails."""
    plugin = GrokAdapterPlugin()
    payload = {"api_key": "test_grok_key", "task": "hello"}
    with patch.object(
        plugin, "_request", new_callable=AsyncMock, side_effect=Exception("network down")
    ):
        res = await plugin.execute_grok_query(payload)
        assert res["status"] == "error"
        assert "Grok request failed" in res["message"]


@pytest.mark.asyncio
async def test_ollama_adapter_translation():
    plugin = OllamaAdapterPlugin()
    payload = {"task": "tell joke"}
    with patch.object(plugin, "call_with_retry", new_callable=AsyncMock) as retry:
        retry.return_value = {
            "message": {"content": "haha"},
            "eval_count": 5,
            "prompt_eval_count": 10,
        }
        with patch("eval_runner.adapters.ollama.emit") as mock_emit:
            res = await plugin.execute_ollama_query(payload, "http://ollama")
            assert res["status"] == "success"
            assert res["action"] == "final_answer"
            assert retry.await_count == 1
            assert mock_emit.called


@pytest.mark.asyncio
async def test_ollama_adapter_failure():
    """Test Ollama adapter failure handling."""
    plugin = OllamaAdapterPlugin()
    with patch.object(
        plugin, "call_with_retry", new_callable=AsyncMock, side_effect=Exception("ollama down")
    ):
        res = await plugin.execute_ollama_query({"task": "hello"}, "http://ollama")
        assert res["status"] == "error"
        assert "ollama down" in res["message"]


# ---------------------------------------------------------------------------
# LangGraphAdapterPlugin Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_langgraph_adapter_missing_sdk():
    """Test LangGraph fails when SDK is not installed and graph_path is provided."""
    plugin = LangGraphAdapterPlugin()
    payload = {"metadata": {"graph_path": "my_module:my_graph"}}

    # Hide langgraph module from sys.modules to simulate missing installation
    with patch.dict(sys.modules, {"langgraph": None}):
        res = await plugin.execute_langgraph_node(payload)
        assert res["status"] == "error"
        assert "not installed" in res["message"]


@pytest.mark.asyncio
async def test_langgraph_adapter_simulation_missing_sdk():
    """Test LangGraph simulation fails when SDK is not installed."""
    plugin = LangGraphAdapterPlugin()
    payload = {}  # No graph_path, triggers simulation path

    with patch.dict(sys.modules, {"langgraph": None}):
        res = await plugin.execute_langgraph_node(payload)
        assert res["status"] == "error"
        assert "not installed" in res["message"]


@pytest.mark.asyncio
async def test_langgraph_adapter_requires_execution_target_when_sdk_is_present():
    """LangGraph must not simulate when no graph target is configured."""
    plugin = LangGraphAdapterPlugin()
    payload = {"node_id": "test_node", "input": {"x": 1}}

    # Mock langgraph import to return true
    mock_langgraph = MagicMock()
    with (
        patch.dict(sys.modules, {"langgraph": mock_langgraph}),
        patch("eval_runner.adapters.common.AESCallbackHandler"),
    ):
        res = await plugin.execute_langgraph_node(payload)
        assert res["status"] == "error"
        assert res["action"] == "error"


@pytest.mark.asyncio
async def test_langgraph_adapter_execution_success():
    """Test LangGraph execution with mock compile module and callbacks."""
    plugin = LangGraphAdapterPlugin()
    payload = {
        "input": {"request": "run"},
        "metadata": {"graph_path": "mock_graph_module:my_graph"},
    }

    class Graph:
        ainvoke = AsyncMock(return_value={"state": "completed"})

    mock_app = Graph()

    with (
        patch.dict(sys.modules, {"langgraph": MagicMock(__version__="test")}),
        patch.object(plugin, "_resolve_execution_target", new_callable=AsyncMock) as resolve,
    ):
        resolve.return_value = mock_app
        res = await plugin.execute_langgraph_node(payload)

    assert res["status"] == "success"
    assert res["output"] == {"state": "completed"}
    assert res["action"] == "final_answer"


@pytest.mark.asyncio
async def test_langgraph_adapter_attribute_or_value_error():
    """Test LangGraph execution with AttributeError/ValueError formatting issues."""
    plugin = LangGraphAdapterPlugin()
    payload = {"metadata": {"graph_path": "mock_graph_module:my_graph"}}

    mock_langgraph = MagicMock()

    with (
        patch.dict(sys.modules, {"langgraph": mock_langgraph}),
        patch("importlib.import_module", side_effect=ValueError("Invalid module format")),
    ):
        res = await plugin.execute_langgraph_node(payload)
        assert res["status"] == "error"
        assert "Invalid module format" in res["message"]
