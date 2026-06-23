import os
import sys
import unittest.mock as mock

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from eval_runner.adapters import http_adapter, sse_http_adapter
from eval_runner.context import EvaluationContext, TurnContext
from eval_runner.events import CoreEvents, Event, emit
from eval_runner.otel_bridge import OTelTelemetryBridge


@pytest.fixture
def otel_setup():
    """Sets up an in-memory OTel exporter for assertions."""
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(exporter)
    provider.add_span_processor(processor)

    old_provider = trace.get_tracer_provider()
    try:
        trace.set_tracer_provider(provider)
    except Exception:
        pass

    yield exporter

    try:
        trace.set_tracer_provider(old_provider)
    except Exception:
        pass


def test_context_creation_and_binding(otel_setup):
    eval_ctx = EvaluationContext(identifier="test-run-123", scenario_data={"name": "test_scenario"})
    assert eval_ctx.otel_context is None

    tracer = trace.get_tracer("test-tracer")
    with tracer.start_as_current_span("parent-span") as span:
        object.__setattr__(eval_ctx, "otel_context", trace.set_span_in_context(span))

        turn_ctx = TurnContext(
            task_id="task-123",
            turn_number=1,
            current_message="hello",
            history=(),
            otel_context=eval_ctx.otel_context,
        )
        assert turn_ctx.otel_context is not None

        active_span = trace.get_current_span(turn_ctx.otel_context)
        assert active_span == span


def test_otel_telemetry_bridge():
    _ = OTelTelemetryBridge()

    mock_span = mock.MagicMock()
    mock_span.is_recording.return_value = True

    with mock.patch("opentelemetry.trace.get_current_span", return_value=mock_span):
        emit(CoreEvents.TOOL_CALL, {"tool": "calculator", "arguments": {"expression": "2+2"}})
        emit(CoreEvents.TOOL_RESULT, {"tool": "calculator", "result": "4"})
        emit(CoreEvents.ERROR, {"message": "Database disconnected", "traceback": "Traceback..."})

        # Verify event records on mock_span
        mock_span.add_event.assert_any_call(
            "tool.call", {"tool.name": "calculator", "tool.arguments": "{'expression': '2+2'}"}
        )
        mock_span.add_event.assert_any_call(
            "tool.result", {"tool.name": "calculator", "tool.result": "4"}
        )
        mock_span.add_event.assert_any_call(
            "error", {"error.message": "Database disconnected", "error.traceback": "Traceback..."}
        )
        mock_span.set_attribute.assert_called_with("error", True)


@pytest.mark.asyncio
async def test_traceparent_injection_in_http_adapter():
    payload = {
        "span_context": {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
    }

    mock_session = mock.Mock()
    mock_response = mock.AsyncMock()
    mock_response.json = mock.AsyncMock(return_value={"status": "ok"})

    mock_post_context = mock.MagicMock()
    mock_post_context.__aenter__.return_value = mock_response
    mock_session.post.return_value = mock_post_context

    patch_path = "eval_runner.adapters.common.SessionManager.get_session"
    with mock.patch(patch_path, return_value=mock_session):
        res = await http_adapter(payload, "http://localhost:5001/execute")
        assert res == {"status": "ok"}

        _, kwargs = mock_session.post.call_args
        expected = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        assert kwargs["headers"]["traceparent"] == expected


@pytest.mark.asyncio
async def test_traceparent_injection_in_sse_adapter():
    payload = {
        "span_context": {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
    }

    mock_session = mock.Mock()
    mock_response = mock.AsyncMock()

    async def mock_content_iter():
        yield b'data: {"content": "hello"}\n'
        yield b"data: [DONE]\n"

    mock_response.content = mock_content_iter()
    mock_post_context = mock.MagicMock()
    mock_post_context.__aenter__.return_value = mock_response
    mock_session.post.return_value = mock_post_context

    patch_path = "eval_runner.adapters.common.SessionManager.get_session"
    with mock.patch(patch_path, return_value=mock_session):
        res = await sse_http_adapter(payload, "http://localhost:5001/execute")
        assert res == {"content": "hello"}

        _, kwargs = mock_session.post.call_args
        expected = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        assert kwargs["headers"]["traceparent"] == expected
        assert kwargs["headers"]["Accept"] == "text/event-stream"


def test_otel_bridge_error_handling_graceful():
    """Ensure that the OTel telemetry bridge doesn't crash on invalid events or missing keys."""
    bridge = OTelTelemetryBridge()
    bridge.handle_event(Event(name=CoreEvents.TOOL_CALL, data=None))
    bridge.handle_event(Event(name=CoreEvents.TOOL_RESULT, data=None))
    bridge.handle_event(Event(name=CoreEvents.ERROR, data=None))
    bridge.handle_event(Event(name="unknown_event", data={}))

    # Trigger line 93 (unhandled exception inside handle_event try-except)
    bridge.handle_event(None)


def test_otel_bridge_initialization_with_endpoint():
    with mock.patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"}):
        with (
            mock.patch("opentelemetry.trace.get_tracer_provider") as mock_get_tp,
            mock.patch("opentelemetry.trace.set_tracer_provider") as mock_set_tp,
        ):
            # Setup trace.get_tracer_provider() to not have 'shutdown' attribute
            mock_provider = mock.MagicMock(spec=[])
            mock_get_tp.return_value = mock_provider

            # Mock OTLPSpanExporter dynamically in sys.modules
            mock_exporter_module = mock.MagicMock()
            sys.modules["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"] = (
                mock_exporter_module
            )

            # Mock TracerProvider and BatchSpanProcessor to verify usage
            mock_tp = mock.MagicMock()
            mock_bp = mock.MagicMock()

            tp_patch = "opentelemetry.sdk.trace.TracerProvider"
            bp_patch = "opentelemetry.sdk.trace.export.BatchSpanProcessor"
            with (
                mock.patch(tp_patch, return_value=mock_tp) as mock_tp_class,
                mock.patch(bp_patch, return_value=mock_bp),
            ):
                _ = OTelTelemetryBridge()
                mock_tp_class.assert_called_once()
                mock_set_tp.assert_called_once_with(mock_tp)


def test_otel_bridge_initialization_exception():
    with mock.patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"}):
        # Trigger exception on get_tracer_provider to test line 42 exception handler
        tp_get_patch = "opentelemetry.trace.get_tracer_provider"
        with mock.patch(tp_get_patch, side_effect=Exception("get_tp fail")):
            # Trigger exception on TracerProvider creation to test line 50 exception handler
            tp_patch = "opentelemetry.sdk.trace.TracerProvider"
            with mock.patch(tp_patch, side_effect=Exception("provider fail")):
                _ = OTelTelemetryBridge()


def test_otel_bridge_initialization_existing_provider():
    with mock.patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317"}):
        with (
            mock.patch("opentelemetry.trace.get_tracer_provider") as mock_get_tp,
            mock.patch("opentelemetry.trace.set_tracer_provider") as mock_set_tp,
        ):
            # Return provider WITH shutdown attribute to skip initialization
            mock_provider = mock.MagicMock()
            mock_provider.shutdown = mock.MagicMock()
            mock_get_tp.return_value = mock_provider

            _ = OTelTelemetryBridge()
            mock_set_tp.assert_not_called()
