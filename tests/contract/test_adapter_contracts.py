"""
Adapter contract test suite verifying connection pooling, exponential backoff,
event normalization, and error propagation across framework adapters.
"""

from __future__ import annotations

import aiohttp
import pytest

from eval_runner.adapters.ag2 import AG2AdapterPlugin
from eval_runner.adapters.common import AESCallbackHandler, BaseAdapter, SessionManager
from eval_runner.adapters.grok import GrokAdapterPlugin
from eval_runner.adapters.langchain import LangChainAdapterPlugin
from eval_runner.adapters.ollama import OllamaAdapterPlugin
from eval_runner.adapters.openai import OpenAIAdapterPlugin
from eval_runner.adapters.openapi import OpenAPIAdapterPlugin


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
    Verifies that all framework adapter plugins (LangChain, OpenAI, Ollama, OpenAPI, Grok, AG2)
    instantiate with canonical names and handle query executions cleanly.
    """
    plugin = adapter_cls()
    assert hasattr(plugin, "name")
    assert isinstance(plugin.name, str)
    assert len(plugin.name) > 0

    payload = {"task_id": f"contract_{plugin.name}", "input": {"prompt": "Hello"}}
    query_method_name = f"execute_{plugin.name}_query"
    query_fn = getattr(plugin, query_method_name, None)
    msg = f"Plugin '{plugin.name}' missing expected query method '{query_method_name}'"
    assert query_fn is not None, msg

    res = await query_fn(payload)
    assert isinstance(res, dict)
    assert "status" in res
