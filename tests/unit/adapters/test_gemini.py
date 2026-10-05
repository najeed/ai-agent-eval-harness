import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.adapters.gemini import GeminiAdapterPlugin


class _Types:
    class GenerateContentConfig:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class HttpOptions:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs


class _AsyncEvents:
    def __init__(self, events: list[object]) -> None:
        self._events = events

    def __aiter__(self):
        self._iterator = iter(self._events)
        return self

    async def __anext__(self) -> object:
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def test_gemini_configuration_resolution_and_request_options() -> None:
    adapter = GeminiAdapterPlugin()
    payload = {
        "generation_config": {"temperature": 0.1},
        "top_p": 0.5,
        "thinking_config": {"include_thoughts": True},
        "response_json_schema": {"type": "object"},
        "api_version": "v1beta",
        "http_timeout_ms": 2500,
        "extra_headers": {"X-Test": 3},
        "extra_query": {"alt": "json"},
        "extra_body": {"trace": True},
    }
    assert adapter._build_generation_config(payload) == {
        "temperature": 0.1,
        "top_p": 0.5,
        "include_thoughts": True,
    }
    config = adapter._build_generate_content_config(
        payload={"temperature": 0.2, "response_mime_type": "application/json"},
        types=_Types,
        system_instruction="rules",
    )
    assert config.kwargs["system_instruction"] == "rules"
    assert config.kwargs["temperature"] == 0.2
    http_options = adapter._build_http_options(payload, types=_Types)
    assert http_options.kwargs["headers"] == {"X-Test": "3"}
    assert http_options.kwargs["extra_query"] == {"alt": "json"}
    assert adapter._resolve_response_format(payload)["type"] == "json_schema"
    assert adapter._resolve_api_mode({"api_mode": "legacy"}) == "generate_content"
    assert adapter._resolve_vertex_mode({"deployment": "vertex"}, None)
    assert adapter._resolve_stream({"stream": 1})
    assert adapter._resolve_timeout({"timeout": "bad"}) == 30.0
    assert adapter._resolve_max_attempts({"max_retries": 2}) == 3
    with pytest.raises(ValueError, match="Unsupported"):
        adapter._resolve_api_mode({"api_mode": "unknown"})


def test_gemini_interaction_input_conversion_preserves_history_and_media() -> None:
    adapter = GeminiAdapterPlugin()
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "assistant", "content": "prior"},
        {"role": "user", "content": [{"inline_data": {"data": "abc", "mime_type": "image/png"}}]},
    ]
    converted = adapter._build_interaction_input({"messages": messages})
    assert converted[0] == {"type": "text", "text": "[SYSTEM]\nrules"}
    assert converted[1] == {"type": "text", "text": "[ASSISTANT]\nprior"}
    assert converted[2] == {"type": "image", "data": "abc", "mime_type": "image/png"}
    latest_only = adapter._build_interaction_input(
        {"messages": messages, "previous_interaction_id": "i"}
    )
    assert latest_only == [{"type": "image", "data": "abc", "mime_type": "image/png"}]
    assert adapter._normalize_interaction_part({"file_data": {"file_uri": "file://x"}}) == {
        "type": "file",
        "uri": "file://x",
    }
    function_part = adapter._normalize_interaction_part(
        {"function_call": {"name": "lookup", "args": {"q": "x"}}}
    )
    assert function_part == {
        "type": "function_call",
        "name": "lookup",
        "arguments": {"q": "x"},
        "id": None,
    }
    assert adapter._build_interaction_input({"task": {"text": "object"}}) == {
        "type": "text",
        "text": "object",
    }
    with pytest.raises(TypeError, match="must be a list"):
        adapter._build_interaction_input({"messages": "bad"})


@pytest.mark.asyncio
async def test_gemini_retry_configuration_and_iterator_contracts() -> None:
    adapter = GeminiAdapterPlugin()
    assert adapter._resolve_max_attempts({"max_attempts": "bad"}) == adapter.DEFAULT_MAX_RETRIES + 1
    assert adapter._resolve_backoff_base({"retry_delay": "bad"}) == adapter.DEFAULT_BACKOFF_BASE
    assert adapter._resolve_backoff_max({"max_retry_delay": "bad"}) == adapter.DEFAULT_BACKOFF_MAX
    assert [item async for item in adapter._as_async_iterator([1, 2])] == [1, 2]
    with pytest.raises(TypeError, match="did not return an iterable"):
        _ = [item async for item in adapter._as_async_iterator(object())]
    with patch("eval_runner.adapters.gemini.asyncio.sleep", new=AsyncMock()) as sleep:
        await adapter._retry_sleep(attempt=0, payload={"max_retry_delay": 1}, retry_after=2)
    sleep.assert_awaited_once_with(1.0)


def test_gemini_generate_content_conversion_and_extraction_contracts() -> None:
    adapter = GeminiAdapterPlugin()
    contents, system = adapter._build_generate_content_contents(
        {
            "messages": [
                {"role": "system", "content": "rules"},
                {"role": "assistant", "content": "prior"},
                {"role": "user", "content": [{"type": "image", "url": "file://image"}]},
            ]
        }
    )
    assert system == "rules"
    assert contents[0] == {"role": "model", "parts": [{"text": "prior"}]}
    assert contents[1]["parts"] == [{"file_data": {"file_uri": "file://image"}}]
    tool_part = adapter._normalize_generate_content_part(
        {"type": "tool_call", "name": "lookup", "arguments": {"q": "x"}}
    )
    assert tool_part == [{"function_call": {"name": "lookup", "args": {"q": "x"}}}]
    response = {
        "candidates": [
            {
                "finish_reason": "STOP",
                "safety_ratings": [{"category": "safe"}],
                "content": {
                    "parts": [
                        {"text": "candidate"},
                        {"function_call": {"name": "lookup", "args": {"q": 1}}},
                    ]
                },
            }
        ]
    }
    assert adapter._extract_generate_content_text(response) == "candidate"
    assert adapter._extract_generate_content_function_calls(response) == [
        {"id": None, "name": "lookup", "arguments": {"q": 1}}
    ]
    assert adapter._extract_generate_content_candidates(response) == [
        {"finish_reason": "STOP", "safety_ratings": [{"category": "safe"}]}
    ]


