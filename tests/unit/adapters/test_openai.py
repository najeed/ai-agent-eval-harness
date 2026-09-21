import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from eval_runner.adapters.openai import OpenAIAdapterError, OpenAIAdapterPlugin


class _AsyncLines:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines

    def __aiter__(self):
        self._iterator = iter(self.lines)
        return self

    async def __anext__(self) -> bytes:
        try:
            return next(self._iterator)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _ResponseContext:
    def __init__(self, response: object) -> None:
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *_args: object) -> bool:
        return False


def _sse_event(value: dict[str, object]) -> bytes:
    return f"data: {json.dumps(value)}\n".encode()


def test_openai_configuration_input_and_request_builders() -> None:
    adapter = OpenAIAdapterPlugin()
    traceparent = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
    merged = adapter._merge_runtime_payload(
        {"task": "current", "input_payload": {"model": "nested"}, "turn_context": {"history": []}}
    )
    assert merged["model"] == "nested"
    assert merged["history"] == []
    assert adapter._resolve_api_mode({}, "https://api.openai.com/v1") == "responses"
    assert (
        adapter._resolve_api_mode({}, "https://example.test/chat/completions") == "chat_completions"
    )
    assert (
        adapter._resolve_endpoint("https://example.test/v1/", "responses")
        == "https://example.test/v1/responses"
    )
    assert adapter._resolve_endpoint(
        "https://example.test/v1/responses", "chat_completions"
    ).endswith("/chat/completions")
    assert adapter._resolve_bool("yes", default=False)
    assert not adapter._resolve_bool("off", default=True)
    with pytest.raises(OpenAIAdapterError):
        adapter._resolve_bool("perhaps", default=False)

    messages, prompt = adapter._build_input_messages(
        {
            "history": [{"role": "tool", "tool_call_id": "call-1", "content": {"ok": True}}],
            "system_prompt": "system",
        }
    )
    assert prompt == "system"
    assert messages[0]["role"] == "system"
    assert messages[1]["content"] == '{"ok": true}'
    headers = adapter._build_headers(
        {
            "span_context": {"traceparent": traceparent},
            "organization": "org",
            "headers": {"X-Test": 3, "Authorization": "no"},
        },
        api_key="key",
    )
    assert headers["traceparent"] == traceparent
    assert headers["OpenAI-Organization"] == "org"
    assert headers["X-Test"] == "3"
    assert headers["Authorization"] == "Bearer key"

    chat = adapter._build_chat_payload(
        payload={"max_output_tokens": 7, "tools": [{"type": "function"}]},
        model="gpt-test",
        messages=messages,
        stream=True,
    )
    assert chat["max_completion_tokens"] == 7
    assert chat["stream_options"] == {"include_usage": True}
    responses = adapter._build_responses_payload(
        payload={"response_format": {"type": "json_object"}, "previous_response_id": "resp-1"},
        model="gpt-test",
        messages=messages,
        system_prompt="system",
        stream=False,
    )
    assert responses["instructions"] == "system"
    assert responses["text"] == {"format": {"type": "json_object"}}
    assert responses["previous_response_id"] == "resp-1"


def test_openai_normalizers_cover_text_tools_refusals_and_errors() -> None:
    adapter = OpenAIAdapterPlugin()
    chat = adapter._normalize_chat_completion(
        {
            "id": "chat-1",
            "model": "gpt",
            "usage": {"prompt_tokens": "2", "completion_tokens": 3},
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": [{"type": "text", "text": "working"}],
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {"name": "lookup", "arguments": '{"id":1}'},
                            }
                        ],
                    },
                }
            ],
        }
    )
    assert chat["action"] == "call_tool"
    assert chat["tool_params"] == {"id": 1}
    assert chat["_usage"]["total_tokens"] == 5
    response = adapter._normalize_responses(
        {
            "id": "resp-1",
            "model": "gpt",
            "status": "completed",
            "usage": {"input_tokens": 1, "output_tokens": 2},
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "hello"}]},
                {
                    "type": "function_call",
                    "name": "lookup",
                    "arguments": '{"q":"x"}',
                    "call_id": "call-2",
                },
            ],
        }
    )
    assert response["action"] == "call_tool"
    assert response["output"] == "hello"
    assert (
        adapter._normalize_responses(
            {
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}],
            }
        )["output"]
        == "no"
    )
    assert adapter._extract_chat_content([{"type": "refusal", "refusal": "blocked"}]) == "blocked"
    assert adapter._parse_tool_arguments(None) == {}
    assert adapter._parse_tool_arguments({"x": 1}) == {"x": 1}
    assert (
        adapter._extract_api_error_message({"error": {"type": "invalid", "code": "x"}})
        == "type=invalid, code=x"
    )
    with pytest.raises(OpenAIAdapterError, match="malformed"):
        adapter._parse_tool_arguments("[")
    with pytest.raises(OpenAIAdapterError, match="status=failed"):
        adapter._normalize_responses({"status": "failed", "error": {}})


