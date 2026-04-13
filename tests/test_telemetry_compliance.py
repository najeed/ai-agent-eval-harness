from pathlib import Path
from unittest.mock import patch

import pytest

from eval_runner.adapters.autogen import AutoGenAdapterPlugin
from eval_runner.context import EvaluationContext, TurnContext
from eval_runner.events import CoreEvents, emit, reset, subscribe
from eval_runner.verifier import BaseVerifier, VerificationResult


def test_verification_result_nist_compliance():
    """Verify VerificationResult adheres to NIST AI-100-1 (7-dimension vector)."""
    res = VerificationResult(
        success=True,
        message="Standard compliance check",
        metrics={
            "reliability": 0.9,
            "safety": 0.8,
            "security": 0.9,
            "fairness": 0.8,
            "explainability": 0.8,
            "privacy": 0.9,
            "resilience": 0.7,
        },
        aggregate_score=0.85,
    )

    data = res.to_dict()
    assert data["aggregate_score"] == 0.85
    assert data["success"] is True
    assert data["metrics"]["reliability"] == 0.9
    assert "timestamp" in data

    # Test defaults
    res_default = VerificationResult(success=False, message="Fail", aggregate_score=0.5)
    assert res_default.metrics["reliability"] == 0.0
    assert len(res_default.metrics) == 7


def test_event_emitter_span_propagation():
    """Verify span_context is propagated correctly through the event bus."""
    captured_events = []

    def subscriber(event):
        captured_events.append(event)

    reset()
    subscribe(subscriber)

    span_ctx = {"trace_id": "nist-trace-001"}
    emit(CoreEvents.STRATEGY_START, {"goal": "verify_security"}, span_context=span_ctx)

    assert len(captured_events) == 1
    assert captured_events[0].span_context == span_ctx
    assert captured_events[0].to_dict()["span_context"] == span_ctx


def test_core_events_taxonomy_growth():
    """Verify the new hierarchical taxonomy is available."""
    assert hasattr(CoreEvents, "STRATEGY_START")
    assert hasattr(CoreEvents, "MANEUVER_START")
    assert CoreEvents.STRATEGY_START == "strategy_start"
    assert CoreEvents.MANEUVER_START == "maneuver_start"


def test_context_objects_telemetry_fields():
    """Verify EvaluationContext and TurnContext support span_context."""
    eval_ctx = EvaluationContext(
        identifier="s1", scenario_data={}, span_context={"root_span": "abc"}
    )
    assert eval_ctx.span_context == {"root_span": "abc"}

    turn_ctx = TurnContext(
        task_id="t1",
        turn_number=1,
        current_message="hi",
        history=(),
        span_context={"turn_span": "def"},
    )
    assert turn_ctx.span_context == {"turn_span": "def"}


@pytest.mark.asyncio
async def test_autogen_adapter_instrumentation():
    """Verify AutoGen adapter emits TURN and CHAIN events with context."""

    original_import = __builtins__["__import__"]

    adapter = AutoGenAdapterPlugin()
    payload = {"agent_id": "test_agent", "message": "hello"}
    span_ctx = {"adapter_trace": "xyz"}

    def mock_import(name, *args, **kwargs):
        if name == "autogen":
            raise ImportError("No module named 'autogen'")
        return original_import(name, *args, **kwargs)

    with patch("eval_runner.events.EventEmitter.emit") as mock_emit:
        with patch("builtins.__import__", side_effect=mock_import):
            try:
                await adapter.execute_autogen_query(payload, span_context=span_ctx)
            except ImportError:
                pass

            mock_emit.assert_any_call(
                CoreEvents.TURN_START,
                {
                    "adapter": "autogen",
                    "agent_id": "test_agent",
                    "message": "hello",
                    "mode": "remote-fallback",
                },
                span_context=span_ctx,
            )

            mock_emit.assert_any_call(
                CoreEvents.CHAIN_START,
                {
                    "adapter": "autogen",
                    "agent_id": "test_agent",
                    "protocol": "v1",
                    "mode": "remote",
                },
                span_context=span_ctx,
            )


def test_base_verifier_interface():
    """Ensure BaseVerifier is an ABC requiring verify()."""

    class MyVerifier(BaseVerifier):
        def verify(self, trace_path, **kwargs):
            return VerificationResult(success=True, message="OK", aggregate_score=1.0)

    v = MyVerifier()
    res = v.verify(Path("test.jsonl"))
    assert res.aggregate_score == 1.0


if __name__ == "__main__":
    # If run directly, execute tests
    pytest.main([__file__])