@pytest.mark.asyncio
async def test_gemini_interactions_direct_call_retries_transient_api_error() -> None:
    adapter = GeminiAdapterPlugin()

    class APIError(Exception):
        status_code = 429

    create = AsyncMock(side_effect=[APIError("retry"), {"output_text": "CERTIFIED"}])
    client = SimpleNamespace(aio=SimpleNamespace(interactions=SimpleNamespace(create=create)))
    with patch.object(adapter, "_retry_sleep", new=AsyncMock()) as retry_sleep:
        response = await adapter._call_interaction_with_retry(
            client=client,
            genai_errors=SimpleNamespace(APIError=APIError),
            request={"model": "gemini-test", "input": "hello"},
            timeout_seconds=1,
            payload={"idempotency_key": "replay-safe"},
        )
    assert response == {"output_text": "CERTIFIED"}
    retry_sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_gemini_legacy_direct_call_and_stream_materialization() -> None:
    adapter = GeminiAdapterPlugin()
    generate_content = AsyncMock(return_value=SimpleNamespace(text="LEGACY"))
    generate_stream = AsyncMock(return_value=_AsyncEvents([{"text": "one"}, {"text": "two"}]))
    models = SimpleNamespace(
        generate_content=generate_content,
        generate_content_stream=generate_stream,
    )
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    errors = SimpleNamespace(APIError=RuntimeError)
    response = await adapter._call_generate_content_with_retry(
        client=client,
        genai_errors=errors,
        request={"model": "gemini-test"},
        timeout_seconds=1,
        payload={"max_attempts": 1},
    )
    assert response.text == "LEGACY"
    chunks = await adapter._call_generate_content_stream_with_retry(
        client=client,
        genai_errors=errors,
        request={"model": "gemini-test"},
        timeout_seconds=1,
        payload={"max_attempts": 1},
    )
    assert chunks == [{"text": "one"}, {"text": "two"}]


def test_gemini_provider_error_metadata_and_redaction() -> None:
    adapter = GeminiAdapterPlugin()
    assert adapter._extract_status_code(SimpleNamespace(code="503")) == 503
    assert (
        adapter._extract_retry_after(
            SimpleNamespace(raw_response=SimpleNamespace(headers={"Retry-After": "1.5"}))
        )
        == 1.5
    )
    assert adapter._safe_error_message(RuntimeError("api_key=secret")) == (
        "Gemini request failed; provider returned a credential-sensitive error."
    )


def test_gemini_sdk_serialization_stream_summary_and_usage_telemetry() -> None:
    class Model:
        def model_dump(self) -> dict[str, object]:
            return {"value": {"nested": 1}}

    adapter = GeminiAdapterPlugin()
    assert adapter._serialize(Model()) == {"value": {"nested": 1}}
    assert adapter._serialize({"items": (1, 2)}) == {"items": [1, 2]}
    assert adapter._summarize_stream_event(
        {
            "event_type": "delta",
            "step": {"type": "model_output"},
            "delta": {"type": "text"},
            "status": "done",
        }
    ) == {
        "event_type": "delta",
        "step_type": "model_output",
        "delta_type": "text",
        "status": "done",
    }
    with patch("eval_runner.adapters.gemini.emit") as emit:
        adapter._emit_usage({"usage": {"input_tokens": 2, "output_tokens": 3}})
    emit.assert_called_once()


def test_gemini_interaction_extraction_and_function_call_normalization() -> None:
    adapter = GeminiAdapterPlugin()
    response = {
        "steps": [
            {"type": "model_output", "content": [{"type": "text", "text": "hello"}]},
            {"type": "function_call", "name": "lookup", "arguments": {"q": "x"}, "id": "call-1"},
        ],
        "outputs": [{"type": "function_call", "name": "second", "args": {"n": 2}}],
        "response_metadata": {"usage": {"input_tokens": 2}},
    }
    assert adapter._extract_interaction_text(response) == "hello"
    calls = adapter._extract_function_calls_from_interaction(response)
    assert [call["name"] for call in calls] == ["lookup", "second"]
    assert adapter._extract_interaction_usage(response) == {"input_tokens": 2}
    assert adapter._extract_step_text({"parts": [{"type": "output_text", "text": "part"}]}) == [
        "part"
    ]
    assert adapter._normalize_function_call({"name": "lookup", "arguments": '{"q":1}'}) == {
        "name": "lookup",
        "arguments": '{"q":1}',
        "id": None,
    }
    assert adapter._value(SimpleNamespace(value="x"), "value") == "x"
    assert adapter._serialize(SimpleNamespace(value="x")) == {"value": "x"}


def test_gemini_response_error_helpers_are_fail_closed() -> None:
    adapter = GeminiAdapterPlugin()
    assert adapter._error("bad", metadata={"model": "gemini"})["status"] == "error"
    assert adapter._extract_status_code(SimpleNamespace(status_code=429)) == 429
    assert adapter._extract_retry_after(SimpleNamespace(headers={"Retry-After": "2"})) == 2.0
    assert "problem" in adapter._safe_error_message(RuntimeError("problem"))
    assert adapter._normalize_tools({"function_declarations": []}) == {"function_declarations": []}


@pytest.mark.asyncio
async def test_gemini_interaction_and_legacy_execution_paths() -> None:
    adapter = GeminiAdapterPlugin()
    client = SimpleNamespace()
    errors = SimpleNamespace(APIError=RuntimeError)
    interaction_response = {
        "output_text": "CERTIFIED",
        "id": "interaction-1",
        "model": "gemini-test",
    }
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            adapter,
            "_call_interaction_with_retry",
            AsyncMock(return_value=interaction_response),
        )
        result = await adapter._execute_interaction(
            client=client,
            genai_errors=errors,
            types=_Types,
            payload={"task": "hello"},
            model="gemini-test",
            agent=None,
            vertexai=False,
            project=None,
            location=None,
            timeout_seconds=1,
        )
    assert result["status"] == "success"
    assert result["output"] == "CERTIFIED"

    legacy_response = SimpleNamespace(text="LEGACY")
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            adapter,
            "_call_generate_content_with_retry",
            AsyncMock(return_value=legacy_response),
        )
        result = await adapter._execute_generate_content(
            client=client,
            genai_errors=errors,
            types=_Types,
            payload={"task": "hello"},
            model="gemini-test",
            vertexai=False,
            project=None,
            location=None,
            timeout_seconds=1,
        )
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_gemini_interaction_stream_consumption_materializes_text_tools_and_usage() -> None:
    adapter = GeminiAdapterPlugin()
    final_interaction = {
        "id": "interaction-final",
        "model": "gemini-test",
        "output_text": "final text",
        "usage": {"input_tokens": 2},
        "steps": [{"type": "function_call", "name": "lookup", "arguments": {"q": "x"}}],
    }
    events = _AsyncEvents(
        [
            {
                "event_type": "delta",
                "delta": {"type": "text", "text": "partial"},
                "status": "in_progress",
            },
            {
                "event_type": "delta",
                "delta": {"type": "function_call", "name": "lookup", "arguments": {"q": "x"}},
            },
            {"event_type": "completed", "interaction": final_interaction, "status": "completed"},
        ]
    )
    create = AsyncMock(return_value=events)
    client = SimpleNamespace(aio=SimpleNamespace(interactions=SimpleNamespace(create=create)))
    result = await adapter._consume_interaction_stream(
        client=client,
        request={"model": "gemini-test", "input": "hello"},
        timeout_seconds=1,
    )
    assert result["text"] == "final text"
    assert result["interaction_id"] == "interaction-final"
    assert result["function_calls"] == [{"id": None, "name": "lookup", "arguments": {"q": "x"}}]
    assert result["usage"] == {"input_tokens": 2}


