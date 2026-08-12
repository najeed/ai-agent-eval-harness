"""
Adapter contract test suite verifying connection pooling, exponential backoff,
event normalization, error propagation, auth failure, and cancellation handling.
"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from eval_runner.adapters.ag2 import AG2AdapterPlugin
from eval_runner.adapters.claude import ClaudeAdapterPlugin
from eval_runner.adapters.common import AESCallbackHandler, BaseAdapter, SessionManager
from eval_runner.adapters.crewai import CrewAIAdapterPlugin
from eval_runner.adapters.gemini import GeminiAdapterPlugin
from eval_runner.adapters.grok import GrokAdapterPlugin
from eval_runner.adapters.langchain import LangChainAdapterPlugin
from eval_runner.adapters.langgraph import LangGraphAdapterPlugin
from eval_runner.adapters.ollama import OllamaAdapterPlugin
from eval_runner.adapters.openai import OpenAIAdapterPlugin
from eval_runner.adapters.openapi import OpenAPIAdapterPlugin

# Narrow set of exception types that a well-behaved adapter is permitted to raise
# when given mock credentials (no live network/API key available).
# Any exception outside this set indicates a structural defect in the adapter
# (e.g. AttributeError from missing initialization, ImportError from broken deps).
_ACCEPTED_ADAPTER_EXCEPTIONS = (
    aiohttp.ClientResponseError,
    ValueError,
    RuntimeError,
    KeyError,
    TypeError,
)

# Canonical set of normalized response status values the adapter contract requires.
_VALID_RESPONSE_STATUSES = {
    "success",
    "error",
    "processing",
    "hitl_pause",
    "final_answer",
    "completed",
}


@pytest.mark.asyncio
async def test_session_manager_connection_pooling_contract():
    """
    Contract Test: SessionManager reuses global ClientSession and closes cleanly.
    """
    await SessionManager.close_all()
    session1 = await SessionManager.get_session()
    session2 = await SessionManager.get_session()

    assert session1 is session2
    assert not session1.closed

    await SessionManager.close_all()
    assert session1.closed


@pytest.mark.asyncio
async def test_base_adapter_exponential_backoff_retry_contract():
    """
    Contract Test: BaseAdapter.call_with_retry retries transient 429/503 HTTP status codes.
    """
    adapter = BaseAdapter(name="contract_test_adapter")
    attempts = 0

    async def flaky_api_call():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise aiohttp.ClientResponseError(
                request_info=None, history=(), status=503, message="Service Unavailable"
            )
        return {"status": "success", "attempts": attempts}

    result = await adapter.call_with_retry(
        flaky_api_call, max_attempts=4, base_delay=0.01, retry_codes={503}
    )
    assert result["status"] == "success"
    assert attempts == 3


@pytest.mark.asyncio
async def test_base_adapter_exponential_backoff_timing_contract(monkeypatch):
    """
    Contract Test: BaseAdapter.call_with_retry uses exponential backoff formula
    base_delay * 2^attempt. Verified by injecting a mock asyncio.sleep and asserting
    exact delay values — no real sleeps are used.
    """
    sleep_calls: list[float] = []

    async def mock_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("eval_runner.adapters.common.asyncio.sleep", mock_sleep)

    adapter = BaseAdapter(name="timing_contract_adapter")
    attempts = 0

    async def flaky_call():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise aiohttp.ClientResponseError(
                request_info=None, history=(), status=503, message="Service Unavailable"
            )
        return {"status": "success"}

    result = await adapter.call_with_retry(
        flaky_call, max_attempts=4, base_delay=1.0, retry_codes={503}
    )

    assert result["status"] == "success"
    assert attempts == 3
    # Formula: base_delay * (2 ** attempt), where attempt increments before sleep.
    # Retry 1: attempt=1 → delay = 1.0 * 2^1 = 2.0
    # Retry 2: attempt=2 → delay = 1.0 * 2^2 = 4.0
    assert len(sleep_calls) == 2
    assert sleep_calls[0] == pytest.approx(2.0)
    assert sleep_calls[1] == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_base_adapter_max_retries_exceeded_contract():
    """
    Contract Test: Exceeding max attempts raises original ClientResponseError.
    """
    adapter = BaseAdapter(name="contract_test_adapter")

    async def failing_api_call():
        raise aiohttp.ClientResponseError(
            request_info=None, history=(), status=429, message="Rate Limit Exceeded"
        )

    with pytest.raises(aiohttp.ClientResponseError) as exc_info:
        await adapter.call_with_retry(
            failing_api_call, max_attempts=2, base_delay=0.01, retry_codes={429}
        )
    assert exc_info.value.status == 429


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code,reason",
    [
        (401, "Unauthorized API Key"),
        (403, "Forbidden — insufficient permissions"),
    ],
    ids=["401-unauthorized", "403-forbidden"],
)
async def test_adapter_auth_failure_contract(status_code: int, reason: str):
    """
    Contract Test: 401 Unauthorized and 403 Forbidden errors do NOT trigger retries
    and immediately raise ClientResponseError after exactly one attempt.
    """
    adapter = BaseAdapter(name="auth_contract_adapter")
    attempts = 0

    async def auth_rejected_call():
        nonlocal attempts
        attempts += 1
        raise aiohttp.ClientResponseError(
            request_info=None, history=(), status=status_code, message=reason
        )

    with pytest.raises(aiohttp.ClientResponseError) as exc_info:
        await adapter.call_with_retry(
            auth_rejected_call, max_attempts=3, base_delay=0.01, retry_codes={503}
        )
    assert exc_info.value.status == status_code
    assert attempts == 1, (
        f"Auth rejection ({status_code}) triggered retries. "
        f"Expected exactly 1 attempt, got {attempts}."
    )


@pytest.mark.asyncio
async def test_adapter_cancellation_contract():
    """
    Contract Test: asyncio.CancelledError during adapter execution cancels task cleanly.
    """
    adapter = BaseAdapter(name="cancel_contract_adapter")

    async def hanging_call():
        await asyncio.sleep(10.0)

    task = asyncio.create_task(
        adapter.call_with_retry(hanging_call, max_attempts=3, base_delay=0.01)
    )
    await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_aes_callback_handler_event_contract(monkeypatch):
    """
    Contract Test: AESCallbackHandler emits standardized CHAIN_START and NODE_START events.
    """
    events_captured = []

    def mock_emit(event_type, event_data):
        events_captured.append((event_type, event_data))

    monkeypatch.setattr("eval_runner.adapters.common.emit", mock_emit)

    handler = AESCallbackHandler(adapter_name="langchain", identifier="run-contract-001")
    handler.on_chain_start(serialized={"name": "test_chain"}, inputs={"query": "test"})
    handler.on_node_start(serialized={"id": ["root", "node1"]}, inputs={})

    assert len(events_captured) == 2
    assert events_captured[0][0] == "chain_start"
    assert events_captured[0][1]["adapter"] == "langchain"
    assert events_captured[1][0] == "node_start"
    assert events_captured[1][1]["node_id"] == "node1"


# --- Parameterized Adapter Contract Matrix ---

ADAPTER_PLUGINS = [
    LangChainAdapterPlugin,
    LangGraphAdapterPlugin,
    ClaudeAdapterPlugin,
    GeminiAdapterPlugin,
    CrewAIAdapterPlugin,
    OpenAIAdapterPlugin,
    OllamaAdapterPlugin,
    OpenAPIAdapterPlugin,
    GrokAdapterPlugin,
    AG2AdapterPlugin,
]


@pytest.mark.parametrize("adapter_cls", ADAPTER_PLUGINS)
@pytest.mark.asyncio
async def test_adapter_plugin_contract_matrix(adapter_cls):
    """
    Parameterized Contract Test Matrix:
    Verifies that all 10 framework adapter plugins (LangChain, LangGraph, Claude,
    Gemini, CrewAI, OpenAI, Ollama, OpenAPI, Grok, AG2) satisfy the adapter interface
    contract: correct instantiation, named execute method, and normalized response.

    Expected failure modes with mock credentials (no live API keys):
    - aiohttp.ClientResponseError: auth/network rejection from the SDK transport
    - ValueError / RuntimeError / KeyError / TypeError: config/parse rejection

    Any other exception type (AttributeError, ImportError, NotImplementedError, etc.)
    indicates a structural defect in the adapter and fails this test.
    """
    plugin = adapter_cls()
    assert hasattr(plugin, "name"), f"{adapter_cls.__name__} missing 'name' attribute"
    assert isinstance(plugin.name, str)
    assert len(plugin.name) > 0

    payload = {
        "task_id": f"contract_{plugin.name}",
        "api_key": "mock_contract_key_12345",
        "input": {"prompt": "Hello"},
    }
    query_fn = (
        getattr(plugin, f"execute_{plugin.name}_query", None)
        or getattr(plugin, f"execute_{plugin.name}_node", None)
        or getattr(plugin, f"execute_{plugin.name}_agent", None)
        or getattr(plugin, f"execute_{plugin.name}_task", None)
    )
    msg = f"Plugin '{plugin.name}' missing expected query execution method!"
    assert query_fn is not None, msg

    try:
        res = await query_fn(payload)
        assert isinstance(res, dict), (
            f"Plugin '{plugin.name}' returned {type(res).__name__}, expected dict"
        )
        assert "status" in res, f"Plugin '{plugin.name}' response missing required 'status' key"
        assert res["status"] in _VALID_RESPONSE_STATUSES, (
            f"Plugin '{plugin.name}' returned non-canonical status: {res['status']!r}. "
            f"Valid values: {_VALID_RESPONSE_STATUSES}"
        )
    except _ACCEPTED_ADAPTER_EXCEPTIONS:
        # Expected: mock credentials rejected at SDK config or network layer.
        pass
    except Exception as exc:
        pytest.fail(
            f"Plugin '{plugin.name}' raised unexpected exception type "
            f"'{type(exc).__name__}': {exc!r}. "
            f"Adapters must only raise one of: "
            f"{[e.__name__ for e in _ACCEPTED_ADAPTER_EXCEPTIONS]}."
        )
