import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.adapters.ag2 import AG2AdapterPlugin
from eval_runner.adapters.claude import ClaudeAdapterPlugin
from eval_runner.adapters.common import DualNormalizationHub
from eval_runner.adapters.crewai import CrewAIAdapterPlugin
from eval_runner.adapters.gemini import GeminiAdapterPlugin
from eval_runner.adapters.grok import GrokAdapterPlugin
from eval_runner.adapters.langchain import LangChainAdapterPlugin
from eval_runner.adapters.langgraph import LangGraphAdapterPlugin
from eval_runner.adapters.ollama import OllamaAdapterPlugin
from eval_runner.adapters.openai import OpenAIAdapterPlugin


class MockResponse:
    def __init__(self, status=200, json_data=None):
        self.status = status
        self._json_data = json_data or {}

    async def json(self):
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.parametrize(
    "text, expected_action",
    [
        ("The process is pending", "processing"),
        ("Manual review required (HITL)", "hitl_pause"),
        ("Critical system error occurred", "error"),
        ("Task completed successfully", "final_answer"),
        ("I have decided to deny the loan", "final_answer"),
        ("Just some random text", "final_answer"),
    ],
)
def test_normalization_hub_text_heuristics(text, expected_action):
    assert DualNormalizationHub.normalize_text(text) == expected_action


def test_normalization_hub_json_heuristics():
    res = DualNormalizationHub.normalize({"status": "pending"}, 200)
    assert res == "processing"

    res = DualNormalizationHub.normalize({"state": "hitl"}, 200)
    assert res == "hitl_pause"

    res = DualNormalizationHub.normalize({"outcome": "error"}, 200)
    assert res == "error"

    res = DualNormalizationHub.normalize({"status": "success"}, 500)
    assert res == "error"

    overrides = {"custom_done": "final_answer"}
    res = DualNormalizationHub.normalize({"status": "custom_done"}, 200, overrides=overrides)
    assert res == "final_answer"


def test_gemini_interactions_uses_current_response_format_contract():
    plugin = GeminiAdapterPlugin()

    request = plugin._build_interaction_request(
        payload={
            "task": "hello",
            "response_schema": {"type": "object"},
            "candidate_count": 2,
            "presence_penalty": 0.5,
        },
        model="gemini-test",
        agent=None,
    )

    assert request["response_format"] == {
        "type": "json_schema",
        "json_schema": {"type": "object"},
    }
    assert "response_mime_type" not in request
    assert "candidate_count" not in request.get("generation_config", {})
    assert "presence_penalty" not in request.get("generation_config", {})


def test_gemini_background_interaction_returns_processing_state():
    result = GeminiAdapterPlugin()._normalize_interaction(
        response={"id": "interaction-1", "status": "in_progress"},
        model="gemini-test",
        agent=None,
        vertexai=False,
        project=None,
        location=None,
    )

    assert result["action"] == "processing"
    assert result["metadata"]["interaction_id"] == "interaction-1"


def test_gemini_completed_interaction_remains_a_final_answer():
    result = GeminiAdapterPlugin()._normalize_interaction(
        response={"id": "interaction-2", "status": "completed", "output_text": "done"},
        model="gemini-test",
        agent=None,
        vertexai=False,
        project=None,
        location=None,
    )

    assert result["action"] == "final_answer"


def test_gemini_empty_completed_interaction_fails_closed():
    result = GeminiAdapterPlugin()._normalize_interaction(
        response={"id": "interaction-3", "status": "completed"},
        model="gemini-test",
        agent=None,
        vertexai=False,
        project=None,
        location=None,
    )

    assert result["action"] == "error"