def test_openai_configuration_and_input_validation_contracts() -> None:
    adapter = OpenAIAdapterPlugin()
    registry = type("Registry", (), {"register": MagicMock()})()
    adapter.on_discover_adapters(registry)
    registry.register.assert_called_once()
    with pytest.raises(OpenAIAdapterError, match="payload must be an object"):
        adapter._merge_runtime_payload([])  # type: ignore[arg-type]
    assert adapter._resolve_api_key({"metadata": {"api_key": " metadata "}}) == "metadata"
    with patch("eval_runner.adapters.openai.config.OPENAI_MODEL", None):
        with pytest.raises(OpenAIAdapterError, match="model is missing"):
            adapter._resolve_model({})
    with pytest.raises(OpenAIAdapterError, match="Unsupported"):
        adapter._resolve_api_mode({"api_mode": "invalid"}, "https://example.test")
    for endpoint, message in (
        (" ", "endpoint is empty"),
        ("relative", "absolute http"),
        ("https://example.test/v1#fragment", "must not contain"),
    ):
        with pytest.raises(OpenAIAdapterError, match=message):
            adapter._resolve_endpoint(endpoint, "responses")
    assert adapter._resolve_bool(0, default=True) is False
    assert adapter._resolve_bool(None, default=True) is True
    with pytest.raises(OpenAIAdapterError, match="must be an array"):
        adapter._build_input_messages({"messages": "bad"})
    invalid_messages = (
        (["bad"], "expected an object"),
        ([{}], "missing role"),
        ([{"role": "unknown", "content": "x"}], "unsupported role"),
        ([{"role": "user"}], "missing content"),
        ([{"role": "tool", "content": "x"}], "missing tool_call_id"),
    )
    for messages, message in invalid_messages:
        with pytest.raises(OpenAIAdapterError, match=message):
            adapter._build_input_messages({"messages": messages})
    messages, system = adapter._build_input_messages(
        {"input_payload": {"task_description": "nested"}, "system_prompt": " rules "}
    )
    assert system == "rules"
    assert messages[-1]["content"] == "nested"
    assert adapter._normalize_message_content(None) == ""
    assert adapter._normalize_message_content({"a": 1}) == '{"a": 1}'
    headers = adapter._build_headers(
        {"project": "project", "client_request_id": "request", "headers": {None: "x", " ": "x"}},
        api_key="key",
    )
    assert headers["OpenAI-Project"] == "project"
    assert headers["X-Client-Request-Id"] == "request"
    merged = adapter._merge_runtime_payload(
        {"turn_context": {"input_payload": {"temperature": 0}, "metadata": {"model": "gpt"}}}
    )
    assert merged["temperature"] == 0
    assert adapter._resolve_api_mode({}, "https://example.test/responses") == "responses"
    assert adapter._resolve_api_mode({}, "https://example.test/v1") == "chat_completions"
    assert adapter._resolve_endpoint("https://example.test/v1?x=1", "responses").endswith(
        "/v1/responses?x=1"
    )
    assert adapter._resolve_endpoint("https://example.test/v1/responses?x=1", "responses").endswith(
        "/v1/responses?x=1"
    )
    normalized, _ = adapter._build_input_messages(
        {"messages": [{"role": "user", "content": ["part"]}, {"role": "assistant"}]}
    )
    assert normalized[0]["content"] == ["part"]
    assert (
        adapter._build_input_messages({"input_payload": {"prompt": "prompt"}})[0][-1]["content"]
        == "prompt"
    )
    assert (
        adapter._build_input_messages({"input_payload": {"input": "input"}})[0][-1]["content"]
        == "input"
    )
    assert adapter._normalize_message_content("text") == "text"