def test_gemini_normalization_contracts_for_text_tools_processing_and_legacy_chunks() -> None:
    adapter = GeminiAdapterPlugin()
    common = dict(model="gemini-test", agent=None, vertexai=False, project=None, location=None)
    text_result = adapter._normalize_interaction(
        response={"output_text": "hello", "id": "i"}, **common
    )
    assert text_result["output"] == "hello"
    processing = adapter._normalize_interaction(response={"status": "queued"}, **common)
    assert processing["action"] == "processing"
    tool = adapter._normalize_interaction(
        response={"steps": [{"type": "function_call", "name": "lookup", "arguments": {"q": "x"}}]},
        **common,
    )
    assert tool["action"] == "call_tool"
    streamed = adapter._normalize_streamed_interaction(
        response={"text": "stream", "usage": {"input_tokens": 1}, "model_version": "v"},
        **common,
    )
    assert streamed["metadata"]["model_version"] == "v"
    legacy = adapter._normalize_generate_content_response(
        response={"text": "legacy", "usage_metadata": {"total_token_count": 2}, "response_id": "r"},
        model="gemini-test",
        vertexai=False,
        project=None,
        location=None,
    )
    assert legacy["metadata"]["response_id"] == "r"
    chunks = adapter._normalize_generate_content_chunks(
        response=[{"text": "one"}, {"text": "two"}],
        model="gemini-test",
        vertexai=False,
        project=None,
        location=None,
    )
    assert chunks["output"] == "onetwo"


def test_gemini_interactions_reject_custom_safety_settings() -> None:
    adapter = GeminiAdapterPlugin()

    with pytest.raises(ValueError, match="does not support custom safety_settings"):
        adapter._build_interaction_request(
            payload={"task": "CERTIFIED", "safety_settings": [{"category": "HARM_CATEGORY"}]},
            model="gemini-test",
            agent=None,
        )


def test_gemini_interaction_request_and_message_edge_contracts() -> None:
    adapter = GeminiAdapterPlugin()
    request = adapter._build_interaction_request(
        payload={
            "input": "explicit",
            "previous_interaction_id": "previous",
            "system_instruction": "rules",
            "tools": [{"function_declarations": []}],
            "environment": {"a": 1},
            "agent_config": {"b": 2},
            "response_mime_type": "application/json",
            "response_modalities": ["TEXT"],
            "temperature": 0.1,
            "store": 1,
            "background": 0,
            "service_tier": "default",
            "labels": {"x": "y"},
            "webhook_config": {"url": "https://example.test"},
            "extra_headers": {"X": 1},
            "extra_query": {"alt": "json"},
            "extra_body": {"trace": True},
            "api_version": "v1beta",
            "timeout": 2,
        },
        model=None,
        agent="agent",
    )
    assert request["agent"] == "agent"
    assert request["previous_interaction_id"] == "previous"
    assert request["generation_config"]["temperature"] == 0.1
    assert request["extra_headers"] == {"X": "1"}
    assert adapter._build_interaction_input({"contents": [{"type": "text", "text": "x"}]})
    assert adapter._latest_user_input([{"role": "assistant", "content": "x"}, "latest"]) == "latest"
    assert (
        adapter._messages_to_interaction_input([1, {"role": "user", "content": None}])[0]["text"]
        == "1"
    )
    assert adapter._content_to_text_parts(["x", 1])[1]["text"] == "1"
    assert adapter._normalize_interaction_part({}) is None


@pytest.mark.asyncio
async def test_gemini_interaction_stream_collects_deltas_without_final_interaction() -> None:
    adapter = GeminiAdapterPlugin()
    events = _AsyncEvents(
        [
            {"event_type": "delta", "delta": {"type": "text", "text": "one"}, "status": "running"},
            {
                "event_type": "delta",
                "delta": {"type": "function_call", "name": "lookup", "arguments": {"q": 1}},
            },
            {"event_type": "delta", "delta": {"type": "thought_summary"}},
        ]
    )
    client = SimpleNamespace(
        aio=SimpleNamespace(interactions=SimpleNamespace(create=AsyncMock(return_value=events)))
    )
    result = await adapter._consume_interaction_stream(
        client=client, request={"model": "gemini-test"}, timeout_seconds=1
    )
    assert result["text"] == "one"
    assert result["function_calls"][0]["name"] == "lookup"
    assert result["finish_reasons"] == ["running"]


@pytest.mark.asyncio
async def test_gemini_legacy_execution_and_content_conversion_edge_contracts() -> None:
    adapter = GeminiAdapterPlugin()
    assert (
        adapter._normalize_interaction_part(
            {"inline_data": {"data": "x", "mimeType": "image/png"}}
        )["mime_type"]
        == "image/png"
    )
    assert (
        adapter._normalize_interaction_part(
            {"function_response": {"name": "tool", "response": {"ok": True}}}
        )["type"]
        == "function_result"
    )
    assert adapter._coerce_interaction_input([{"type": "text", "text": "x"}])[0]["type"] == "text"
    assert adapter._normalize_generate_content_part({"type": "image", "image": {"url": "file://x"}})
    assert adapter._normalize_generate_content_part({"data": "x", "mime_type": "image/png"})
    assert adapter._normalize_generate_content_part({"type": "function_response", "name": "tool"})
    client = SimpleNamespace()
    errors = SimpleNamespace(APIError=RuntimeError)
    response = {"text": "legacy"}
    with patch.object(
        adapter, "_call_generate_content_with_retry", new=AsyncMock(return_value=response)
    ):
        result = await adapter._execute_generate_content(
            client=client,
            genai_errors=errors,
            types=_Types,
            payload={"task": "hello"},
            model="gemini-test",
            vertexai=False,
            project=None,
            location=None,
            timeout_seconds=1,
        )
    assert result["output"] == "legacy"
    with patch.object(
        adapter,
        "_call_generate_content_stream_with_retry",
        new=AsyncMock(return_value=[{"text": "stream"}]),
    ):
        result = await adapter._execute_generate_content(
            client=client,
            genai_errors=errors,
            types=_Types,
            payload={"task": "hello", "stream": True},
            model="gemini-test",
            vertexai=False,
            project=None,
            location=None,
            timeout_seconds=1,
        )
    assert result["output"] == "stream"


@pytest.mark.asyncio
async def test_gemini_interaction_stream_retry_and_execution_contracts() -> None:
    adapter = GeminiAdapterPlugin()

    class APIError(Exception):
        status_code = 429

    consume = AsyncMock(side_effect=APIError("retry"))
    with patch.object(adapter, "_consume_interaction_stream", new=consume):
        with pytest.raises(APIError):
            await adapter._call_interaction_stream_with_retry(
                client=SimpleNamespace(),
                genai_errors=SimpleNamespace(APIError=APIError),
                request={"model": "gemini-test"},
                timeout_seconds=1,
                payload={"idempotency_key": "replay-safe"},
            )
    assert consume.await_count == 1

    common = dict(
        client=SimpleNamespace(),
        genai_errors=SimpleNamespace(APIError=RuntimeError),
        types=_Types,
        payload={"task": "hello", "stream": True},
        model="gemini-test",
        agent=None,
        vertexai=False,
        project=None,
        location=None,
        timeout_seconds=1,
    )
    with patch.object(
        adapter,
        "_call_interaction_stream_with_retry",
        new=AsyncMock(return_value={"text": "stream"}),
    ):
        result = await adapter._execute_interaction(**common)
    assert result["output"] == "stream"


