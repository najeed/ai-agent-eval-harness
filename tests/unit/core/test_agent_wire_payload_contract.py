"""Agent dispatch preserves wire prompts, context metadata, and original failures."""

import hashlib
import json
from datetime import date
from types import SimpleNamespace

import pytest

from eval_runner.context import TurnContext
from eval_runner.engine import AgentAdapterRegistry, render_outbound_payload


@pytest.mark.parametrize("template", [None, {}])
def test_empty_payload_template_still_transmits_the_requested_task(template):
    context = TurnContext("step", 1, "", (), metadata={"payload_template": template})

    payload, digest = render_outbound_payload("Perform transfer", context, "http")

    assert payload == {"task_description": "Perform transfer"}
    expected = hashlib.sha3_256(b'{"task_description":"Perform transfer"}').hexdigest()
    assert digest == "sha3_256:" + expected


def test_python_adapter_input_date_has_a_reproducible_wire_commitment():
    context = TurnContext("step", 1, "", (), input_payload={"booked_at": date(2026, 10, 29)})

    payload, digest = render_outbound_payload("Perform transfer", context, "openapi")

    assert payload == {"booked_at": date(2026, 10, 29), "task_description": "Perform transfer"}
    expected = hashlib.sha3_256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()
    assert digest == "sha3_256:" + expected


@pytest.mark.parametrize("legacy_input", [None, {}, [], ["legacy"], "unstructured"])
def test_openapi_legacy_non_object_input_preserves_the_requested_task(legacy_input):
    context = SimpleNamespace(input_payload=legacy_input, metadata={})

    payload, _ = render_outbound_payload("Perform transfer", context, "openapi")

    assert payload == {"task_description": "Perform transfer"}


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [None, {"caller_tag": "preserve"}])
async def test_dispatch_normalizes_legacy_context_and_preserves_caller_metadata(
    monkeypatch, metadata
):
    captured = {}

    async def adapter(payload, *, context, **kwargs):
        captured.update(payload=payload, context=context)
        return {"action": "final_answer"}

    monkeypatch.setattr(
        AgentAdapterRegistry, "_resolve_adapter", classmethod(lambda cls, protocol: adapter)
    )
    context = SimpleNamespace(
        task_id="step",
        turn_number=1,
        history=(),
        input_payload={},
        metadata=metadata,
        span_context=None,
        otel_context=None,
    )

    response = await AgentAdapterRegistry.call_agent("http", None, "Perform transfer", [], context)

    assert response == {"action": "final_answer"}
    assert captured["payload"] == {"task_description": "Perform transfer"}
    assert isinstance(captured["context"].metadata, dict)
    assert captured["context"].metadata["rendered_outbound_payload"] == captured["payload"]
    if metadata:
        assert captured["context"].metadata["caller_tag"] == "preserve"


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_fails", [False, True])
async def test_unavailable_optional_telemetry_preserves_agent_result_or_original_error(
    monkeypatch, adapter_fails
):
    async def adapter(payload, **kwargs):
        if adapter_fails:
            raise RuntimeError("agent unavailable")
        return {"action": "final_answer"}

    def unavailable_tracer(*args, **kwargs):
        raise RuntimeError("telemetry unavailable")

    monkeypatch.setattr(
        AgentAdapterRegistry, "_resolve_adapter", classmethod(lambda cls, protocol: adapter)
    )
    monkeypatch.setattr("opentelemetry.trace.get_tracer", unavailable_tracer)
    context = TurnContext("step", 1, "", ())

    if adapter_fails:
        with pytest.raises(RuntimeError, match="agent unavailable"):
            await AgentAdapterRegistry.call_agent("http", None, "Perform transfer", [], context)
    else:
        response = await AgentAdapterRegistry.call_agent(
            "http", None, "Perform transfer", [], context
        )
        assert response == {"action": "final_answer"}