def test_openai_request_conversion_and_optional_fields_contracts() -> None:
    adapter = OpenAIAdapterPlugin()
    messages = [
        {"role": "developer", "content": "rules"},
        {
            "role": "assistant",
            "content": "working",
            "tool_calls": [
                {"id": "call", "function": {"name": "lookup", "arguments": {"q": "x"}}},
                {"function": {}},
                "ignored",
            ],
        },
        {"role": "tool", "tool_call_id": "call", "content": {"result": 1}},
    ]
    converted = adapter._messages_for_responses_api(messages)
    assert any(item.get("type") == "function_call" for item in converted)
    assert any(item.get("type") == "function_call_output" for item in converted)
    chat = adapter._build_chat_payload(
        payload={"temperature": 0, "stream_options": {"include_usage": False}},
        model="gpt",
        messages=messages,
        stream=True,
    )
    assert chat["stream_options"] == {"include_usage": False}
    responses = adapter._build_responses_payload(
        payload={"response_format": "ignored", "text": {"verbosity": "low"}},
        model="gpt",
        messages=messages,
        system_prompt=None,
        stream=False,
    )
    assert responses["text"] == {"verbosity": "low"}


def test_openai_normalization_failure_and_helper_contracts() -> None:
    adapter = OpenAIAdapterPlugin()
    for data, message in (
        ({"choices": []}, "no choices"),
        ({"choices": ["bad"]}, "invalid choice"),
        ({"choices": [{"message": "bad"}]}, "invalid message"),
        ({"choices": [{"finish_reason": "length", "message": {}}]}, "output limit"),
    ):
        with pytest.raises(OpenAIAdapterError, match=message):
            adapter._normalize_chat_completion(data)
    multi = adapter._normalize_chat_completion(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"id": "1", "function": {"name": "one", "arguments": "{}"}},
                            {"id": "2", "function": {"name": "two", "arguments": "{}"}},
                        ]
                    }
                }
            ]
        }
    )
    assert multi["action"] == "call_multiple_tools"
    for arguments, message in (([], "must be JSON"), ("[]", "JSON object")):
        with pytest.raises(OpenAIAdapterError, match=message):
            adapter._parse_tool_arguments(arguments)
    for calls, message in (
        ("bad", "must be an array"),
        (["bad"], "not an object"),
        ([{}], "function object"),
    ):
        with pytest.raises(OpenAIAdapterError, match=message):
            adapter._normalize_chat_tool_calls(calls)
    assert (
        adapter._extract_chat_content(["one", None, {"type": "refusal", "refusal": "two"}])
        == "onetwo"
    )
    assert adapter._extract_chat_content(3) == "3"
    assert adapter._normalize_usage({"input_tokens": "bad", "output_tokens": 2}) == {
        "completion_tokens": 2
    }
    assert (
        adapter._normalize_usage({"prompt_tokens": 1, "completion_tokens": 2})["total_tokens"] == 3
    )
    assert adapter._extract_api_error_message({"message": "top"}) == "top"
    assert adapter._extract_api_error_message({}) == "Unknown OpenAI API error."
    assert adapter._drop_none({"a": 1, "b": None}) == {"a": 1}
    with pytest.raises(OpenAIAdapterError, match="invalid output"):
        adapter._normalize_responses({"output": "bad"})
    with pytest.raises(OpenAIAdapterError, match="without a name"):
        adapter._normalize_responses({"output": [{"type": "function_call"}]})
    assert (
        adapter._normalize_responses({"output": [{"type": "message", "content": "text"}]})["output"]
        == "text"
    )
    assert adapter._normalize_responses({"output_text": "fallback"})["output"] == "fallback"
    with pytest.raises(OpenAIAdapterError, match="no usable content"):
        adapter._normalize_responses({"status": "incomplete", "output": []})
    with pytest.raises(OpenAIAdapterError, match="neither text"):
        adapter._normalize_responses({"status": "completed", "output": []})
    assert adapter._parse_tool_arguments("null") == {}
    with pytest.raises(OpenAIAdapterError, match="function name"):
        adapter._normalize_chat_tool_calls([{"function": {}}])
    refusal = adapter._normalize_chat_completion({"choices": [{"message": {"refusal": "no"}}]})
    assert refusal["output"] == "no"
    assert (
        adapter._normalize_responses(
            {
                "output": [
                    None,
                    {"type": "message", "content": [{"type": "refusal", "refusal": "no"}]},
                ]
            }
        )["output"]
        == "no"
    )
    assert adapter._normalize_usage({"input_tokens": "bad", "output_tokens": "bad"}) == {}


