"""Focused contract coverage for the native Anthropic Messages adapter."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from eval_runner.adapters.claude import ClaudeAdapterError, ClaudeAdapterPlugin


class _AsyncLines:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __aiter__(self):
        self._iterator = iter(self._lines)
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


def test_claude_boundary_resolution_and_request_construction() -> None:
    adapter = ClaudeAdapterPlugin()
    traceparent = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
    payload = {
        "api_key": "key",
        "model": "claude-test",
        "max_tokens": "12",
        "messages": [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "hello", "name": "removed"},
        ],
        "stream": True,
        "tools": [{"name": "lookup"}],
        "anthropic_betas": ["beta-a", "beta-b"],
        "anthropic_workspace_id": "workspace",
        "span_context": {"traceparent": traceparent},
    }
    request, model = adapter._build_request(payload)
    assert model == "claude-test"
    assert request["system"] == "rules"
    assert request["messages"] == [{"role": "user", "content": "hello"}]
    assert request["tools"] == [{"name": "lookup"}]
    headers = adapter._resolve_headers(payload, "key", stream=True)
    assert headers["accept"] == "text/event-stream"
    assert headers["anthropic-beta"] == "beta-a,beta-b"
    assert headers["traceparent"] == traceparent
    assert adapter._resolve_url({}, "https://example.test/v1") == "https://example.test/v1/messages"
    assert adapter._request_summary(request)["message_count"] == 1
    assert len(adapter._request_fingerprint(request)) == 64
    assert adapter._provider_request_id(None, {"x-request-id": "request"}) == "request"


def test_claude_normalizes_text_tool_calls_and_provider_errors() -> None:
    adapter = ClaudeAdapterPlugin()
    data = {
        "id": "msg-1",
        "type": "message",
        "model": "claude-test",
        "role": "assistant",
        "stop_reason": "tool_use",
        "content": [
            {"type": "text", "text": "checking"},
            {"type": "thinking", "thinking": "reason"},
            {"type": "tool_use", "id": "tool-1", "name": "lookup", "input": {"q": "x"}},
            {"type": "text", "citations": [{"source": "doc"}]},
        ],
        "usage": {"input_tokens": "2", "output_tokens": 3},
    }
    with patch("eval_runner.adapters.claude.emit") as emit:
        result = adapter._normalize_message_response(
            data, response_headers={"request-id": "request"}
        )
    assert result["action"] == "call_tool"
    assert result["tool_params"] == {"q": "x"}
    assert result["metadata"]["usage"]["total_tokens"] == 5
    assert result["metadata"]["request_id"] == "request"
    emit.assert_called_once()
    error = adapter._normalize_message_response(
        {"type": "error", "error": {"type": "invalid_request", "message": "bad"}}
    )
    assert error["status"] == "error"
    assert error["message"] == "bad"
    assert adapter._usage_metadata({"input_tokens": "bad", "output_tokens": 4})["total_tokens"] == 4
    with pytest.raises(ClaudeAdapterError, match="valid name"):
        adapter._extract_tool_calls([{"type": "tool_use", "input": {}}])


def test_claude_rejects_invalid_required_input() -> None:
    adapter = ClaudeAdapterPlugin()
    with pytest.raises(ClaudeAdapterError, match="no input"):
        adapter._resolve_messages({})
    with pytest.raises(ClaudeAdapterError, match="integer"):
        adapter._resolve_max_tokens({"max_tokens": "not-a-number"})
    with pytest.raises(ClaudeAdapterError, match="at least one"):
        adapter._build_request(
            {
                "api_key": "key",
                "model": "claude",
                "messages": [{"role": "system", "content": "rules"}],
            }
        )


def test_claude_boundary_validation_and_normalization_edge_cases() -> None:
    adapter = ClaudeAdapterPlugin()
    for payload, message in (
        ({"messages": "nope"}, "must be a list"),
        ({"messages": ["nope"]}, "must be an object"),
        ({"messages": [{"content": "x"}]}, "valid role"),
        ({"messages": [{"role": "tool", "content": "x"}]}, "Unsupported"),
        ({"messages": [{"role": "user"}]}, "required 'content'"),
    ):
        with pytest.raises(ClaudeAdapterError, match=message):
            adapter._resolve_messages(payload)
    with pytest.raises(ClaudeAdapterError, match="key missing"):
        adapter._resolve_auth({})
    with pytest.raises(ClaudeAdapterError, match="key is empty"):
        adapter._resolve_auth({"api_key": " "})
    with patch("eval_runner.adapters.claude.config.ANTHROPIC_MODEL", None):
        with pytest.raises(ClaudeAdapterError, match="model is required"):
            adapter._resolve_model({})
        with pytest.raises(ClaudeAdapterError, match="model is empty"):
            adapter._resolve_model({"model": " "})
    with pytest.raises(ClaudeAdapterError, match="greater than zero"):
        adapter._resolve_max_tokens({"max_tokens": 0})
    with pytest.raises(ClaudeAdapterError, match="string or content-block"):
        adapter._resolve_system_prompt({"system": 1}, [])
    assert adapter._resolve_url({}, "https://example.test/") == "https://example.test/v1/messages"
    assert (
        adapter._resolve_url({}, "https://example.test/v1/") == "https://example.test/v1/messages"
    )
    assert (
        adapter._resolve_headers(
            {"anthropic_beta": "beta", "anthropic_user_profile_id": "user"}, "key", stream=False
        )["anthropic-beta"]
        == "beta"
    )
    error = adapter._normalize_message_response({"type": "error", "error": "bad"})
    assert error["message"] == "bad"
    with pytest.raises(ClaudeAdapterError, match="valid 'content'"):
        adapter._normalize_message_response({"type": "message", "content": None})
    with pytest.raises(ClaudeAdapterError, match="non-object input"):
        adapter._extract_tool_calls([{"type": "tool_use", "name": "tool", "input": []}])
    multi = adapter._normalize_message_response(
        {
            "content": [
                {"type": "tool_use", "id": "one", "name": "one", "input": {}},
                {"type": "tool_use", "id": "two", "name": "two", "input": {}},
            ]
        }
    )
    assert multi["action"] == "call_multiple_tools"


def test_claude_static_helpers_cover_optional_and_failure_paths() -> None:
    adapter = ClaudeAdapterPlugin()
    registry = type("Registry", (), {"register": MagicMock()})()
    adapter.on_discover_adapters(registry)
    registry.register.assert_called_once()
    assert adapter._traceparent({"span_context": {"traceparent": "broken"}}) is None
    assert adapter._traceparent({"span_context": {"traceparent": 1}}) is None
    assert adapter._traceparent({"span_context": "broken"}) is None

    class _Unprintable:
        def __str__(self) -> str:
            raise TypeError("cannot serialize")

    with pytest.raises(ClaudeAdapterError, match="Unable to serialize"):
        adapter._resolve_messages({"task": _Unprintable()})
    assert (
        adapter._resolve_system_prompt(
            {}, [{"role": "system", "content": [{"type": "text", "text": "rules"}]}]
        )
        == "rules"
    )
    headers = adapter._resolve_headers(
        {"metadata": {"anthropic_workspace_id": "workspace"}}, "key", stream=False
    )
    assert headers["anthropic-workspace-id"] == "workspace"
    assert adapter._provider_request_id({"request_id": "body"}) == "body"
    assert adapter._provider_request_id(None, {"anthropic-request-id": "header"}) == "header"
    assert adapter._extract_text(["ignored", {"type": "text", "text": "ok"}]) == "ok"
    assert adapter._extract_thinking(["ignored", {"type": "thinking", "thinking": "x"}])
    assert adapter._extract_citations(["ignored", {"citations": [{"source": "x"}]}])
    assert adapter._extract_tool_calls(["ignored"]) == []
    with pytest.raises(ClaudeAdapterError, match="non-object response"):
        adapter._normalize_message_response([])  # type: ignore[arg-type]
    with pytest.raises(ClaudeAdapterError, match="thinking content"):
        adapter._normalize_message_response({"content": [{"type": "thinking", "thinking": "x"}]})
    with pytest.raises(ClaudeAdapterError, match="neither usable"):
        adapter._normalize_message_response({"content": []})
    assert (
        adapter._resolve_system_prompt({"metadata": {"system_prompt": "metadata rules"}}, [])
        == "metadata rules"
    )
    assert adapter._resolve_system_prompt(
        {},
        [
            {"role": "system", "content": "one"},
            {"role": "system", "content": "two"},
        ],
    ) == [
        {"type": "text", "text": "one"},
        {"type": "text", "text": "two"},
    ]
    with pytest.raises(ClaudeAdapterError, match="endpoint is empty"):
        adapter._resolve_url({}, " ")
    assert adapter._provider_request_id(None, {"x-request-id": "header"}) == "header"


def test_claude_sse_aggregation_reconstructs_text_tool_usage_and_diagnostics() -> None:
    adapter = ClaudeAdapterPlugin()
    message, diagnostics = adapter._aggregate_sse_events(
        [
            (
                "message_start",
                {
                    "message": {
                        "id": "msg-1",
                        "request_id": "request-1",
                        "usage": {"input_tokens": 2},
                    }
                },
            ),
            ("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": "hello"}}),
            (
                "content_block_start",
                {"index": 1, "content_block": {"type": "tool_use", "name": "lookup"}},
            ),
            (
                "content_block_delta",
                {
                    "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": '{"q":"x"}'},
                },
            ),
            ("content_block_stop", {"index": 1}),
            (
                "message_delta",
                {"delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 3}},
            ),
            ("message_stop", {}),
        ]
    )
    assert diagnostics == {"request_id": "request-1"}
    assert message["content"][0]["text"] == "hello"
    assert message["content"][1]["input"] == {"q": "x"}
    assert message["usage"] == {"input_tokens": 2, "output_tokens": 3}
    with pytest.raises(ClaudeAdapterError, match="never emitted"):
        adapter._aggregate_sse_events([("message_stop", {})])
    with pytest.raises(ClaudeAdapterError, match="streaming API error"):
        adapter._aggregate_sse_events([("error", {})])


def test_claude_sse_aggregation_covers_thinking_signature_and_citations() -> None:
    adapter = ClaudeAdapterPlugin()
    message, _ = adapter._aggregate_sse_events(
        [
            ("message_start", {"message": {}}),
            ("content_block_start", {"index": 0, "content_block": {}}),
            (
                "content_block_delta",
                {"index": 0, "delta": {"type": "thinking_delta", "thinking": "reason"}},
            ),
            (
                "content_block_delta",
                {"index": 0, "delta": {"type": "signature_delta", "signature": "sig"}},
            ),
            (
                "content_block_delta",
                {"index": 0, "delta": {"type": "citations_delta", "citation": {"source": "doc"}}},
            ),
            ("content_block_stop", {"index": 0}),
            ("message_stop", {}),
        ]
    )
    assert message["content"] == [
        {
            "type": "thinking",
            "thinking": "reason",
            "signature": "sig",
            "citations": [{"source": "doc"}],
        }
    ]
    with pytest.raises(ClaudeAdapterError, match="ended without"):
        adapter._aggregate_sse_events([("message_start", {"message": {}})])


def test_claude_sse_rejects_invalid_protocol_events() -> None:
    adapter = ClaudeAdapterPlugin()
    invalid_cases = (
        ([("content_block_delta", {"index": "0", "delta": {}})], "invalid content_block_delta"),
        ([("content_block_stop", {"index": 0})], "unknown content block"),
        (
            [
                ("message_start", {"message": {}}),
                (
                    "content_block_delta",
                    {"index": 0, "delta": {"type": "input_json_delta", "partial_json": 2}},
                ),
            ],
            "non-string",
        ),
        (
            [
                ("message_start", {"message": {}}),
                (
                    "content_block_delta",
                    {"index": 0, "delta": {"type": "citations_delta", "citation": []}},
                ),
            ],
            "non-object citation",
        ),
        ([("message_start", {"message": {}}), ("unsupported", {})], "unsupported SSE"),
    )
    for events, message in invalid_cases:
        with pytest.raises(ClaudeAdapterError, match=message):
            adapter._aggregate_sse_events(events)
    with pytest.raises(ClaudeAdapterError, match="malformed tool input"):
        adapter._aggregate_sse_events(
            [
                ("message_start", {"message": {}}),
                ("content_block_start", {"index": 0, "content_block": {}}),
                (
                    "content_block_delta",
                    {"index": 0, "delta": {"type": "input_json_delta", "partial_json": "{"}},
                ),
                ("content_block_stop", {"index": 0}),
            ]
        )
    with pytest.raises(ClaudeAdapterError, match="no events"):
        adapter._aggregate_sse_events([])
    with pytest.raises(ClaudeAdapterError, match="failure"):
        adapter._aggregate_sse_events(
            [("error", {"error": {"message": "failure"}, "request_id": "r"})]
        )
    message, _ = adapter._aggregate_sse_events(
        [
            ("ping", {}),
            ("message_start", {"message": "ignored"}),
            ("content_block_start", {"index": "ignored", "content_block": {}}),
            ("message_delta", {"delta": {"stop_sequence": "END", "stop_details": {"a": 1}}}),
            ("message_stop", {}),
        ]
    )
    assert message["stop_sequence"] == "END"


@pytest.mark.asyncio
async def test_claude_sse_reader_parses_framing_and_rejects_malformed_events() -> None:
    adapter = ClaudeAdapterPlugin()
    response = type("Response", (), {})()
    response.content = _AsyncLines(
        [
            b": keepalive\n",
            b"event: message_start\n",
            b'data: {"message":{"id":"msg-1","usage":{"input_tokens":1}}}\n',
            b"\n",
            b"event: content_block_start\n",
            b'data: {"index":0,"content_block":{"type":"text","text":"ok"}}\n',
            b"\n",
            b"event: message_stop\n",
            b"data: {}\n",
            b"\n",
        ]
    )
    message, diagnostics = await adapter._read_stream(response)
    assert message["content"] == [{"type": "text", "text": "ok"}]
    assert diagnostics == {}

    invalid = type("Response", (), {"content": _AsyncLines([b"data: not-json\n", b"\n"])})()
    with pytest.raises(ClaudeAdapterError, match="invalid JSON"):
        await adapter._read_stream(invalid)

    trailing = type(
        "Response",
        (),
        {
            "content": _AsyncLines(
                [
                    b"event: message_start\n",
                    b'data: {"message":{}}\n',
                    b"\n",
                    b"event: message_stop\n",
                    b"data: {}",
                ]
            )
        },
    )()
    parsed, _ = await adapter._read_stream(trailing)
    assert parsed["content"] == []
    non_object = type("Response", (), {"content": _AsyncLines([b"data: []\n", b"\n"])})()
    with pytest.raises(ClaudeAdapterError, match="must decode to an object"):
        await adapter._read_stream(non_object)


@pytest.mark.asyncio
async def test_claude_http_reader_stream_and_public_wrapper_validation() -> None:
    adapter = ClaudeAdapterPlugin()
    empty = type("Response", (), {"read": AsyncMock(return_value=b""), "charset": "utf-8"})()
    assert await adapter._read_error_body(empty) == ("", None)
    text = type("Response", (), {"read": AsyncMock(return_value=b"not json"), "charset": None})()
    assert await adapter._read_error_body(text) == ("not json", None)
    assert adapter._extract_error_message(500, " body ", None) == "body"
    assert adapter._extract_error_message(500, "", {}) == "Anthropic API returned HTTP 500."

    response = type("Response", (), {})()
    response.headers = {}
    response.status = 200
    response.json = AsyncMock(return_value=[])
    session = type("Session", (), {"post": lambda *_args, **_kwargs: _ResponseContext(response)})()
    with patch.object(adapter, "get_session", new=AsyncMock(return_value=session)):
        with pytest.raises(ClaudeAdapterError, match="non-object JSON"):
            await adapter._post("https://example.test", {}, {}, stream=False, timeout_seconds=1)

    stream_reader = AsyncMock(return_value=({"content": []}, {"x": "y"}))
    with patch.object(adapter, "_read_stream", new=stream_reader):
        response.content = _AsyncLines([])
        with patch.object(adapter, "get_session", new=AsyncMock(return_value=session)):
            wrapper = await adapter._post(
                "https://example.test", {}, {}, stream=True, timeout_seconds=1
            )
    assert wrapper["__stream_diagnostics__"] == {"x": "y"}

    payload = {"api_key": "key", "model": "claude", "task": "hi"}
    with patch.object(adapter, "_post", new=AsyncMock(return_value={"__claude_response__": []})):
        result = await adapter.execute_claude_query(payload)
    assert result["metadata"]["error_type"] == "ClaudeAdapterError"
    with patch.object(adapter, "_post", new=AsyncMock(side_effect=RuntimeError("boom"))):
        result = await adapter.execute_claude_query(payload)
    assert result["metadata"]["error_type"] == "RuntimeError"
    invalid_payload = await adapter.execute_claude_query([])  # type: ignore[arg-type]
    assert invalid_payload["status"] == "error"


@pytest.mark.asyncio
async def test_claude_remaining_stream_and_execution_failure_contracts() -> None:
    adapter = ClaudeAdapterPlugin()
    with pytest.raises(ClaudeAdapterError, match="trailing JSON"):
        await adapter._read_stream(type("Response", (), {"content": _AsyncLines([b"data: bad"])})())
    failed_read = type(
        "Response",
        (),
        {"read": AsyncMock(side_effect=aiohttp.ClientError("closed")), "charset": None},
    )()
    assert await adapter._read_error_body(failed_read) == ("closed", None)

    malformed = type("Response", (), {})()
    malformed.headers = {}
    malformed.status = 200
    malformed.json = AsyncMock(side_effect=json.JSONDecodeError("invalid", "", 0))
    session = type("Session", (), {"post": lambda *_args, **_kwargs: _ResponseContext(malformed)})()
    with patch.object(adapter, "get_session", new=AsyncMock(return_value=session)):
        with pytest.raises(ClaudeAdapterError, match="non-JSON"):
            await adapter._post("https://example.test", {}, {}, stream=False, timeout_seconds=1)

    payload = {"api_key": "key", "model": "claude", "task": "hi", "timeout": "invalid"}
    malformed_stream = AsyncMock(return_value={"__claude_stream_result__": None})
    with patch.object(adapter, "_post", new=malformed_stream):
        result = await adapter.execute_claude_query({**payload, "stream": True})
    assert result["metadata"]["error_type"] == "ClaudeAdapterError"
    with patch.object(
        adapter,
        "_post",
        new=AsyncMock(return_value={"__claude_response__": {"type": "error", "error": "bad"}}),
    ):
        result = await adapter.execute_claude_query(payload)
    assert result["status"] == "error"

    with patch.object(adapter, "_post", new=AsyncMock(side_effect=asyncio.CancelledError())):
        with pytest.raises(asyncio.CancelledError):
            await adapter.execute_claude_query(payload)


@pytest.mark.asyncio
async def test_claude_post_and_public_execution_cover_success_and_http_error() -> None:
    adapter = ClaudeAdapterPlugin()
    response = type("Response", (), {})()
    response.headers = {"request-id": "request-1"}
    response.status = 200
    response.json = AsyncMock(
        return_value={
            "id": "msg-1",
            "type": "message",
            "model": "claude-test",
            "content": [{"type": "text", "text": "CERTIFIED"}],
        }
    )
    session = type("Session", (), {})()
    session.post = lambda *_args, **_kwargs: _ResponseContext(response)
    with patch.object(adapter, "get_session", new=AsyncMock(return_value=session)):
        wrapper = await adapter._post(
            "https://example.test/v1/messages",
            {},
            {"model": "claude-test"},
            stream=False,
            timeout_seconds=2,
        )
    assert wrapper["__claude_response__"]["id"] == "msg-1"

    with patch.object(adapter, "_post", new=AsyncMock(return_value=wrapper)):
        result = await adapter.execute_claude_query(
            {"api_key": "key", "model": "claude-test", "task": "hello"}
        )
    assert result["status"] == "success"
    assert result["output"] == "CERTIFIED"

    error = type("Response", (), {})()
    error.headers = {"request-id": "request-2"}
    error.status = 429
    error.request_info = SimpleNamespace(real_url="https://example.test/v1/messages")
    error.history = ()
    error.charset = "utf-8"
    error.read = AsyncMock(return_value=b'{"error":{"message":"slow down"}}')
    error_session = type("Session", (), {})()
    error_session.post = lambda *_args, **_kwargs: _ResponseContext(error)
    with patch.object(adapter, "get_session", new=AsyncMock(return_value=error_session)):
        with pytest.raises(aiohttp.ClientResponseError, match="slow down"):
            await adapter._post(
                "https://example.test/v1/messages",
                {},
                {},
                stream=False,
                timeout_seconds=2,
            )


@pytest.mark.asyncio
async def test_claude_public_execution_normalizes_transport_and_provider_errors() -> None:
    adapter = ClaudeAdapterPlugin()
    payload = {"api_key": "key", "model": "claude-test", "task": "hello"}
    http_error = aiohttp.ClientResponseError(
        request_info=SimpleNamespace(real_url="https://example.test"),
        history=(),
        status=429,
        message="rate limited",
        headers={"request-id": "request"},
    )
    with patch.object(adapter, "_post", new=AsyncMock(side_effect=http_error)):
        result = await adapter.execute_claude_query(payload)
    assert result["metadata"]["retryable"] is True
    with patch.object(adapter, "_post", new=AsyncMock(side_effect=TimeoutError("late"))):
        result = await adapter.execute_claude_query(payload)
    assert result["metadata"]["error_type"] == "TimeoutError"


@pytest.mark.asyncio
async def test_claude_execute_non_stream_stream_and_http_error_contracts() -> None:
    adapter = ClaudeAdapterPlugin()
    payload = {"api_key": "key", "model": "claude-test", "task": "hello"}
    response = {
        "id": "msg-1",
        "type": "message",
        "model": "claude-test",
        "role": "assistant",
        "content": [{"type": "text", "text": "CERTIFIED"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    with patch.object(
        adapter,
        "_post",
        new=AsyncMock(return_value={"__claude_response__": response, "__response_headers__": {}}),
    ):
        result = await adapter.execute_claude_query(payload)
    assert result["status"] == "success"
    assert result["metadata"]["streaming"] is False

    stream_payload = {**payload, "stream": True}
    with patch.object(
        adapter,
        "_post",
        new=AsyncMock(
            return_value={
                "__claude_stream_result__": response,
                "__response_headers__": {},
                "__stream_diagnostics__": {"request_id": "stream-request"},
            }
        ),
    ):
        streamed = await adapter.execute_claude_query(stream_payload)
    assert streamed["metadata"]["streaming"] is True
    assert streamed["metadata"]["request_id"] == "stream-request"


@pytest.mark.asyncio
async def test_claude_post_decodes_success_and_surfaces_provider_error() -> None:
    adapter = ClaudeAdapterPlugin()
    success = type("Response", (), {})()
    success.headers = {"request-id": "request-1"}
    success.status = 200
    success.json = AsyncMock(return_value={"type": "message", "content": []})
    session = type("Session", (), {})()
    session.post = lambda *_args, **_kwargs: _ResponseContext(success)
    with patch.object(adapter, "get_session", new=AsyncMock(return_value=session)):
        wrapped = await adapter._post(
            "https://example.test/v1/messages", {}, {}, stream=False, timeout_seconds=1
        )
    assert wrapped["__claude_response__"]["type"] == "message"

    failure = type("Response", (), {})()
    failure.headers = {"request-id": "request-2"}
    failure.status = 429
    failure.request_info = SimpleNamespace(real_url="https://example.test/v1/messages")
    failure.history = ()
    failure.charset = "utf-8"
    failure.read = AsyncMock(return_value=b'{"error":{"message":"rate limited"}}')
    session.post = lambda *_args, **_kwargs: _ResponseContext(failure)
    with (
        patch.object(adapter, "get_session", new=AsyncMock(return_value=session)),
        pytest.raises(aiohttp.ClientResponseError, match="rate limited"),
    ):
        await adapter._post(
            "https://example.test/v1/messages",
            {},
            {},
            stream=False,
            timeout_seconds=1,
        )