def test_gemini_normalization_error_tool_and_metadata_contracts() -> None:
    adapter = GeminiAdapterPlugin()
    common = dict(
        model="gemini-test", agent="agent", vertexai=True, project="project", location="location"
    )
    assert adapter._normalize_interaction(response=None, **common)["status"] == "error"
    multi = adapter._normalize_interaction(
        response={
            "id": "i",
            "model_version": "v",
            "parsed": {"ok": True},
            "steps": [
                {"type": "function_call", "name": "one", "arguments": {}},
                {"type": "function_call", "name": "two", "arguments": {}},
            ],
        },
        **common,
    )
    assert multi["action"] == "call_multiple_tools"
    assert multi["metadata"]["parsed"] == {"ok": True}
    assert adapter._normalize_streamed_interaction(response={}, **common)["status"] == "error"
    streamed = adapter._normalize_streamed_interaction(
        response={"function_calls": [{"name": "tool"}, {"name": "other"}], "model_version": "v"},
        **common,
    )
    assert streamed["action"] == "call_multiple_tools"
    assert (
        adapter._normalize_generate_content_response(
            response={}, model="gemini-test", vertexai=False, project=None, location=None
        )["status"]
        == "error"
    )
    tools = adapter._normalize_generate_content_response(
        response={
            "model_version": "v",
            "response_id": "r",
            "parsed": {"ok": True},
            "candidates": [
                {
                    "finish_reason": "STOP",
                    "content": {"parts": [{"function_call": {"name": "tool", "args": {}}}]},
                }
            ],
        },
        model="gemini-test",
        vertexai=True,
        project="project",
        location="location",
    )
    assert tools["action"] == "call_tool"
    assert tools["metadata"]["response_id"] == "r"
    assert (
        adapter._normalize_generate_content_chunks(
            response=[], model="gemini-test", vertexai=False, project=None, location=None
        )["status"]
        == "error"
    )


@pytest.mark.asyncio
async def test_gemini_public_interactions_execution_owns_client_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = GeminiAdapterPlugin()
    closed = AsyncMock()
    client = SimpleNamespace(aio=SimpleNamespace(aclose=closed))
    genai = ModuleType("google.genai")
    genai.Client = lambda **kwargs: client  # type: ignore[attr-defined]
    errors = ModuleType("google.genai.errors")
    errors.APIError = RuntimeError  # type: ignore[attr-defined]
    types = ModuleType("google.genai.types")
    types.GenerateContentConfig = _Types.GenerateContentConfig  # type: ignore[attr-defined]
    google = ModuleType("google")
    google.genai = genai  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.errors", errors)
    monkeypatch.setitem(sys.modules, "google.genai.types", types)
    with patch.object(
        adapter,
        "_execute_interaction",
        new=AsyncMock(return_value={"status": "success", "output": "CERTIFIED", "metadata": {}}),
    ) as execute:
        result = await adapter.execute_gemini_query(
            {"api_key": "key", "model": "gemini-test", "task": "hello"}
        )
    assert result["output"] == "CERTIFIED"
    execute.assert_awaited_once()
    closed.assert_awaited_once()


