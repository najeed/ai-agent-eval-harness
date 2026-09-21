import os
from unittest.mock import AsyncMock, patch

import pytest

from eval_runner.context import AdapterInvocationContext, TurnContext
from eval_runner.engine import (
    AgentAdapterRegistry,
    _adapter_context_kwargs,
    _adapter_endpoint_kwargs,
    _internal_adapter_payload,
)


@pytest.mark.asyncio
async def test_registry_discovery():
    AgentAdapterRegistry.reset()
    AgentAdapterRegistry._discover()
    assert "http" in AgentAdapterRegistry._adapters
    assert "local" in AgentAdapterRegistry._adapters
    assert "socket" in AgentAdapterRegistry._adapters


@pytest.mark.asyncio
async def test_call_agent_protocol_selection():
    payload = {"test": "data"}
    AgentAdapterRegistry.reset()
    AgentAdapterRegistry._discover()

    # Target the dictionary values directly to be sure
    with patch.dict(
        AgentAdapterRegistry._adapters,
        {"local": AsyncMock(return_value={"action": "final_answer", "content": "ok"})},
    ):
        # Industrial Signature: (protocol, endpoint, message, history, turn_ctx=None)
        result = await AgentAdapterRegistry.call_agent("local", "echo 'test'", str(payload), [])
        assert result["content"] == "ok"


@pytest.mark.asyncio
async def test_call_agent_env_fallback():
    payload = {"test": "data"}
    AgentAdapterRegistry.reset()
    AgentAdapterRegistry._discover()

    with patch.dict(os.environ, {"AGENT_LOCAL_CMD": "python mock_agent.py"}):
        with patch.dict(
            AgentAdapterRegistry._adapters,
            {"local": AsyncMock(return_value={"action": "final_answer", "content": "env_ok"})},
        ):
            # Industrial Signature: (protocol, endpoint, message, history, turn_ctx=None)
            result = await AgentAdapterRegistry.call_agent("local", None, str(payload), [])
            assert result["content"] == "env_ok"


@pytest.mark.asyncio
async def test_dispatcher_keeps_context_off_protocol_wire_payload():
    received = {}

    async def protocol_adapter(payload, endpoint=None, **kwargs):
        received.update(payload=payload, endpoint=endpoint, context=kwargs["context"])
        return {"action": "final_answer", "content": "ok"}

    AgentAdapterRegistry.reset()
    AgentAdapterRegistry._discovered = True
    AgentAdapterRegistry.register("http", protocol_adapter)
    turn = TurnContext(
        task_id="task-1",
        turn_number=2,
        current_message="hello",
        history=({"role": "user", "content": "earlier"},),
        input_payload={"account": "a-1"},
        metadata={"secret_binding": "internal"},
    )

    await AgentAdapterRegistry.call_agent("http", "https://agent.example", "hello", [], turn)

    assert received["payload"] == {"task_description": "hello"}
    assert received["context"].history[0]["content"] == "earlier"
    assert received["context"].metadata["secret_binding"] == "internal"


@pytest.mark.asyncio
async def test_dispatcher_materializes_context_for_framework_adapters():
    received = {}

    async def framework_adapter(payload, endpoint=None, **kwargs):
        received.update(payload=payload, context=kwargs["context"])
        return {"action": "final_answer", "content": "ok"}

    AgentAdapterRegistry.reset()
    AgentAdapterRegistry._discovered = True
    AgentAdapterRegistry.register("crewai", framework_adapter)
    turn = TurnContext(
        task_id="crew-task",
        turn_number=3,
        current_message="run",
        history=({"role": "assistant", "content": "previous"},),
        input_payload={"customer": "c-1"},
        metadata={"crew_path": "tests.fixtures:crew"},
    )

    await AgentAdapterRegistry.call_agent("crewai", None, "run", [], turn)

    assert received["payload"]["metadata"]["crew_path"] == "tests.fixtures:crew"
    assert received["payload"]["history"][0]["content"] == "previous"
    assert received["payload"]["input_payload"] == {"customer": "c-1"}
    assert received["payload"]["task_id"] == "crew-task"