@pytest.mark.asyncio
async def test_gemini_interaction_retry_policy_is_replay_safe():
    plugin = GeminiAdapterPlugin()
    client = MagicMock()
    client.aio.interactions.create = AsyncMock(return_value={"id": "interaction-1"})
    errors = MagicMock()
    errors.APIError = RuntimeError

    await plugin._call_interaction_with_retry(
        client=client,
        genai_errors=errors,
        request={"input": "hello"},
        timeout_seconds=0,
        payload={},
    )
    assert client.aio.interactions.create.await_count == 1

    plugin._consume_interaction_stream = AsyncMock(return_value={"content": "done"})
    await plugin._call_interaction_stream_with_retry(
        client=client,
        genai_errors=errors,
        request={"input": "hello"},
        timeout_seconds=0,
        payload={"idempotency_key": "request-1"},
    )
    assert plugin._consume_interaction_stream.await_count == 1


@pytest.mark.asyncio
async def test_provider_adapter_retry_policy_is_forwarded_to_transport():
    openai = OpenAIAdapterPlugin()
    openai.call_with_retry = AsyncMock(
        return_value=({"choices": [{"message": {"content": "ok"}}]}, {})
    )
    result = await openai.execute_openai_query(
        {"api_key": "key", "task": "hello", "api_mode": "chat_completions"}
    )
    assert result["status"] == "success"
    assert openai.call_with_retry.call_args.kwargs["max_attempts"] == 1

    claude = ClaudeAdapterPlugin()
    claude.call_with_retry = AsyncMock(
        return_value={
            "__claude_response__": {"content": [{"type": "text", "text": "ok"}]},
            "__response_headers__": {},
        }
    )
    result = await claude.execute_claude_query({"api_key": "key", "task": "hello"})
    assert result["status"] == "success"
    assert claude.call_with_retry.call_args.kwargs["max_attempts"] == 1

    grok = GrokAdapterPlugin()
    grok.call_with_retry = AsyncMock(return_value={"choices": [{"message": {"content": "ok"}}]})
    result = await grok.execute_grok_query(
        {"api_key": "key", "task": "hello", "api_mode": "chat_completions"}
    )
    assert result["status"] == "success"
    assert grok.call_with_retry.call_args.kwargs["max_attempts"] == 1

    ollama = OllamaAdapterPlugin()
    ollama.call_with_retry = AsyncMock(return_value={"message": {"content": "ok"}})
    result = await ollama.execute_ollama_query({"task": "hello"})
    assert result["status"] == "success"
    assert ollama.call_with_retry.call_args.kwargs["max_attempts"] == 1


@pytest.mark.asyncio
async def test_ollama_error_messages_and_invalid_json_are_bounded():
    adapter = OllamaAdapterPlugin()
    adapter.call_with_retry = AsyncMock(side_effect=ValueError("x" * 3_000))

    result = await adapter.execute_ollama_query({"task": "hello"})
    assert result["status"] == "error"
    assert len(result["message"].encode("utf-8")) <= 2_024

    response = MagicMock()
    response.json = AsyncMock(side_effect=json.JSONDecodeError("bad", "x", 0))
    response.text = AsyncMock(return_value="invalid")
    with pytest.raises(ValueError, match="Ollama returned invalid JSON"):
        await adapter._read_json_response(response)


@pytest.mark.asyncio
async def test_ollama_uses_the_lifecycle_owned_session():
    adapter = OllamaAdapterPlugin()
    response = MagicMock(status=200, headers={})
    response.json = AsyncMock(return_value={"message": {"content": "ok"}})
    request_context = MagicMock()
    request_context.__aenter__ = AsyncMock(return_value=response)
    request_context.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post.return_value = request_context
    adapter.get_session = AsyncMock(return_value=session)

    result = await adapter.execute_ollama_query({"task": "hello"})

    assert result["status"] == "success"
    adapter.get_session.assert_awaited_once()


