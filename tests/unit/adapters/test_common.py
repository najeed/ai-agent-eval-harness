"""
Canonical test suite for eval_runner/adapters/common.py.

Covers:
  SessionManager: singleton, close_all (open session, None state), reopen after close
  BaseAdapter.call_with_retry: HTTP retry codes (503/429/502), exhaustion, non-transient
    401 not retried, TimeoutError retry + exhaustion, ClientConnectorError retry +
    exhaustion, generic ValueError not retried
  AESCallbackHandler: on_chain_start (normal, serialization error), on_chain_end,
    on_node_start (dict with id, non-dict, dict without id), on_node_end,
    on_llm_start, on_llm_end (with usage, no usage, no llm_output attr)
  DualNormalizationHub.normalize_text: HITL priority, polling, error, terminal, default
  DualNormalizationHub.normalize: override (match, invalid action, no match, non-status
    key), schema (valid, invalid, absent field, default field), HTTP 4xx, heuristic
    (all primary keys, secondary substring scan, no match, emit on non-final)
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from eval_runner.adapters.common import (
    AdapterExecutionContext,
    AdapterRetryError,
    AdapterSessionPool,
    AESCallbackHandler,
    BaseAdapter,
    DualNormalizationHub,
    SessionManager,
    bounded_text,
    build_request_headers,
    canonical_json,
    coerce_timeout,
    is_mapping,
    is_retryable_http_status,
    iter_sse_events,
    json_safe,
    read_response_bytes,
    read_response_json,
    read_response_text,
    redact_mapping,
    request_json,
    retry_after_seconds,
    serialize_json_bytes,
    traceparent_from_payload,
    validate_http_endpoint,
)


def test_common_serialization_and_timeout_utilities() -> None:
    class Model:
        def model_dump(self, *, mode: str) -> dict[str, object]:
            assert mode == "json"
            return {"value": {"nested": "ok"}}

    assert is_mapping({})
    assert not is_mapping([])
    assert coerce_timeout("2.5", default=10) == 2.5
    assert coerce_timeout(0, default=10) == 10
    assert coerce_timeout("invalid", default=10) == 10
    assert json_safe(Model()) == {"value": {"nested": "ok"}}
    assert json_safe({"x": [1, 2]}) == {"x": [1, 2]}
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert serialize_json_bytes({"a": "é"}) == b'{"a":"\xc3\xa9"}'
    assert bounded_text("éé", max_bytes=3) == "é�"


@pytest.mark.parametrize("endpoint", ["", "ftp://example.com", "http:///missing-host"])
def test_validate_http_endpoint_rejects_invalid_values(endpoint: str) -> None:
    with pytest.raises(ValueError):
        validate_http_endpoint(endpoint)


def test_headers_trace_context_redaction_and_retry_after() -> None:
    traceparent = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
    payload = {"span_context": {"traceparent": traceparent}}

    assert traceparent_from_payload(payload) == traceparent
    assert traceparent_from_payload({"span_context": {"traceparent": "invalid"}}) is None
    headers = build_request_headers(
        payload,
        headers={"X-Test": "value", "X-Unsafe": "line\nbreak"},
        accept="application/json",
        content_type="application/json",
    )
    assert headers == {
        "traceparent": traceparent,
        "X-Test": "value",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    assert redact_mapping({"token": "secret", "nested": {"safe": "ok"}})["token"] == "<redacted>"
    assert retry_after_seconds(SimpleNamespace(headers={"Retry-After": "2"})) == 2.0
    assert retry_after_seconds(SimpleNamespace(headers={"Retry-After": "invalid"})) is None


def test_execution_context_and_callback_error_tool_contracts() -> None:
    pool = MagicMock()
    context = AdapterExecutionContext(
        pool=pool,
        payload={"headers": {"X-Request": "ok"}, "task": "run"},
        metadata={"openai": {"model": "metadata-model"}},
        span_context={"traceparent": "trace"},
        timeout="2",
    )
    assert context.timeout == 2.0
    assert context.request_headers == {"X-Request": "ok"}
    assert context.provider_config("openai") == {
        "model": "metadata-model",
        "headers": {"X-Request": "ok"},
        "task": "run",
    }

    callback = AESCallbackHandler("langgraph", "graph", {"trace": "context"})
    with patch("eval_runner.adapters.common.emit") as emit:
        callback.on_chain_error(ValueError("chain"))
        callback.on_node_error(ValueError("node"))
        callback.on_llm_error(ValueError("llm"))
        callback.on_tool_start({"name": "lookup"}, "secret input")
        callback.on_tool_end({"ok": True})
        callback.on_tool_error(ValueError("tool"))
        callback.on_agent_action(SimpleNamespace(tool="lookup", tool_input={"q": "x"}))
        callback.on_agent_finish(SimpleNamespace(return_values={"done": True}))
    assert emit.call_count == 8
    assert all(call.kwargs["span_context"] == {"trace": "context"} for call in emit.call_args_list)


def test_common_utility_failure_and_fallback_paths() -> None:
    class BrokenModel:
        def __str__(self) -> str:
            return "broken-model"

        def model_dump(self, *, mode: str) -> object:
            raise RuntimeError(mode)

        def dict(self) -> object:
            raise RuntimeError("dict")

    assert json_safe(BrokenModel()) == "broken-model"
    assert json_safe({"deep": {"more": "value"}}, max_depth=1) == {"deep": "<max-depth>"}
    assert redact_mapping({"values": list(range(1002))})["values"][-1] == 999
    assert validate_http_endpoint(" https://example.test/path ") == "https://example.test/path"
    assert is_mapping(SimpleNamespace()) is False


def test_callback_and_normalizer_remaining_contract_branches() -> None:
    callback = AESCallbackHandler("adapter", "id")
    assert callback._safe_type_summary(None) == "NoneType"
    assert callback._summarize_inputs([1, "two"]) == {
        "container": "list",
        "length": 2,
        "item_types": ["int", "str"],
    }
    assert callback._extract_usage(
        SimpleNamespace(response_metadata={"usage": {"input_tokens": 2, "output_token_count": 3}})
    ) == {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}
    with patch("eval_runner.adapters.common.canonical_json", side_effect=ValueError("bad")):
        assert callback._state_hash_and_summary({"x": 1}) == (
            None,
            {"error": "serialization_failed"},
        )
    with patch("eval_runner.adapters.common.emit") as emit:
        callback.on_node_start({"id": ["graph", "node"]}, [1])
        callback.on_node_start({"name": "named"}, {})
        callback.on_llm_start({"id": "model"}, [])
    assert emit.call_count == 3

    assert DualNormalizationHub.normalize(None) == "error"
    assert DualNormalizationHub.normalize(["not-a-mapping"]) == "error"
    assert DualNormalizationHub.normalize({"content": ""}) == "final_answer"
    assert DualNormalizationHub.normalize({"answer": 0}) == "final_answer"
    assert DualNormalizationHub.normalize({"other_status": "processing"}) == "processing"
    assert (
        DualNormalizationHub.normalize({"status": "waiting"}, overrides={"waiting": "hitl_pause"})
        == "hitl_pause"
    )
    assert (
        DualNormalizationHub.normalize(
            {"phase": "done"}, schema={"status_field": "phase", "mapping": {"done": "completed"}}
        )
        == "completed"
    )


@pytest.mark.asyncio
async def test_common_remaining_utility_and_lifecycle_boundaries() -> None:
    assert traceparent_from_payload(None) is None
    assert traceparent_from_payload({"span_context": {"traceparent": 3}}) is None
    zero_traceparent = "00-" + "0" * 32 + "-0123456789abcdef-01"
    assert traceparent_from_payload({"span_context": {"traceparent": zero_traceparent}}) is None
    assert build_request_headers(headers={2: "ignored", "X-Int": 3}) == {"X-Int": "3"}
    assert redact_mapping({"nested": {"value": "x"}}, max_depth=1) == {"nested": "<max-depth>"}
    assert retry_after_seconds(SimpleNamespace(headers={})) is None
    assert retry_after_seconds(SimpleNamespace(headers={"X-Other": "value"})) is None
    retry_date = SimpleNamespace(headers={"Retry-After": "Sun, 06 Nov 1994 08:49:37 GMT"})
    assert retry_after_seconds(retry_date) == 0.0
    assert not is_retryable_http_status("bad")

    with pytest.raises(RuntimeError, match="valid UTF-8"):
        await read_response_json(SimpleNamespace(content=_Chunks([b"\xff"])))

    async def sse_chunks():
        yield b"retry: 100\n"
        yield b"data: final\n"

    assert [event async for event in iter_sse_events(sse_chunks())] == [
        {"event": "message", "id": "", "retry": "100", "data": "final"}
    ]

    SessionManager.reset()
    assert isinstance(SessionManager.pool(), AdapterSessionPool)
    injected = MagicMock()
    injected.get_session = AsyncMock(return_value="session")
    adapter = BaseAdapter("injected", session_pool=injected)
    assert adapter.get_pool() is injected
    assert await adapter.get_session() == "session"
    with pytest.raises(ValueError, match="non-empty"):
        BaseAdapter(" ")


@pytest.mark.asyncio
async def test_common_remaining_bounded_pool_retry_and_callback_branches() -> None:
    with pytest.raises(ValueError, match="not a valid URL"):
        validate_http_endpoint("http://[bad")
    assert build_request_headers(headers={"X-Large": "x" * 20000})["X-Large"]
    short_traceparent = {"span_context": {"traceparent": "00-short-0123456789abcdef-01"}}
    invalid_hex_traceparent = {
        "span_context": {"traceparent": "zz-0123456789abcdef0123456789abcdef-0123456789abcdef-01"}
    }
    assert traceparent_from_payload(short_traceparent) is None
    assert traceparent_from_payload(invalid_hex_traceparent) is None
    assert retry_after_seconds(SimpleNamespace(headers={"Retry-After": " "})) is None
    assert retry_after_seconds(SimpleNamespace(headers={"Retry-After": "invalid-date"})) is None

    assert await read_response_bytes(SimpleNamespace(content=_Chunks([b"", b"ok"]))) == b"ok"

    bad_utf8 = SimpleNamespace(content=_Chunks([b"\xff"]), headers={}, status=200)
    bad_utf8.request_info = None
    bad_utf8.history = ()
    bad_utf8.reason = "ok"
    with pytest.raises(RuntimeError, match="valid UTF-8"):
        await request_json(
            _RequestPool(bad_utf8), method="GET", url="https://example.test", max_attempts=1
        )
    bad_json = SimpleNamespace(content=_Chunks([b"nope"]), headers={}, status=200)
    bad_json.request_info = None
    bad_json.history = ()
    bad_json.reason = "ok"
    with pytest.raises(RuntimeError, match="valid JSON"):
        await request_json(
            _RequestPool(bad_json), method="GET", url="https://example.test", max_attempts=1
        )

    async def sse_edges():
        yield b""
        yield b"event: edge\n"
        yield b"id: event-1\nretry: 7\ndata: tail"

    assert [event async for event in iter_sse_events(sse_edges())] == [
        {"event": "edge", "id": "event-1", "retry": "7", "data": "tail"}
    ]

    pool = AdapterSessionPool()
    assert pool._current_loop() is not None
    assert pool._session_loop(None) is None
    closed = MagicMock(closed=True)
    assert not pool._is_usable(closed, None)
    failing = MagicMock(closed=False)
    failing.close = AsyncMock(side_effect=RuntimeError("close"))
    await pool._close_session(failing)
    timeout = aiohttp.ClientTimeout(total=3)
    explicit_timeout_pool = AdapterSessionPool(timeout=timeout)
    assert explicit_timeout_pool._timeout is timeout

    adapter = BaseAdapter("branches")
    assert adapter._backoff_seconds(1, base_delay=0, max_delay=1) == 0
    assert adapter._is_retryable_exception(TimeoutError(), set())
    assert not adapter._is_retryable_exception(ValueError(), set())
    callback = AESCallbackHandler("adapter", "id")
    assert callback._summarize_inputs(object()) == "object"
    callback.on_node_start({"id": "node"}, {})
    callback.on_tool_start({}, "input")
    assert DualNormalizationHub.normalize_text(None) == "error"
    assert DualNormalizationHub.validate_action(None) is None


class _Chunks:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int):
        for chunk in self._chunks:
            yield chunk


class _ResponseContext:
    def __init__(self, response: object) -> None:
        self.response = response
        self.exited = False

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *_args: object) -> bool:
        self.exited = True
        return False


class _RequestPool:
    def __init__(self, response: object) -> None:
        self.context = _ResponseContext(response)
        self.calls: list[tuple[object, ...]] = []

    def session_request(self, *args: object, **kwargs: object) -> _ResponseContext:
        self.calls.append((*args, kwargs))
        return self.context


@pytest.mark.asyncio
async def test_bounded_response_readers_and_sse_parser() -> None:
    response = SimpleNamespace(content=_Chunks([b'{"value":', b" 1}"]))
    assert await read_response_bytes(response, max_bytes=32) == b'{"value": 1}'
    assert await read_response_text(SimpleNamespace(content=_Chunks([b"text"]))) == "text"
    json_response = SimpleNamespace(content=_Chunks([b'{"ok":true}']))
    assert await read_response_json(json_response) == {"ok": True}
    assert await read_response_json(SimpleNamespace(content=_Chunks([])), allow_empty=True) is None

    async def events():
        yield b": comment\n"
        yield b"event: update\nid: 7\ndata: first\ndata: second\n\n"
        yield b"data: tail\n"

    assert [event async for event in iter_sse_events(events())] == [
        {"event": "update", "id": "7", "retry": "", "data": "first\nsecond"},
        {"event": "message", "id": "", "retry": "", "data": "tail"},
    ]


@pytest.mark.asyncio
async def test_bounded_response_readers_reject_invalid_or_oversized_bodies() -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        await read_response_bytes(SimpleNamespace(content=_Chunks([])), max_bytes=0)
    with pytest.raises(RuntimeError, match="exceeded"):
        await read_response_bytes(SimpleNamespace(content=_Chunks([b"abcd"])), max_bytes=3)
    with pytest.raises(RuntimeError, match="empty"):
        await read_response_json(SimpleNamespace(content=_Chunks([])))
    with pytest.raises(RuntimeError, match="valid JSON"):
        await read_response_json(SimpleNamespace(content=_Chunks([b"not json"])))

    async def too_large_event():
        yield b"data: abcdef\n"

    with pytest.raises(RuntimeError, match="SSE event exceeded"):
        _ = [event async for event in iter_sse_events(too_large_event(), max_event_bytes=2)]


@pytest.mark.asyncio
async def test_session_pool_lifecycle_request_context_and_retry_boundaries() -> None:
    pool = AdapterSessionPool(connection_limit=0, dns_cache_ttl=-1, keepalive_timeout=-1)
    loop = __import__("asyncio").get_running_loop()
    response = object()
    request_context = _ResponseContext(response)
    session = MagicMock(closed=False, _loop=loop)
    session.request.return_value = request_context
    session.close = AsyncMock()
    with patch.object(pool, "_build_session", return_value=session):
        assert await pool.get_session() is session
        async with pool.session_request("GET", "https://example.test", marker=True) as actual:
            assert actual is response
        session.request.assert_called_once_with("GET", "https://example.test", marker=True)
        session.request = AsyncMock(return_value=response)
        assert await pool.request("POST", "https://example.test") is response
        await pool.close()
    session.close.assert_awaited_once()
    assert pool.session is None

    adapter = BaseAdapter("retry")
    with pytest.raises(ValueError, match="max_attempts"):
        await adapter.call_with_retry(AsyncMock(), max_attempts=0)
    timeout = AsyncMock(side_effect=TimeoutError("temporary"))
    with (
        patch.object(adapter, "_backoff_seconds", return_value=0),
        pytest.raises(AdapterRetryError),
    ):
        await adapter.call_with_retry(timeout, max_attempts=2, deadline=0)


@pytest.mark.asyncio
async def test_request_json_builds_bounded_request_and_surfaces_http_error() -> None:
    response = SimpleNamespace(
        content=_Chunks([b'{"answer":42}']),
        headers={"X-Result": "yes"},
        status=201,
        request_info=None,
        history=(),
        reason="created",
    )
    pool = _RequestPool(response)
    decoded, status, headers = await request_json(
        pool,
        method="POST",
        url="https://example.test/v1",
        payload={"q": 1},
        headers={"X-Test": 1},
        cookies={"cookie": 2},
        expected_statuses={201},
        max_attempts=1,
    )
    assert (decoded, status, headers) == ({"answer": 42}, 201, {"X-Result": "yes"})
    assert pool.context.exited
    assert pool.calls[0][0:2] == ("POST", "https://example.test/v1")
    request_kwargs = pool.calls[0][2]
    assert request_kwargs["json"] == {"q": 1}
    assert request_kwargs["headers"] == {"X-Test": "1"}
    assert request_kwargs["cookies"] == {"cookie": "2"}

    error_response = SimpleNamespace(
        content=_Chunks([b'{"error":"no"}']),
        headers={},
        status=400,
        request_info=None,
        history=(),
        reason="bad request",
    )
    with pytest.raises(aiohttp.ClientResponseError) as exc:
        await request_json(
            _RequestPool(error_response),
            method="GET",
            url="https://example.test",
            max_attempts=1,
        )
    assert exc.value.status == 400


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_manager_singleton():
    """SessionManager returns the same session instance on repeated calls."""
    session1 = await SessionManager.get_session()
    session2 = await SessionManager.get_session()
    assert session1 is session2
    assert not session1.closed
    await SessionManager.close_all()
    assert session1.closed
    assert SessionManager._session is None


@pytest.mark.asyncio
async def test_session_manager_close_all_when_none():
    """close_all() is idempotent when _session is already None."""
    SessionManager._session = None
    await SessionManager.close_all()
    assert SessionManager._session is None


@pytest.mark.asyncio
async def test_session_manager_reopens_after_close():
    """A new session is created after close_all()."""
    s1 = await SessionManager.get_session()
    await SessionManager.close_all()
    s2 = await SessionManager.get_session()
    assert s2 is not s1
    assert not s2.closed
    await SessionManager.close_all()


# ---------------------------------------------------------------------------
# BaseAdapter — HTTP status-code retry paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_adapter_retry_success():
    """call_with_retry succeeds after transient 503 and 429 failures."""
    adapter = BaseAdapter(name="test")
    func = AsyncMock(
        side_effect=[
            aiohttp.ClientResponseError(None, None, status=503),
            aiohttp.ClientResponseError(None, None, status=429),
            "success_data",
        ]
    )
    result = await adapter.call_with_retry(func, max_attempts=3, base_delay=0.01)
    assert result == "success_data"
    assert func.call_count == 3


@pytest.mark.asyncio
async def test_base_adapter_retry_exhausted():
    """call_with_retry raises after max_attempts with persistent 502."""
    adapter = BaseAdapter(name="test")
    func = AsyncMock(side_effect=aiohttp.ClientResponseError(None, None, status=502))
    with pytest.raises(aiohttp.ClientResponseError) as exc:
        await adapter.call_with_retry(func, max_attempts=2, base_delay=0.01)
    assert exc.value.status == 502
    assert func.call_count == 2


@pytest.mark.asyncio
async def test_base_adapter_no_retry_on_401():
    """call_with_retry does NOT retry on non-transient 401."""
    adapter = BaseAdapter(name="test")
    func = AsyncMock(side_effect=aiohttp.ClientResponseError(None, None, status=401))
    with pytest.raises(aiohttp.ClientResponseError) as exc:
        await adapter.call_with_retry(func, max_attempts=3, base_delay=0.01)
    assert exc.value.status == 401
    assert func.call_count == 1


# ---------------------------------------------------------------------------
# BaseAdapter — TimeoutError / ClientConnectorError retry paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_base_adapter_retry_on_timeout_success():
    """Retries on TimeoutError then succeeds."""
    adapter = BaseAdapter(name="test")
    func = AsyncMock(side_effect=[TimeoutError("timed out"), "ok"])
    result = await adapter.call_with_retry(func, max_attempts=3, base_delay=0.001)
    assert result == "ok"
    assert func.call_count == 2


@pytest.mark.asyncio
async def test_base_adapter_retry_on_connector_error_success():
    """Retries on ClientConnectorError then succeeds."""
    adapter = BaseAdapter(name="test")
    conn_err = aiohttp.ClientConnectorError(connection_key=MagicMock(), os_error=OSError("refused"))
    func = AsyncMock(side_effect=[conn_err, "data"])
    result = await adapter.call_with_retry(func, max_attempts=3, base_delay=0.001)
    assert result == "data"
    assert func.call_count == 2


@pytest.mark.asyncio
async def test_base_adapter_timeout_exhausted():
    """TimeoutError propagates after max_attempts exhausted."""
    adapter = BaseAdapter(name="test")
    func = AsyncMock(side_effect=TimeoutError("always fails"))
    with pytest.raises(TimeoutError):
        await adapter.call_with_retry(func, max_attempts=2, base_delay=0.001)
    assert func.call_count == 2


@pytest.mark.asyncio
async def test_base_adapter_connector_error_exhausted():
    """ClientConnectorError propagates after max_attempts exhausted."""
    adapter = BaseAdapter(name="test")
    conn_err = aiohttp.ClientConnectorError(connection_key=MagicMock(), os_error=OSError("refused"))
    func = AsyncMock(side_effect=conn_err)
    with pytest.raises(aiohttp.ClientConnectorError):
        await adapter.call_with_retry(func, max_attempts=2, base_delay=0.001)
    assert func.call_count == 2


@pytest.mark.asyncio
async def test_base_adapter_generic_exception_not_retried():
    """Generic exceptions are NOT retried — they propagate immediately."""
    adapter = BaseAdapter(name="test")
    func = AsyncMock(side_effect=ValueError("bad input"))
    with pytest.raises(ValueError):
        await adapter.call_with_retry(func, max_attempts=3, base_delay=0.001)
    assert func.call_count == 1


@pytest.mark.asyncio
async def test_base_adapter_retry_uses_default_codes():
    """Default retry_codes include 503; verify it is retried and succeeds."""
    adapter = BaseAdapter(name="test")
    func = AsyncMock(side_effect=[aiohttp.ClientResponseError(None, None, status=503), "success"])
    result = await adapter.call_with_retry(func, max_attempts=2, base_delay=0.001)
    assert result == "success"


# ---------------------------------------------------------------------------
# AESCallbackHandler — all lifecycle methods
# ---------------------------------------------------------------------------


@pytest.fixture
def aes_handler():
    return AESCallbackHandler(adapter_name="test_adapter", identifier="run-001")


def test_aes_on_chain_start_normal(aes_handler):
    """on_chain_start serializes inputs and emits CHAIN_START."""
    with patch("eval_runner.adapters.common.emit") as mock_emit:
        aes_handler.on_chain_start({"name": ["MyChain"]}, {"query": "hello"})
        mock_emit.assert_called_once()
        _, payload = mock_emit.call_args[0]
        assert "state_hash" in payload
        assert payload["inputs_summary"] == {"query": "str"}


def test_aes_on_chain_start_serialization_error(aes_handler):
    """on_chain_start handles non-serializable inputs gracefully."""
    with patch("eval_runner.adapters.common.emit") as mock_emit:
        aes_handler.on_chain_start({}, {"key": object()})
        mock_emit.assert_called_once()
        _, payload = mock_emit.call_args[0]
        assert len(payload["state_hash"]) == 64
        assert payload["inputs_summary"] == {"key": "object"}


def test_aes_on_chain_end(aes_handler):
    """on_chain_end emits CHAIN_END."""
    with patch("eval_runner.adapters.common.emit") as mock_emit:
        aes_handler.on_chain_end({"output": "done"})
        mock_emit.assert_called_once()
        _, payload = mock_emit.call_args[0]
        assert payload["adapter"] == "test_adapter"


def test_aes_on_node_start_dict_with_id(aes_handler):
    """on_node_start extracts node_id from the 'id' list of the serialized dict."""
    with patch("eval_runner.adapters.common.emit") as mock_emit:
        aes_handler.on_node_start({"id": ["ns", "MyNode"]}, {})
        _, payload = mock_emit.call_args[0]
        assert payload["node_id"] == "MyNode"


def test_aes_on_node_start_non_dict(aes_handler):
    """on_node_start falls back to 'unknown' for non-dict serialized value."""
    with patch("eval_runner.adapters.common.emit") as mock_emit:
        aes_handler.on_node_start("not_a_dict", {})
        _, payload = mock_emit.call_args[0]
        assert payload["node_id"] == "unknown"


def test_aes_on_node_start_dict_no_id_key(aes_handler):
    """on_node_start falls back to 'unknown' when 'id' key is absent."""
    with patch("eval_runner.adapters.common.emit") as mock_emit:
        aes_handler.on_node_start({}, {})
        _, payload = mock_emit.call_args[0]
        assert payload["node_id"] == "unknown"


def test_aes_on_node_end(aes_handler):
    """on_node_end emits NODE_END."""
    with patch("eval_runner.adapters.common.emit") as mock_emit:
        aes_handler.on_node_end({"output": "result"})
        mock_emit.assert_called_once()
        _, payload = mock_emit.call_args[0]
        assert payload["adapter"] == "test_adapter"


def test_aes_on_llm_start(aes_handler):
    """on_llm_start emits ADAPTER_DEBUG with prompt count."""
    with patch("eval_runner.adapters.common.emit") as mock_emit:
        aes_handler.on_llm_start({}, ["prompt1", "prompt2"])
        mock_emit.assert_called_once()
        _, payload = mock_emit.call_args[0]
        assert "2 prompt(s)" in payload["message"]


def test_aes_on_llm_end_with_usage(aes_handler):
    """on_llm_end emits metric_update when token_usage is present."""
    response = MagicMock()
    response.llm_output = {
        "token_usage": {"total_tokens": 50, "prompt_tokens": 20, "completion_tokens": 30}
    }
    with patch("eval_runner.adapters.common.emit") as mock_emit:
        aes_handler.on_llm_end(response)
        mock_emit.assert_called_once()
        event, payload = mock_emit.call_args[0]
        assert event == "metric_update"
        assert payload["tokens"] == 50


def test_aes_on_llm_end_no_usage(aes_handler):
    """on_llm_end does NOT emit when token_usage key is absent."""
    response = MagicMock()
    response.llm_output = {}
    with patch("eval_runner.adapters.common.emit") as mock_emit:
        aes_handler.on_llm_end(response)
        mock_emit.assert_not_called()


def test_aes_on_llm_end_no_llm_output_attr(aes_handler):
    """on_llm_end does NOT emit when llm_output attribute is missing entirely."""
    response = MagicMock(spec=[])
    with patch("eval_runner.adapters.common.emit") as mock_emit:
        aes_handler.on_llm_end(response)
        mock_emit.assert_not_called()


# ---------------------------------------------------------------------------
# DualNormalizationHub.normalize_text — keyword priority branches
# ---------------------------------------------------------------------------


def test_normalize_text_hitl_keyword():
    assert DualNormalizationHub.normalize_text("Waiting for human review") == "hitl_pause"


def test_normalize_text_hitl_priority_over_polling():
    """HITL keywords are checked before polling keywords."""
    assert DualNormalizationHub.normalize_text("waiting for human clearance") == "hitl_pause"


def test_normalize_text_polling_keyword():
    assert DualNormalizationHub.normalize_text("Task is currently processing") == "processing"


def test_normalize_text_error_keyword():
    assert DualNormalizationHub.normalize_text("An error occurred") == "error"


def test_normalize_text_terminal_keyword():
    assert DualNormalizationHub.normalize_text("Request approved") == "final_answer"


def test_normalize_text_no_keyword_defaults_to_final_answer():
    assert DualNormalizationHub.normalize_text("some unrecognized state") == "final_answer"


# ---------------------------------------------------------------------------
# DualNormalizationHub.normalize — override tier
# ---------------------------------------------------------------------------


def test_normalize_override_valid_match():
    """Override with a valid action and matching status value is applied."""
    result = DualNormalizationHub.normalize(
        {"status": "PENDING"}, 200, overrides={"pending": "hitl_pause"}
    )
    assert result == "hitl_pause"


def test_normalize_override_invalid_action_falls_through():
    """Override maps to an unrecognised action; falls through to heuristics."""
    result = DualNormalizationHub.normalize(
        {"status": "PENDING"}, 200, overrides={"pending": "not_valid_action"}
    )
    # "PENDING" is in POLLING_KEYWORDS → "processing"
    assert result == "processing"


def test_normalize_override_no_match_falls_through():
    """Override condition does not match; falls through to heuristics."""
    result = DualNormalizationHub.normalize(
        {"status": "running"}, 200, overrides={"DONE": "completed"}
    )
    # "running" matches no keyword → "final_answer"
    assert result == "final_answer"


def test_normalize_override_non_status_key_ignored():
    """Override only inspects status/state/result keys."""
    result = DualNormalizationHub.normalize(
        {"payload": "pending"}, 200, overrides={"pending": "hitl_pause"}
    )
    assert result == "final_answer"


# ---------------------------------------------------------------------------
# DualNormalizationHub.normalize — schema tier
# ---------------------------------------------------------------------------


def test_normalize_schema_valid_action():
    schema = {"status_field": "phase", "mapping": {"active": "processing"}}
    assert DualNormalizationHub.normalize({"phase": "active"}, 200, schema=schema) == "processing"


def test_normalize_schema_invalid_action_falls_through():
    schema = {"status_field": "phase", "mapping": {"active": "NOT_VALID"}}
    # "active" → no keyword match → "final_answer"
    assert DualNormalizationHub.normalize({"phase": "active"}, 200, schema=schema) == "final_answer"


def test_normalize_schema_field_absent_falls_through():
    schema = {"status_field": "nonexistent", "mapping": {"active": "processing"}}
    # Falls to heuristics — "pending" → POLLING_KEYWORDS → "processing"
    assert DualNormalizationHub.normalize({"status": "pending"}, 200, schema=schema) == "processing"


def test_normalize_schema_defaults_to_status_field():
    schema = {"mapping": {"done": "completed"}}
    assert DualNormalizationHub.normalize({"status": "done"}, 200, schema=schema) == "completed"


# ---------------------------------------------------------------------------
# DualNormalizationHub.normalize — HTTP status tier
# ---------------------------------------------------------------------------


def test_normalize_http_4xx_returns_error():
    assert DualNormalizationHub.normalize({}, 400) == "error"
    assert DualNormalizationHub.normalize({}, 503) == "error"


def test_normalize_http_ok_falls_through_to_heuristics():
    assert DualNormalizationHub.normalize({"status": "pending"}, 200) == "processing"


# ---------------------------------------------------------------------------
# DualNormalizationHub.normalize — heuristic key scan
# ---------------------------------------------------------------------------


def test_normalize_heuristic_state_key():
    assert DualNormalizationHub.normalize({"state": "hitl"}, 200) == "hitl_pause"


def test_normalize_heuristic_phase_key():
    assert DualNormalizationHub.normalize({"phase": "error"}, 200) == "error"


def test_normalize_heuristic_outcome_key():
    assert DualNormalizationHub.normalize({"outcome": "completed"}, 200) == "final_answer"


def test_normalize_heuristic_decision_key():
    assert DualNormalizationHub.normalize({"decision": "approved"}, 200) == "final_answer"


def test_normalize_heuristic_result_key():
    assert DualNormalizationHub.normalize({"result": "failure"}, 200) == "error"


def test_normalize_heuristic_secondary_status_substring():
    """Keys containing 'status' substring are scanned as secondary heuristic."""
    assert DualNormalizationHub.normalize({"task_status": "pending"}, 200) == "processing"


def test_normalize_no_matching_key_falls_to_final_answer():
    assert DualNormalizationHub.normalize({"irrelevant": "data"}, 200) == "final_answer"


def test_normalize_heuristic_non_final_emits_debug_event():
    """A heuristic non-final result triggers an ADAPTER_DEBUG emit."""
    with patch("eval_runner.adapters.common.emit") as mock_emit:
        DualNormalizationHub.normalize({"status": "pending"}, 200)
        mock_emit.assert_called_once()
        _, payload = mock_emit.call_args[0]
        assert "Agnostic Mapping" in payload["message"]


@pytest.mark.asyncio
async def test_session_manager_stale_close_and_loop_mismatch():
    """
    Verify SessionManager properly closes stale session
    when loop changes or session is replaced.
    """
    session1 = await SessionManager.get_session()
    assert session1 is not None

    # Simulate loop mismatch
    session1._loop = "different_loop"

    # Next get_session should detect mismatch, close stale, and create new
    session2 = await SessionManager.get_session()
    assert session2 is not None
    assert session2 is not session1

    await SessionManager.close_all()


@pytest.mark.asyncio
async def test_session_manager_connector_coroutine_close_and_exception():
    """Verify close_all handles coroutine connector.close and exceptions cleanly."""

    class MockAsyncConnector:
        async def close(self):
            pass

    mock_sess = MagicMock(closed=False)
    mock_sess.close = AsyncMock()
    mock_sess.connector = MockAsyncConnector()

    SessionManager._session = mock_sess
    await SessionManager.close_all()
    assert SessionManager._session is None

    # Test exception on connector close
    class MockFailingConnector:
        def close(self):
            raise RuntimeError("close failed")

    mock_sess2 = MagicMock(closed=False)
    mock_sess2.close = AsyncMock()
    mock_sess2.connector = MockFailingConnector()

    SessionManager._session = mock_sess2
    await SessionManager.close_all()
    assert SessionManager._session is None


@pytest.mark.asyncio
async def test_base_adapter_non_retry_code():
    """Verify call_with_retry raises on non-retryable status."""
    adapter = BaseAdapter("test")
    mock_func = AsyncMock(
        side_effect=aiohttp.ClientResponseError(request_info=MagicMock(), history=(), status=400)
    )
    with pytest.raises(aiohttp.ClientResponseError):
        await adapter.call_with_retry(mock_func, max_attempts=1)


@pytest.mark.parametrize(
    ("payload", "stream", "expected_attempts"),
    [
        ({}, False, 1),
        ({"idempotency_key": "request-1"}, False, 4),
        ({"metadata": {"retry_idempotent": True}}, False, 4),
        ({"idempotency_key": "request-1"}, True, 1),
    ],
)
def test_provider_retry_attempts_require_explicit_replay_safety(payload, stream, expected_attempts):
    adapter = BaseAdapter("provider")
    adapter.max_retries = 3

    assert adapter.provider_retry_attempts(payload, stream=stream) == expected_attempts