@pytest.mark.asyncio
async def test_openai_execute_responses_stream_and_input_failures() -> None:
    adapter = OpenAIAdapterPlugin()
    payload = {
        "api_key": "test",
        "task": "hello",
        "model": "gpt-test",
        "api_mode": "responses",
        "stream": True,
    }
    streamed = {
        "id": "resp",
        "model": "gpt-test",
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "streamed"}]}],
    }
    with patch.object(
        adapter,
        "_stream_request",
        new_callable=AsyncMock,
        return_value=(streamed, {"x-request-id": "request"}),
    ):
        result = await adapter.execute_openai_query(payload)
    assert result["output"] == "streamed"
    assert result["metadata"]["request_id"] == "request"
    result = await adapter.execute_openai_query({"api_key": "test", "model": "gpt-test"})
    assert result["status"] == "error"
    assert "no user" in result["message"]


@pytest.mark.asyncio
async def test_openai_sse_consumers_and_transport_error_paths() -> None:
    adapter = OpenAIAdapterPlugin()
    chat_response = MagicMock()
    chat_response.content = _AsyncLines(
        [
            b": keepalive\n",
            _sse_event(
                {
                    "id": "chat-1",
                    "model": "gpt",
                    "choices": [{"finish_reason": None, "delta": {"content": "hi"}}],
                }
            ),
            b"\n",
            _sse_event({"choices": [{"finish_reason": "stop", "delta": {"content": "!"}}]}),
            b"\n",
            b"data: [DONE]\n",
            b"\n",
        ]
    )
    assembled, headers = await adapter._consume_chat_stream(chat_response, {"x": "y"})
    assert headers == {"x": "y"}
    assert assembled["choices"][0]["message"]["content"] == "hi!"

    responses_response = MagicMock()
    responses_response.content = _AsyncLines(
        [
            _sse_event(
                {
                    "type": "response.created",
                    "response": {"id": "resp-1", "model": "gpt", "status": "in_progress"},
                }
            ),
            b"\n",
            _sse_event({"type": "response.output_text.delta", "delta": "hello"}),
            b"\n",
            _sse_event(
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "item-1",
                    "call_id": "call-1",
                    "name": "lookup",
                    "delta": '{"x":1}',
                }
            ),
            b"\n",
            b"data: [DONE]\n",
            b"\n",
        ]
    )
    assembled, _ = await adapter._consume_responses_stream(responses_response, {})
    assert assembled["output"][0]["content"][0]["text"] == "hello"
    assert assembled["output"][1]["name"] == "lookup"

    response = MagicMock()
    response.headers = {"x-request-id": "req"}
    response.status = 200
    response.json = AsyncMock(return_value={"ok": True})
    session = MagicMock()
    session.post.return_value = _ResponseContext(response)
    with patch.object(adapter, "get_session", new_callable=AsyncMock, return_value=session):
        data, result_headers = await adapter._post_json(
            "https://example.test", {}, {"_agentv_timeout": "2"}
        )
    assert data == {"ok": True}
    assert result_headers == {"x-request-id": "req"}

    error = MagicMock()
    error.headers = {}
    error.status = 401
    error.request_info = None
    error.history = ()
    error.json = AsyncMock(return_value={"error": {"message": "bad key"}})
    with pytest.raises(OpenAIAdapterError, match="bad key"):
        adapter._raise_http_error(response=error, data=await adapter._read_json_or_error(error))


