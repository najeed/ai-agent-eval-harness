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

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from eval_runner.adapters.common import (
    AESCallbackHandler,
    BaseAdapter,
    DualNormalizationHub,
    SessionManager,
)

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
        assert payload["state_hash"] == "error_hashing"
        assert payload["inputs_summary"] == {"error": "serialization_failed"}


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
        assert "2 prompts" in payload["message"]


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