@pytest.mark.asyncio
async def test_gemini_public_validation_and_exception_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = GeminiAdapterPlugin()
    closed = AsyncMock()
    client = SimpleNamespace(aio=SimpleNamespace(aclose=closed))
    genai = ModuleType("google.genai")
    genai.Client = lambda **kwargs: client  # type: ignore[attr-defined]
    errors = ModuleType("google.genai.errors")
    errors.APIError = RuntimeError  # type: ignore[attr-defined]
    types = ModuleType("google.genai.types")
    types.GenerateContentConfig = _Types.GenerateContentConfig  # type: ignore[attr-defined]
    google = ModuleType("google")
    google.genai = genai  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.errors", errors)
    monkeypatch.setitem(sys.modules, "google.genai.types", types)
    assert (await adapter.execute_gemini_query({}))["status"] == "error"
    assert (await adapter.execute_gemini_query({"model": "gemini-test", "task": "hello"}))[
        "status"
    ] == "error"
    with patch.object(adapter, "_execute_interaction", new=AsyncMock(side_effect=TimeoutError())):
        timeout = await adapter.execute_gemini_query(
            {"api_key": "key", "model": "gemini-test", "task": "hello"}
        )
    assert "timed out" in timeout["message"]
    with patch.object(
        adapter, "_execute_interaction", new=AsyncMock(side_effect=RuntimeError("boom"))
    ):
        failed = await adapter.execute_gemini_query(
            {"api_key": "key", "model": "gemini-test", "task": "hello"}
        )
    assert failed["metadata"]["error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_gemini_legacy_retry_contracts() -> None:
    adapter = GeminiAdapterPlugin()

    class APIError(Exception):
        status_code = 429

    generate = AsyncMock(side_effect=[APIError("retry"), {"text": "ok"}])
    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    with patch.object(adapter, "_retry_sleep", new=AsyncMock()) as sleep:
        result = await adapter._call_generate_content_with_retry(
            client=client,
            genai_errors=SimpleNamespace(APIError=APIError),
            request={"model": "gemini-test"},
            timeout_seconds=1,
            payload={"max_attempts": 2},
        )
    assert result == {"text": "ok"}
    sleep.assert_awaited_once()

    stream = AsyncMock(side_effect=[APIError("retry"), _AsyncEvents([{"text": "ok"}])])
    client.aio.models.generate_content_stream = stream
    with patch.object(adapter, "_retry_sleep", new=AsyncMock()) as sleep:
        chunks = await adapter._call_generate_content_stream_with_retry(
            client=client,
            genai_errors=SimpleNamespace(APIError=APIError),
            request={"model": "gemini-test"},
            timeout_seconds=1,
            payload={"max_attempts": 2},
        )
    assert chunks == [{"text": "ok"}]
    sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_gemini_configuration_serialization_and_error_helper_edges() -> None:
    adapter = GeminiAdapterPlugin()

    class Broken:
        def model_dump(self) -> object:
            raise ValueError("broken")

    assert adapter._serialize(Broken()) == {}
    assert adapter._summarize_stream_event({}) is None
    assert adapter._summarize_stream_event({"event_type": "event", "status": 1}) == {
        "event_type": "event",
        "status": "1",
    }
    assert adapter._resolve_agent({"agent_id": " a "}) == "a"
    assert adapter._resolve_agent({"agent": " "}) is None
    assert adapter._resolve_vertex_mode({"vertex_ai": True}, None)
    assert adapter._resolve_vertex_mode({"metadata": {"vertexai": True}}, None)
    assert adapter._build_http_options({}, types=_Types) is None
    assert adapter._normalize_tools(None) is None
    assert adapter._resolve_response_format({"response_format": {"type": "text"}}) == {
        "type": "text"
    }
    with (
        patch("eval_runner.adapters.gemini.random.uniform", return_value=0.2),
        patch("eval_runner.adapters.gemini.asyncio.sleep", new=AsyncMock()) as sleep,
    ):
        await adapter._retry_sleep(attempt=1, payload={"retry_delay": 0.1, "max_retry_delay": 1})
    sleep.assert_awaited_once()
    assert adapter._extract_status_code(SimpleNamespace(status="bad")) is None
    assert adapter._extract_retry_after(SimpleNamespace(headers={"Retry-After": "bad"})) is None


@pytest.mark.asyncio
async def test_gemini_public_vertex_legacy_configuration_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = GeminiAdapterPlugin()
    closed = AsyncMock()
    captured: dict[str, object] = {}

    def client_factory(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(aio=SimpleNamespace(aclose=closed))

    genai = ModuleType("google.genai")
    genai.Client = client_factory  # type: ignore[attr-defined]
    errors = ModuleType("google.genai.errors")
    errors.APIError = RuntimeError  # type: ignore[attr-defined]
    types = ModuleType("google.genai.types")
    types.GenerateContentConfig = _Types.GenerateContentConfig  # type: ignore[attr-defined]
    types.HttpOptions = _Types.HttpOptions  # type: ignore[attr-defined]
    google = ModuleType("google")
    google.genai = genai  # type: ignore[attr-defined]
    for name, module in (
        ("google", google),
        ("google.genai", genai),
        ("google.genai.errors", errors),
        ("google.genai.types", types),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    with patch.object(
        adapter,
        "_execute_generate_content",
        new=AsyncMock(return_value={"status": "success", "output": "legacy", "metadata": {}}),
    ):
        result = await adapter.execute_gemini_query(
            {
                "model": "gemini-test",
                "task": "hello",
                "api_mode": "generate_content",
                "vertexai": True,
                "project": "project",
                "location": "location",
                "credentials": "credentials",
                "http_timeout_ms": 100,
            }
        )
    assert result["output"] == "legacy"
    assert captured["vertexai"] is True
    assert captured["project"] == "project"
    closed.assert_awaited_once()


def test_gemini_interaction_extraction_helper_edge_contracts() -> None:
    adapter = GeminiAdapterPlugin()
    assert (
        adapter._extract_interaction_text({"outputs": [{"type": "text", "text": "output"}]})
        == "output"
    )
    assert adapter._extract_function_calls_from_interaction(
        {
            "steps": [{"type": "other"}],
            "outputs": [{"type": "function_call", "name": "tool", "args": {}}],
        }
    ) == [{"id": None, "name": "tool", "arguments": {}}]
    assert adapter._extract_step_text({"content": [{"type": "text", "text": "x"}]}) == ["x"]
    assert adapter._extract_step_text(SimpleNamespace(text="x")) == ["x"]
    assert adapter._extract_step_text(None) == []
    assert adapter._extract_interaction_usage({"usage_metadata": {"tokens": 1}}) == {"tokens": 1}
    assert adapter._extract_interaction_usage({"response_metadata": {"usage": {"tokens": 2}}}) == {
        "tokens": 2
    }


def test_gemini_generate_content_extraction_helper_edge_contracts() -> None:
    adapter = GeminiAdapterPlugin()
    assert adapter._normalize_function_call({}) is None
    assert adapter._normalize_function_call(
        {"name": "tool", "parameters": {"x": 1}, "call_id": "id"}
    ) == {
        "id": "id",
        "name": "tool",
        "arguments": {"x": 1},
    }
    assert (
        adapter._extract_generate_content_text({"parts": [{"text": "one"}, {"text": "two"}]})
        == "one\ntwo"
    )
    response = {
        "candidates": [
            {
                "finish_reason": "STOP",
                "safety_ratings": [{"category": "safe"}],
                "content": {
                    "parts": [
                        {"text": "candidate"},
                        {"function_call": {"name": "tool", "args": {"x": 1}}},
                    ]
                },
            }
        ]
    }
    assert adapter._extract_generate_content_text(response) == "candidate"
    assert adapter._extract_generate_content_function_calls(response)[0]["name"] == "tool"
    assert adapter._extract_generate_content_candidates(response)[0]["finish_reason"] == "STOP"
    assert (
        adapter._extract_generate_content_function_calls(
            {"function_calls": [{"name": "direct", "arguments": {}}]}
        )[0]["name"]
        == "direct"
    )
    assert (
        adapter._extract_message_text([{"text": "one"}, {"parts": [{"text": "two"}]}]) == "one\ntwo"
    )


def test_gemini_adapter_extended_edge_cases() -> None:
    adapter = GeminiAdapterPlugin()

    # Discover adapters hook
    registry = MagicMock()
    adapter.on_discover_adapters(registry)
    registry.register.assert_called_once_with("gemini", adapter.execute_gemini_query)

    # Build interaction input when task is None
    assert adapter._build_interaction_input({}) is None

    # Latest user input with non-mapping and non-user messages
    assert adapter._latest_user_input([123, {"role": "model", "content": "hi"}]) == "hi"

    # Latest user input with parts
    assert adapter._latest_user_input([{"role": "user", "parts": [{"text": "p"}]}]) == [
        {"text": "p"}
    ]

    # Latest user input fallback to last message
    assert adapter._latest_user_input([{"role": "assistant", "content": "a"}]) == "a"
    assert adapter._latest_user_input(["str_msg"]) == "str_msg"

    # Messages to interaction input with strings and typed dicts
    res_str = adapter._messages_to_interaction_input(["just string"])
    assert res_str[0]["text"] == "just string"
    res_typed = adapter._messages_to_interaction_input([{"type": "text", "text": "direct"}])
    assert res_typed[0]["text"] == "direct"

    # Normalize interaction content with Mapping and non-collection scalars
    assert adapter._content_to_text_parts({"text": "hello"}) == [{"type": "text", "text": "hello"}]
    assert adapter._content_to_text_parts({}) == []
    assert adapter._content_to_text_parts(123) == [{"type": "text", "text": "123"}]

    # Normalize interaction part with explicit type and media
    assert adapter._normalize_interaction_part({"type": "custom", "val": 1}) == {
        "type": "custom",
        "val": 1,
    }
    part_file = adapter._normalize_interaction_part(
        {"file_data": {"uri": "gs://b/f", "mime_type": "audio/mp3"}}
    )
    assert part_file is not None and part_file["mime_type"] == "audio/mp3"

    part_url = adapter._normalize_interaction_part(
        {"url": "https://img", "mime_type": "image/jpeg"}
    )
    assert (
        part_url is not None
        and part_url["type"] == "image"
        and part_url["mime_type"] == "image/jpeg"
    )

    # Coerce interaction input with type mapping and scalar
    assert adapter._coerce_interaction_input({"type": "raw"}) == {"type": "raw"}
    assert adapter._coerce_interaction_input(999) == "999"

    # Build generate content contents edge cases
    with pytest.raises(TypeError, match="must be a list"):
        adapter._build_generate_content_contents({"messages": "not_a_list"})

    with pytest.raises(TypeError, match="must be a string or object"):
        adapter._build_generate_content_contents({"messages": [123]})

    contents_str, _ = adapter._build_generate_content_contents({"messages": ["hello string"]})
    assert contents_str[0]["parts"][0]["text"] == "hello string"

    contents_empty, _ = adapter._build_generate_content_contents({})
    assert contents_empty == []

    contents_list, _ = adapter._build_generate_content_contents(
        {"task": [{"role": "user", "parts": []}]}
    )
    assert contents_list == [{"role": "user", "parts": []}]

    # Normalize generate content parts when content is None with message fallback
    assert (
        adapter._normalize_generate_content_parts(
            None,
            message={"tool_response": {"type": "tool_response", "name": "t", "response": {}}},
        )[0]["function_response"]["name"]
        == "t"
    )
    assert adapter._normalize_generate_content_parts(None, message={}) == []
    assert adapter._normalize_generate_content_parts({"text": "m"}, message={}) == [{"text": "m"}]
    assert adapter._normalize_generate_content_parts(["str"], message={}) == [{"text": "str"}]
    assert adapter._normalize_generate_content_parts([123], message={}) == [{"text": "123"}]
    assert adapter._normalize_generate_content_parts(456, message={}) == [{"text": "456"}]

    # Normalize generate content part edge cases
    assert adapter._normalize_generate_content_part({}) == []
    assert adapter._normalize_generate_content_part({"code_execution_result": {}}) == [
        {"code_execution_result": {}}
    ]
    assert adapter._normalize_generate_content_part({"type": "text"}) == [{"text": ""}]
    assert adapter._normalize_generate_content_part({"type": "text", "text": "t"}) == [
        {"type": "text", "text": "t"}
    ]
    assert adapter._normalize_generate_content_part({"type": "image", "image": "gs://img"}) == [
        {"file_data": {"file_uri": "gs://img"}}
    ]
    assert (
        adapter._normalize_generate_content_part(
            {"type": "image", "image": {"url": "gs://img", "mime_type": "image/png"}}
        )[0]["file_data"]["mime_type"]
        == "image/png"
    )
    assert (
        adapter._normalize_generate_content_part({"url": "gs://img", "mime_type": "image/png"})[0][
            "file_data"
        ]["mime_type"]
        == "image/png"
    )
    assert adapter._normalize_generate_content_part({"unknown_key": "val"}) == [
        {"unknown_key": "val"}
    ]

    # Normalize interaction empty and stream single tool
    assert (
        adapter._normalize_interaction(
            response=SimpleNamespace(),
            model="m",
            agent=None,
            vertexai=False,
            project=None,
            location=None,
        )["status"]
        == "error"
    )
    norm_stream = adapter._normalize_streamed_interaction(
        response={"function_calls": [{"name": "tool", "arguments": {}}]},
        model="m",
        agent=None,
        vertexai=False,
        project=None,
        location=None,
    )
    assert norm_stream["action"] == "call_tool"

    # Stream generate content chunks usage and tool calls
    chunk_usage = SimpleNamespace(
        usage_metadata={"total_token_count": 10}, text=None, candidates=[]
    )
    norm_chunks_usage = adapter._normalize_generate_content_chunks(
        response=[chunk_usage],
        model="m",
        vertexai=False,
        project=None,
        location=None,
    )
    assert norm_chunks_usage["metadata"]["usage"]["total_token_count"] == 10

    chunk_call = SimpleNamespace(
        text=None,
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[SimpleNamespace(function_call=SimpleNamespace(name="t", args={}))]
                )
            )
        ],
        usage_metadata=None,
    )
    norm_chunks_tool = adapter._normalize_generate_content_chunks(
        response=[chunk_call],
        model="m",
        vertexai=False,
        project=None,
        location=None,
    )
    assert norm_chunks_tool["action"] == "call_tool"

    # Build generate content config with explicit generation_config
    cfg = adapter._build_generate_content_config(
        payload={"generation_config": {"temperature": 0.5}},
        types=_Types,
        system_instruction=None,
    )
    assert cfg.kwargs["temperature"] == 0.5

    # Resolution helpers
    assert adapter._resolve_vertex_mode({"metadata": {"vertex_ai": True}}, None) is True
    assert (
        adapter._resolve_max_attempts({"max_retries": "not_an_int"})
        == adapter.DEFAULT_MAX_RETRIES + 1
    )
    assert adapter._resolve_max_attempts({}) == adapter.DEFAULT_MAX_RETRIES + 1
    assert adapter._resolve_backoff_base({}) == adapter.DEFAULT_BACKOFF_BASE
    assert adapter._resolve_backoff_max({}) == adapter.DEFAULT_BACKOFF_MAX

    # Extraction helpers
    assert adapter._extract_function_calls_from_interaction({"outputs": [{"type": "not_fn"}]}) == []
    assert adapter._extract_step_text("direct_str") == ["direct_str"]
    assert adapter._extract_step_text({"other_key": 1}) == []
    assert adapter._extract_step_text(SimpleNamespace(text=123)) == []
    assert adapter._extract_generate_content_text({"candidates": [{"content": {}}]}) == ""
    assert adapter._extract_generate_content_function_calls({"candidates": [{"content": {}}]}) == []
    assert adapter._extract_message_text(None) is None
    assert adapter._extract_message_text({"other": 1}) is None
    assert adapter._extract_message_text(123) == "123"

    # Edge case extraction and resolution helpers
    assert adapter._latest_user_input([123]) == "123"
    assert adapter._latest_user_input([]) is None
    assert adapter._normalize_interaction_part({"unknown": "val"}) == {
        "type": "text",
        "text": "{'unknown': 'val'}",
    }
    assert (
        adapter._extract_generate_content_text(
            {"candidates": [SimpleNamespace(content=SimpleNamespace(parts=[]))]}
        )
        == ""
    )
    assert (
        adapter._extract_generate_content_function_calls(
            {"candidates": [SimpleNamespace(content=SimpleNamespace(parts=[]))]}
        )
        == []
    )
    assert adapter._resolve_max_attempts({"max_retries": "bad"}) == adapter.DEFAULT_MAX_RETRIES + 1
    assert adapter._resolve_max_attempts({"max_attempts": "bad"}) == adapter.DEFAULT_MAX_RETRIES + 1
    assert adapter._resolve_backoff_base({"retry_delay": "bad"}) == adapter.DEFAULT_BACKOFF_BASE
    assert adapter._resolve_backoff_max({"max_retry_delay": "bad"}) == adapter.DEFAULT_BACKOFF_MAX
    with patch("eval_runner.config.ADAPTER_MAX_RETRIES", 5, create=True):
        assert adapter._resolve_max_attempts({}) == 6
    with patch("eval_runner.config.ADAPTER_RETRY_DELAY", 2.0, create=True):
        assert adapter._resolve_backoff_base({}) == 2.0
    with patch("eval_runner.config.ADAPTER_MAX_RETRY_DELAY", 45.0, create=True):
        assert adapter._resolve_backoff_max({}) == 45.0

    # Serialization exception fallback
    class _Unserializable:
        __slots__ = ()

        def __str__(self) -> str:
            return "unserializable"

    assert adapter._serialize(_Unserializable()) == "unserializable"

    # Emit usage with non-mapping
    adapter._emit_usage({"usage": "not_a_mapping"})

    # Extract retry after with invalid float
    exc_bad_retry = Exception()
    exc_bad_retry.raw_response = SimpleNamespace(headers={"Retry-After": "invalid"})
    assert adapter._extract_retry_after(exc_bad_retry) is None