@pytest.mark.asyncio
async def test_openai_http_and_sse_protocol_edge_contracts() -> None:
    adapter = OpenAIAdapterPlugin()
    assert adapter._resolve_timeout({}).total is not None
    assert adapter._resolve_timeout({"_agentv_timeout": "bad"}).total is not None
    response = MagicMock()
    response.content = _AsyncLines([b"data: not-json\n", b"\n", b"data: [DONE]\n", b"\n"])
    assert [event async for event in adapter._iter_sse_events(response)] == [{"__done__": True}]
    trailing = MagicMock()
    trailing.content = _AsyncLines([b'data: {"type":"event"}'])
    assert [event async for event in adapter._iter_sse_events(trailing)] == [{"type": "event"}]

    non_object = MagicMock()
    non_object.headers = {}
    non_object.status = 200
    non_object.json = AsyncMock(return_value=[])
    session = MagicMock()
    session.post.return_value = _ResponseContext(non_object)
    with patch.object(adapter, "get_session", new=AsyncMock(return_value=session)):
        with pytest.raises(OpenAIAdapterError, match="unexpected JSON type"):
            await adapter._post_json("https://example.test", {}, {})

    non_json = MagicMock()
    non_json.json = AsyncMock(side_effect=json.JSONDecodeError("bad", "", 0))
    non_json.text = AsyncMock(return_value="not-json")
    assert await adapter._read_json_or_error(non_json) == {"error": {"message": "not-json"}}
    error = MagicMock()
    error.status = 429
    error.request_info = None
    error.history = ()
    error.headers = {}
    with pytest.raises(aiohttp.ClientResponseError):
        adapter._raise_http_error(response=error, data={"error": {"message": "retry"}})

    streamed = MagicMock()
    streamed.headers = {"x-request-id": "r"}
    streamed.status = 200
    streamed.content = _AsyncLines([])
    session.post.return_value = _ResponseContext(streamed)
    chat_consumer = AsyncMock(return_value=({"choices": []}, {}))
    with (
        patch.object(adapter, "get_session", new=AsyncMock(return_value=session)),
        patch.object(adapter, "_consume_chat_stream", new=chat_consumer),
    ):
        data, _ = await adapter._stream_request("https://example.test", {}, {}, "chat_completions")
    assert data == {"choices": []}


@pytest.mark.asyncio
async def test_openai_stream_consumers_handle_tool_deltas_and_final_response() -> None:
    adapter = OpenAIAdapterPlugin()
    chat_response = MagicMock()
    chat_response.content = _AsyncLines(
        [
            _sse_event(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": "bad-index",
                                        "id": "call-1",
                                        "function": {"name": "look", "arguments": '{"q"'},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ),
            b"\n",
            _sse_event(
                {
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {"name": "up", "arguments": ":1}"},
                                    }
                                ]
                            },
                        }
                    ]
                }
            ),
            b"\n",
        ]
    )
    assembled, _ = await adapter._consume_chat_stream(chat_response, {})
    call = assembled["choices"][0]["message"]["tool_calls"][0]
    assert call["function"] == {"name": "lookup", "arguments": '{"q":1}'}

    final_response = {"id": "resp-final", "status": "completed", "output": []}
    responses_response = MagicMock()
    responses_response.content = _AsyncLines(
        [_sse_event({"type": "response.completed", "response": final_response}), b"\n"]
    )
    assembled, _ = await adapter._consume_responses_stream(responses_response, {})
    assert assembled == final_response


@pytest.mark.asyncio
async def test_openai_responses_stream_assembles_refusal_tool_and_terminal_events() -> None:
    adapter = OpenAIAdapterPlugin()
    response = MagicMock()
    response.content = _AsyncLines(
        [
            _sse_event({"type": "response.created", "response": {"id": "r", "model": "gpt"}}),
            b"\n",
            _sse_event({"type": "response.refusal.delta", "delta": "declined"}),
            b"\n",
            _sse_event(
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "item",
                    "id": "id",
                    "call_id": "call",
                    "name": "lookup",
                    "delta": "{}",
                }
            ),
            b"\n",
        ]
    )
    assembled, _ = await adapter._consume_responses_stream(response, {})
    assert assembled["output"][0]["type"] == "function_call"
    assert assembled["output"][1]["content"][0]["refusal"] == "declined"

    terminal = MagicMock()
    expected = {"id": "final", "status": "incomplete", "output": []}
    terminal.content = _AsyncLines(
        [_sse_event({"type": "response.incomplete", "response": expected}), b"\n"]
    )
    result, _ = await adapter._consume_responses_stream(terminal, {})
    assert result == expected

    generic_terminal = MagicMock()
    generic_expected = {"id": "failed", "status": "failed", "output": []}
    generic_terminal.content = _AsyncLines(
        [_sse_event({"type": "other", "response": generic_expected}), b"\n"]
    )
    result, _ = await adapter._consume_responses_stream(generic_terminal, {})
    assert result == generic_expected

    failed = MagicMock()
    failed_expected = {"id": "explicit", "status": "failed", "output": []}
    failed.content = _AsyncLines(
        [_sse_event({"type": "response.failed", "response": failed_expected}), b"\n"]
    )
    result, _ = await adapter._consume_responses_stream(failed, {})
    assert result == failed_expected