@pytest.mark.asyncio
async def test_ollama_session_transport_handles_error_and_streaming():
    adapter = OllamaAdapterPlugin()
    error_response = MagicMock(status=500, headers={}, history=())
    error_response.request_info.real_url = "http://ollama.test/api/chat"
    error_response.text = AsyncMock(return_value="unavailable")
    error_context = MagicMock()
    error_context.__aenter__ = AsyncMock(return_value=error_response)
    error_context.__aexit__ = AsyncMock(return_value=False)
    error_session = MagicMock()
    error_session.post.return_value = error_context
    adapter.get_session = AsyncMock(return_value=error_session)

    result = await adapter.execute_ollama_query({"task": "hello"})
    assert result["status"] == "error"

    stream_response = MagicMock(status=200, headers={})
    stream_context = MagicMock()
    stream_context.__aenter__ = AsyncMock(return_value=stream_response)
    stream_context.__aexit__ = AsyncMock(return_value=False)
    stream_session = MagicMock()
    stream_session.post.return_value = stream_context
    adapter.get_session = AsyncMock(return_value=stream_session)
    adapter._read_streaming_response = AsyncMock(return_value={"message": {"content": "ok"}})

    result = await adapter.execute_ollama_query({"task": "hello", "stream": True})
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_all_adapters_return_action_key():
    adapters = [
        (OpenAIAdapterPlugin(), "execute_openai_query", {"task": "test", "api_key": "sk-123"}),
        (ClaudeAdapterPlugin(), "execute_claude_query", {"task": "test", "api_key": "sk-123"}),
        (GrokAdapterPlugin(), "execute_grok_query", {"task": "test", "api_key": "sk-123"}),
        (OllamaAdapterPlugin(), "execute_ollama_query", {"task": "test"}),
    ]

    for plugin, method_name, payload in adapters:
        with patch("aiohttp.ClientSession.post") as mock_post:
            with patch("os.getenv", return_value="fake-key"):
                if isinstance(plugin, ClaudeAdapterPlugin):
                    json_data = {"content": [{"text": "ok"}]}
                elif isinstance(plugin, OllamaAdapterPlugin):
                    json_data = {"message": {"content": "ok"}}
                else:
                    json_data = {"choices": [{"message": {"content": "ok"}}]}

                mock_post.return_value = MockResponse(json_data=json_data)
                method = getattr(plugin, method_name)

                if isinstance(plugin, OpenAIAdapterPlugin):
                    res = await method(payload, base_url="http://test")
                else:
                    res = await method(payload, url="http://test")

                assert "action" in res
                if res["status"] == "success":
                    assert res["action"] == "final_answer"
                else:
                    assert res["action"] == "error"


@pytest.mark.asyncio
async def test_gemini_adapter_returns_action():
    plugin = GeminiAdapterPlugin()
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_resp = MagicMock()
        mock_resp.text = "ok"
        mock_resp.usage_metadata = None
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

        res = await plugin.execute_gemini_query({"task": "test"})
        assert "action" in res
        if res["status"] == "success":
            assert res["action"] == "final_answer"
        else:
            assert res["action"] == "error"


@pytest.mark.asyncio
async def test_framework_adapters_return_action():
    plugin = LangChainAdapterPlugin()
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value = MockResponse(json_data={"output": "done"})
        res = await plugin.execute_langchain_query({"input": "hi", "url": "http://langserve"})
        assert "action" in res
        if res["status"] == "success":
            assert res["action"] == "final_answer"

    plugin = AG2AdapterPlugin()
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value = MockResponse(json_data={"output": "done"})
        res = await plugin.execute_ag2_query({"message": "hi", "url": "http://ag2"})
        assert "action" in res
        if res["status"] == "success":
            assert res["action"] == "final_answer"

    plugin = CrewAIAdapterPlugin()
    with patch.dict(sys.modules, {"crewai": MagicMock(__version__="1.0")}):
        res = await plugin.execute_crewai_task({"task_id": "test"})
        assert "action" in res
        if res["status"] == "success":
            assert res["action"] == "final_answer"
        else:
            assert res["action"] == "error"

    plugin = LangGraphAdapterPlugin()
    with patch.dict(sys.modules, {"langgraph": MagicMock(__version__="2.0")}):
        res = await plugin.execute_langgraph_node({"node_id": "test"})
        assert "action" in res
        if res["status"] == "success":
            assert res["action"] == "final_answer"
        else:
            assert res["action"] == "error"