@pytest.mark.asyncio
async def test_gemini_adapter_async_extended_edge_cases() -> None:
    adapter = GeminiAdapterPlugin()

    # Missing google-genai import error
    import builtins

    orig_import = builtins.__import__

    def mock_genai_import(name, *args, **kwargs):
        if "google.genai" in name or name == "google.genai":
            raise ImportError("simulated missing google-genai")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_genai_import):
        res_no_pkg = await adapter.execute_gemini_query({"model": "m", "task": "t"})
        assert res_no_pkg["status"] == "error"
        assert "requires the 'google-genai' package" in res_no_pkg["message"]

    # Missing model or agent error
    with patch.object(adapter, "_resolve_model", return_value=None):
        with patch.object(adapter, "_resolve_agent", return_value=None):
            res_no_model = await adapter.execute_gemini_query({})
            assert res_no_model["status"] == "error"
            assert "requires either 'model' or 'agent'" in res_no_model["message"]

    # CancelledError in execute_gemini_query
    def _create_mock_client(**kwargs: object) -> MagicMock:
        c = MagicMock()
        c.aio.aclose = AsyncMock()
        return c

    with patch.dict(
        sys.modules,
        {
            "google": MagicMock(),
            "google.genai": MagicMock(Client=_create_mock_client),
            "google.genai.errors": MagicMock(),
            "google.genai.types": _Types,
        },
    ):
        with patch.object(adapter, "_execute_interaction", side_effect=asyncio.CancelledError()):
            with pytest.raises(asyncio.CancelledError):
                await adapter.execute_gemini_query({"api_key": "k", "model": "m", "task": "t"})

        # Status code in exception
        exc_status = Exception("not found")
        exc_status.status_code = 404
        with patch.object(adapter, "_execute_interaction", side_effect=exc_status):
            res_exc = await adapter.execute_gemini_query(
                {"api_key": "k", "model": "m", "task": "t"}
            )
            assert res_exc["status"] == "error"
            assert res_exc["metadata"]["status_code"] == 404

        # Client cleanup failure warning in finally
        client_cleanup_fail = MagicMock()
        client_cleanup_fail.aio.aclose = AsyncMock(side_effect=RuntimeError("close failed"))
        with patch.dict(
            sys.modules,
            {"google.genai": MagicMock(Client=lambda **kwargs: client_cleanup_fail)},
        ):
            with patch.object(
                adapter,
                "_execute_interaction",
                return_value={"status": "success", "metadata": {}},
            ):
                res_cleanup = await adapter.execute_gemini_query(
                    {"api_key": "k", "model": "m", "task": "t"}
                )
                assert res_cleanup["status"] == "success"

    # _call_interaction_with_retry with timeout_seconds == 0
    client_invoke = MagicMock()
    client_invoke.aio.interactions.create = AsyncMock(return_value="interaction_res")
    assert (
        await adapter._call_interaction_with_retry(
            client=client_invoke,
            genai_errors=MagicMock(),
            request={},
            timeout_seconds=0,
            payload={},
        )
        == "interaction_res"
    )

    # CancelledError in _call_interaction_with_retry
    client_invoke.aio.interactions.create = AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await adapter._call_interaction_with_retry(
            client=client_invoke,
            genai_errors=MagicMock(),
            request={},
            timeout_seconds=1,
            payload={},
        )

    # TimeoutError retry loop in _call_interaction_with_retry
    timeout_calls = []

    async def mock_timeout_create(**kwargs: object) -> str:
        timeout_calls.append(1)
        if len(timeout_calls) < 2:
            raise TimeoutError()
        return "success"

    client_invoke.aio.interactions.create = mock_timeout_create
    with patch.object(adapter, "_retry_sleep", new_callable=AsyncMock):
        res_timeout = await adapter._call_interaction_with_retry(
            client=client_invoke,
            genai_errors=MagicMock(),
            request={},
            timeout_seconds=1,
            payload={"idempotency_key": "k"},
        )
        assert res_timeout == "success"

    # APIError not retryable in _call_interaction_with_retry
    err_cls = type("APIError", (Exception,), {})
    genai_errs = SimpleNamespace(APIError=err_cls)
    err_inst = err_cls("bad request")
    err_inst.code = 400
    client_invoke.aio.interactions.create = AsyncMock(side_effect=err_inst)
    with pytest.raises(err_cls):
        await adapter._call_interaction_with_retry(
            client=client_invoke,
            genai_errors=genai_errs,
            request={},
            timeout_seconds=1,
            payload={"max_attempts": 1},
        )

    # _call_interaction_stream_with_retry CancelledError
    with patch.object(adapter, "_consume_interaction_stream", side_effect=asyncio.CancelledError()):
        with pytest.raises(asyncio.CancelledError):
            await adapter._call_interaction_stream_with_retry(
                client=MagicMock(),
                genai_errors=MagicMock(),
                request={},
                timeout_seconds=1,
                payload={},
            )

    # _call_interaction_stream_with_retry TimeoutError retry
    stream_timeout_calls = []

    async def mock_stream_timeout(**kwargs: object) -> dict[str, str]:
        stream_timeout_calls.append(1)
        if len(stream_timeout_calls) < 2:
            raise TimeoutError()
        return {"text": "streamed"}

    with patch.object(adapter, "provider_retry_attempts", return_value=2):
        with patch.object(adapter, "_consume_interaction_stream", side_effect=mock_stream_timeout):
            with patch.object(adapter, "_retry_sleep", new_callable=AsyncMock):
                res_stream_timeout = await adapter._call_interaction_stream_with_retry(
                    client=MagicMock(),
                    genai_errors=MagicMock(),
                    request={},
                    timeout_seconds=1,
                    payload={"idempotency_key": "k"},
                )
                assert res_stream_timeout == {"text": "streamed"}

    # _call_interaction_stream_with_retry APIError with retry_after
    err_retry = err_cls("rate limited")
    err_retry.code = 429
    err_retry.headers = {"Retry-After": "5"}
    stream_api_calls = []

    async def mock_stream_api(**kwargs: object) -> dict[str, str]:
        stream_api_calls.append(1)
        if len(stream_api_calls) < 2:
            raise err_retry
        return {"text": "recovered"}

    with patch.object(adapter, "provider_retry_attempts", return_value=2):
        with patch.object(adapter, "_consume_interaction_stream", side_effect=mock_stream_api):
            with patch.object(adapter, "_retry_sleep", new_callable=AsyncMock) as mock_sleep:
                res_stream_api = await adapter._call_interaction_stream_with_retry(
                    client=MagicMock(),
                    genai_errors=genai_errs,
                    request={},
                    timeout_seconds=1,
                    payload={"idempotency_key": "k"},
                )
                assert res_stream_api == {"text": "recovered"}
                assert mock_sleep.call_args[1].get("retry_after") == 5.0

    # _consume_interaction_stream with timeout_seconds == 0
    client_stream_zero = MagicMock()
    client_stream_zero.aio.interactions.create = AsyncMock(return_value=_AsyncEvents([]))
    res_zero = await adapter._consume_interaction_stream(
        client=client_stream_zero, request={}, timeout_seconds=0
    )
    assert res_zero["text"] == ""

    # _build_interaction_request with no input error and response format
    with pytest.raises(ValueError, match="contains no input"):
        adapter._build_interaction_request(payload={}, model="m", agent=None)

    req_fmt = adapter._build_interaction_request(
        payload={"task": "t", "response_json_schema": {"type": "object"}},
        model="m",
        agent=None,
    )
    assert "response_format" in req_fmt

    # _call_interaction_with_retry TimeoutError exhaustion
    client_timeout_fail = MagicMock()
    client_timeout_fail.aio.interactions.create = AsyncMock(side_effect=TimeoutError())
    with pytest.raises(TimeoutError):
        await adapter._call_interaction_with_retry(
            client=client_timeout_fail,
            genai_errors=MagicMock(),
            request={},
            timeout_seconds=1,
            payload={"max_attempts": 1},
        )

    # _call_interaction_stream_with_retry TimeoutError exhaustion
    with patch.object(adapter, "_consume_interaction_stream", side_effect=TimeoutError()):
        with pytest.raises(TimeoutError):
            await adapter._call_interaction_stream_with_retry(
                client=MagicMock(),
                genai_errors=MagicMock(),
                request={},
                timeout_seconds=1,
                payload={"max_attempts": 1},
            )

    # _execute_generate_content missing model error
    res_gc_no_model = await adapter._execute_generate_content(
        payload={},
        model=None,
        client=MagicMock(),
        genai_errors=MagicMock(),
        types=_Types,
        vertexai=False,
        project=None,
        location=None,
        timeout_seconds=10,
    )
    assert res_gc_no_model["status"] == "error"

    # _execute_generate_content with explicit generation_config
    mock_gc_gen = MagicMock()
    mock_gc_gen.aio.models.generate_content = AsyncMock(
        return_value=SimpleNamespace(text="ok", candidates=[])
    )
    res_gc_cfg = await adapter._execute_generate_content(
        payload={"generation_config": {"temperature": 0.5}},
        model="m",
        client=mock_gc_gen,
        genai_errors=MagicMock(),
        types=_Types,
        vertexai=False,
        project=None,
        location=None,
        timeout_seconds=10,
    )
    assert res_gc_cfg["status"] == "success"

    # _call_generate_content_with_retry timeout == 0, CancelledError, TimeoutError, APIError
    client_gc = MagicMock()
    client_gc.aio.models.generate_content = AsyncMock(return_value="gc_res")
    assert (
        await adapter._call_generate_content_with_retry(
            client=client_gc,
            genai_errors=MagicMock(),
            request={},
            timeout_seconds=0,
            payload={},
        )
        == "gc_res"
    )

    client_gc.aio.models.generate_content = AsyncMock(side_effect=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await adapter._call_generate_content_with_retry(
            client=client_gc,
            genai_errors=MagicMock(),
            request={},
            timeout_seconds=1,
            payload={},
        )

    gc_timeout_calls = []

    async def mock_gc_timeout(**kwargs: object) -> str:
        gc_timeout_calls.append(1)
        if len(gc_timeout_calls) < 2:
            raise TimeoutError()
        return "gc_recovered"

    client_gc.aio.models.generate_content = mock_gc_timeout
    with patch.object(adapter, "_retry_sleep", new_callable=AsyncMock):
        assert (
            await adapter._call_generate_content_with_retry(
                client=client_gc,
                genai_errors=MagicMock(),
                request={},
                timeout_seconds=1,
                payload={"idempotency_key": "k"},
            )
            == "gc_recovered"
        )

    client_gc.aio.models.generate_content = AsyncMock(side_effect=err_inst)
    with pytest.raises(err_cls):
        await adapter._call_generate_content_with_retry(
            client=client_gc,
            genai_errors=genai_errs,
            request={},
            timeout_seconds=1,
            payload={"max_attempts": 1},
        )

    # _call_generate_content_stream_with_retry timeout == 0, CancelledError, TimeoutError, APIError
    client_gc_stream = MagicMock()
    chunk_item = SimpleNamespace(text="streamed_chunk")
    client_gc_stream.aio.models.generate_content_stream = AsyncMock(
        return_value=_AsyncEvents([chunk_item])
    )
    chunks_res = await adapter._call_generate_content_stream_with_retry(
        client=client_gc_stream,
        genai_errors=MagicMock(),
        request={},
        timeout_seconds=0,
        payload={},
    )
    assert len(chunks_res) == 1

    client_gc_stream.aio.models.generate_content_stream = AsyncMock(
        side_effect=asyncio.CancelledError()
    )
    with pytest.raises(asyncio.CancelledError):
        await adapter._call_generate_content_stream_with_retry(
            client=client_gc_stream,
            genai_errors=MagicMock(),
            request={},
            timeout_seconds=1,
            payload={},
        )

    gc_stream_timeout_calls = []

    async def mock_gc_stream_timeout(**kwargs: object) -> _AsyncEvents:
        gc_stream_timeout_calls.append(1)
        if len(gc_stream_timeout_calls) < 2:
            raise TimeoutError()
        return _AsyncEvents([chunk_item])

    client_gc_stream.aio.models.generate_content_stream = mock_gc_stream_timeout
    with patch.object(adapter, "_retry_sleep", new_callable=AsyncMock):
        assert (
            len(
                await adapter._call_generate_content_stream_with_retry(
                    client=client_gc_stream,
                    genai_errors=MagicMock(),
                    request={},
                    timeout_seconds=1,
                    payload={"idempotency_key": "k"},
                )
            )
            == 1
        )

    client_gc_stream.aio.models.generate_content_stream = AsyncMock(side_effect=err_inst)
    with pytest.raises(err_cls):
        await adapter._call_generate_content_stream_with_retry(
            client=client_gc_stream,
            genai_errors=genai_errs,
            request={},
            timeout_seconds=1,
            payload={"max_attempts": 1},
        )

    # _call_generate_content_with_retry TimeoutError exhaustion
    client_gc_timeout = MagicMock()
    client_gc_timeout.aio.models.generate_content = AsyncMock(side_effect=TimeoutError())
    with pytest.raises(TimeoutError):
        await adapter._call_generate_content_with_retry(
            client=client_gc_timeout,
            genai_errors=MagicMock(),
            request={},
            timeout_seconds=1,
            payload={"max_attempts": 1},
        )

    # _call_generate_content_stream_with_retry TimeoutError exhaustion
    client_gc_stream_timeout = MagicMock()
    client_gc_stream_timeout.aio.models.generate_content_stream = AsyncMock(
        side_effect=TimeoutError()
    )
    with pytest.raises(TimeoutError):
        await adapter._call_generate_content_stream_with_retry(
            client=client_gc_stream_timeout,
            genai_errors=MagicMock(),
            request={},
            timeout_seconds=1,
            payload={"max_attempts": 1},
        )