@pytest.mark.asyncio
async def test_openai_chat_stream_ignores_invalid_chunks_and_collects_usage() -> None:
    adapter = OpenAIAdapterPlugin()
    response = MagicMock()
    response.content = _AsyncLines(
        [
            _sse_event({"usage": {"total_tokens": 1}}),
            b"\n",
            _sse_event({"choices": ["bad"]}),
            b"\n",
            _sse_event({"choices": [{"delta": "bad"}]}),
            b"\n",
        ]
    )
    assembled, _ = await adapter._consume_chat_stream(response, {})
    assert assembled["usage"] == {"total_tokens": 1}


@pytest.mark.asyncio
async def test_openai_public_and_transport_error_contracts() -> None:
    adapter = OpenAIAdapterPlugin()
    with patch("eval_runner.adapters.openai.config.OPENAI_API_KEY", None):
        missing_key = await adapter.execute_openai_query({"task": "hello", "model": "gpt"})
    assert missing_key["metadata"]["error_type"] == "OpenAIAdapterError"

    payload = {"api_key": "key", "task": "hello", "model": "gpt"}
    with patch.object(adapter, "_post_json", new=AsyncMock(return_value=([], {}))):
        non_object = await adapter.execute_openai_query(payload)
    assert non_object["metadata"]["error_type"] == "OpenAIAdapterError"

    http_error = aiohttp.ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=500,
        message="unavailable",
        headers={"x-request-id": "r"},
    )
    with patch.object(adapter, "_post_json", new=AsyncMock(side_effect=http_error)):
        result = await adapter.execute_openai_query(payload)
    assert result["metadata"]["status_code"] == 500
    with patch.object(adapter, "_post_json", new=AsyncMock(side_effect=asyncio.CancelledError())):
        with pytest.raises(asyncio.CancelledError):
            await adapter.execute_openai_query(payload)

    failure = MagicMock()
    failure.headers = {}
    failure.status = 400
    failure.request_info = MagicMock()
    failure.history = ()
    failure.json = AsyncMock(return_value={"error": {"message": "bad"}})
    session = MagicMock()
    session.post.return_value = _ResponseContext(failure)
    with patch.object(adapter, "get_session", new=AsyncMock(return_value=session)):
        with pytest.raises(OpenAIAdapterError, match="HTTP 400"):
            await adapter._stream_request("https://example.test", {}, {}, "responses")

    tool_response = {
        "id": "response",
        "status": "completed",
        "output": [
            {"type": "function_call", "name": "lookup", "arguments": "{}", "call_id": "call"}
        ],
    }
    with patch.object(adapter, "_post_json", new=AsyncMock(return_value=(tool_response, {}))):
        tool_result = await adapter.execute_openai_query(payload)
    assert tool_result["metadata"]["tool_call_count"] == 1


@pytest.mark.asyncio
async def test_openai_adapter_telemetry():
    """Verify that OpenAI adapter emits token usage telemetry."""
    adapter = OpenAIAdapterPlugin()
    payload = {
        "api_key": "test",
        "task": "test task",
        "model": "gpt-test",
        "api_mode": "chat_completions",
    }

    mock_response_data = {
        "choices": [{"message": {"content": "Hello world"}}],
        "usage": {"total_tokens": 100, "prompt_tokens": 40, "completion_tokens": 60},
    }

    with patch.object(
        adapter,
        "_post_json",
        new_callable=AsyncMock,
        return_value=(mock_response_data, {}),
    ):
        with patch("eval_runner.adapters.openai.emit") as mock_emit:
            result = await adapter.execute_openai_query(payload)

            assert result["status"] == "success"
            assert result["output"] == "Hello world"

            # Verify telemetry emission
            mock_emit.assert_any_call(
                "metric_update",
                {
                    "adapter": "openai",
                    "provider": "openai",
                    "tokens": 100,
                    "prompt_tokens": 40,
                    "completion_tokens": 60,
                },
            )


@pytest.mark.asyncio
async def test_openai_adapter_error_handling():
    """Verify that OpenAI adapter handles and reports errors correctly."""
    adapter = OpenAIAdapterPlugin()
    payload = {"api_key": "test", "task": "test task", "api_mode": "chat_completions"}

    with patch.object(adapter, "_post_json", new_callable=AsyncMock) as post_json:
        post_json.side_effect = aiohttp.ClientResponseError(MagicMock(), (), status=401)
        result = await adapter.execute_openai_query(payload)

        assert result["status"] == "error"
        assert "401" in result["message"]
        assert post_json.await_count == 1