@pytest.mark.asyncio
async def test_dispatcher_materializes_history_for_provider_adapters():
    received = {}

    async def provider_adapter(payload, base_url=None, **kwargs):
        received.update(payload=payload, base_url=base_url, context=kwargs["context"])
        return {"action": "final_answer", "content": "ok"}

    AgentAdapterRegistry.reset()
    AgentAdapterRegistry._discovered = True
    AgentAdapterRegistry.register("openai", provider_adapter)
    turn = TurnContext(
        task_id="provider-task",
        turn_number=2,
        current_message="continue",
        history=({"role": "user", "content": "first turn"},),
        input_payload={"tenant": "example"},
        metadata={"model": "test-model"},
    )

    await AgentAdapterRegistry.call_agent(
        "openai", "https://provider.example", "continue", [], turn
    )

    assert received["base_url"] == "https://provider.example"
    assert received["payload"]["history"] == [{"role": "user", "content": "first turn"}]
    assert received["payload"]["metadata"]["model"] == "test-model"


def test_adapter_invocation_context_handles_missing_turn_context():
    context = TurnContext(
        task_id="ignored",
        turn_number=1,
        current_message="ignored",
        history=(),
    )

    missing = AdapterInvocationContext.from_turn_context("hello", None)
    present = AdapterInvocationContext.from_turn_context("hello", context)

    assert missing.message == "hello"
    assert missing.history == ()
    assert present.task_id == "ignored"


def test_adapter_kwargs_support_legacy_and_endpoint_conventions():
    def legacy(payload, endpoint=None):
        return payload, endpoint

    def url_adapter(payload, url=None, **kwargs):
        return payload, url, kwargs

    def base_url_adapter(payload, base_url=None):
        return payload, base_url

    def keyword_only_adapter(payload, **kwargs):
        return payload, kwargs

    def payload_only_adapter(payload):
        return payload

    def explicit_context_adapter(payload, context=None, turn_ctx=None):
        return payload, context, turn_ctx

    context = AdapterInvocationContext.from_turn_context("hello", None)

    assert _adapter_endpoint_kwargs(legacy, "https://agent.example") == {
        "endpoint": "https://agent.example"
    }
    assert _adapter_context_kwargs(legacy, context, None) == {}
    assert _adapter_endpoint_kwargs(url_adapter, "https://agent.example") == {
        "url": "https://agent.example"
    }
    assert _adapter_endpoint_kwargs(base_url_adapter, "https://agent.example") == {
        "base_url": "https://agent.example"
    }
    assert _adapter_endpoint_kwargs(keyword_only_adapter, "https://agent.example") == {
        "endpoint": "https://agent.example"
    }
    assert _adapter_endpoint_kwargs(payload_only_adapter, "https://agent.example") == {}
    assert _adapter_context_kwargs(url_adapter, context, None)["context"] is context
    assert _adapter_context_kwargs(explicit_context_adapter, context, "turn") == {
        "context": context,
        "turn_ctx": "turn",
    }


def test_internal_adapter_payload_preserves_context_without_mutating_wire_payload():
    turn = TurnContext(
        task_id="task-1",
        turn_number=4,
        current_message="hello",
        history=({"role": "user", "content": "earlier"},),
        input_payload={"source": "test"},
        metadata={"binding": "native"},
        span_context={"traceparent": "00-abc"},
    )
    context = AdapterInvocationContext.from_turn_context("hello", turn)
    wire_payload = {"task_description": "hello", "task_id": "explicit"}

    payload = _internal_adapter_payload(wire_payload, context)

    assert wire_payload == {"task_description": "hello", "task_id": "explicit"}
    assert payload["task_id"] == "explicit"
    assert payload["turn_number"] == 4
    assert payload["span_context"] == {"traceparent": "00-abc"}

    empty = _internal_adapter_payload(
        {"task_description": "hello"},
        AdapterInvocationContext.from_turn_context("hello", None),
    )
    assert empty == {
        "task_description": "hello",
        "history": [],
        "input_payload": {},
        "metadata": {},
    }
