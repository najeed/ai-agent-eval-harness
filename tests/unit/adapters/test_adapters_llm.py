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
async def test_openai_adapter_awaitable_json():
    """Test OpenAI query handling when json_data or raise_for_status need await."""
    plugin = OpenAIAdapterPlugin()
    with patch("aiohttp.ClientSession.post") as mock_post:
        # Mocking awaitable json and raise_for_status
        async def mock_json():
            return {"choices": [{"message": {"content": "ok"}}]}

        mock_resp = MockResponse(status=200)
        mock_resp.json = mock_json

        mock_post.return_value = mock_resp
        res = await plugin.execute_openai_query(
            {"task": "hi", "api_key": "test"}, base_url="http://test"
        )
        assert res["status"] == "success"
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
async def test_claude_adapter_usage_telemetry():
    """Test Claude adapter telemetry emit when usage is provided."""
    plugin = ClaudeAdapterPlugin()
    payload = {"task": "do thing"}
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value = MockResponse(
            json_data={
                "content": [{"text": "ok"}],
                "usage": {"input_tokens": 10, "output_tokens": 20},
            }
        )
        with patch("eval_runner.adapters.claude.emit") as mock_emit:
            res = await plugin.execute_claude_query(payload, "http://claude")
            assert res["status"] == "success"
            mock_emit.assert_called_with(
                "metric_update",
                {
                    "adapter": "claude",
                    "tokens": 30,
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                },
            )


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
async def test_gemini_adapter_empty_response():
    """Test Gemini adapter error return when response is empty."""
    plugin = GeminiAdapterPlugin()
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_resp = MagicMock()
        mock_resp.text = ""
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

        res = await plugin.execute_gemini_query({}, url="http://gemini-api")
        assert res["status"] == "error"
        assert "Empty or invalid response" in res["message"]


@pytest.mark.asyncio
async def test_gemini_adapter_usage_telemetry():
    """Test Gemini adapter telemetry emit when usage_metadata is present."""
    plugin = GeminiAdapterPlugin()
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_resp = MagicMock()
        mock_resp.text = "ok"
        mock_usage = MagicMock()
        mock_usage.total_token_count = 100
        mock_usage.prompt_token_count = 40
        mock_usage.candidates_token_count = 60
        mock_resp.usage_metadata = mock_usage
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

        with patch("eval_runner.adapters.gemini.emit") as mock_emit:
            res = await plugin.execute_gemini_query({}, url="http://gemini-api")
            assert res["status"] == "success"
            mock_emit.assert_called_with(
                "metric_update",
                {
                    "adapter": "gemini",
                    "tokens": 100,
                    "prompt_tokens": 40,
                    "completion_tokens": 60,
                },
            )


@pytest.mark.asyncio
async def test_gemini_adapter_exception():
    """Test Gemini adapter error handling when SDK client throws an exception."""
    plugin = GeminiAdapterPlugin()
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        # Make the async generate_content throw an Exception
        mock_client.aio.models.generate_content = AsyncMock(side_effect=Exception("SDK crash"))
        res = await plugin.execute_gemini_query({}, url="http://gemini-api")
        assert res["status"] == "error"
        assert "Gemini SDK Error: SDK crash" in res["message"]


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
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value = MockResponse(
            json_data={
                "choices": [{"message": {"content": "grok output"}}],
                "usage": {"total_tokens": 50, "prompt_tokens": 20, "completion_tokens": 30},
            }
        )
        with patch("eval_runner.adapters.grok.emit") as mock_emit:
            res = await plugin.execute_grok_query(payload)
            assert res["status"] == "success"
            assert res["output"] == "grok output"
            mock_emit.assert_called_with(
                "metric_update",
                {
                    "adapter": "grok",
                    "tokens": 50,
                    "prompt_tokens": 20,
                    "completion_tokens": 30,
                },
            )


@pytest.mark.asyncio
async def test_grok_adapter_request_failure():
    """Test Grok adapter exception block when post fails."""
    plugin = GrokAdapterPlugin()
    payload = {"api_key": "test_grok_key"}
    with patch("aiohttp.ClientSession.post", side_effect=Exception("network down")):
        res = await plugin.execute_grok_query(payload)
        assert res["status"] == "error"
        assert "Grok request failed" in res["message"]


@pytest.mark.asyncio
async def test_ollama_adapter_translation():
    plugin = OllamaAdapterPlugin()
    payload = {"task": "tell joke"}
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value = MockResponse(
            json_data={"message": {"content": "haha"}, "eval_count": 5, "prompt_eval_count": 10}
        )
        with patch("eval_runner.adapters.ollama.emit") as mock_emit:
            res = await plugin.execute_ollama_query(payload, "http://ollama")
            assert res["status"] == "success"
            assert res["action"] == "final_answer"
            sent_json = mock_post.call_args[1]["json"]
            assert sent_json["messages"][0]["content"] == "tell joke"
            mock_emit.assert_called_with(
                "metric_update",
                {
                    "adapter": "ollama",
                    "tokens": 15,
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                },
            )


@pytest.mark.asyncio
async def test_ollama_adapter_failure():
    """Test Ollama adapter failure handling."""
    plugin = OllamaAdapterPlugin()
    with patch("aiohttp.ClientSession.post", side_effect=Exception("ollama down")):
        res = await plugin.execute_ollama_query({}, "http://ollama")
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
async def test_langgraph_adapter_simulation_success():
    """Test LangGraph simulation success when SDK is present."""
    plugin = LangGraphAdapterPlugin()
    payload = {"node_id": "test_node", "input": {"x": 1}}

    # Mock langgraph import to return true
    mock_langgraph = MagicMock()
    with (
        patch.dict(sys.modules, {"langgraph": mock_langgraph}),
        patch("eval_runner.adapters.common.AESCallbackHandler"),
    ):
        res = await plugin.execute_langgraph_node(payload)
        assert res["status"] == "success"
        assert "test_node" in res["output"]
        assert res["metadata"]["mode"] == "simulated"


@pytest.mark.asyncio
async def test_langgraph_adapter_execution_success():
    """Test LangGraph execution with mock compile module and callbacks."""
    plugin = LangGraphAdapterPlugin()
    payload = {"metadata": {"graph_path": "mock_graph_module:my_graph"}}

    mock_app = MagicMock()
    mock_app.ainvoke = AsyncMock(return_value={"state": "completed"})

    mock_module = MagicMock()
    mock_module.my_graph = mock_app

    mock_langgraph = MagicMock()

    with (
        patch.dict(sys.modules, {"langgraph": mock_langgraph, "mock_graph_module": mock_module}),
        patch("importlib.import_module", return_value=mock_module),
    ):
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
