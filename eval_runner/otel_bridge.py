import os
import sys

from .events import CoreEvents, Event
from .plugins import BaseEvalPlugin


class OTelTelemetryBridge(BaseEvalPlugin):
    """
    Standardized OpenTelemetry Telemetry Bridge.
    Intercepts core system events and maps them to OpenTelemetry Semantic Conventions.
    """

    _subscribed = False

    def __init__(self):
        self._initialize_otel()

        if not OTelTelemetryBridge._subscribed:
            from . import events

            events.subscribe(self.handle_event)
            OTelTelemetryBridge._subscribed = True

    def _initialize_otel(self):
        """Initializes the global TracerProvider if OTLP endpoint is configured."""
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        service_name = os.getenv("OTEL_SERVICE_NAME", "agentv-core")

        if not otlp_endpoint:
            return

        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            try:
                provider = trace.get_tracer_provider()
                if hasattr(provider, "shutdown"):
                    return
            except Exception:
                pass

            resource = Resource.create(attributes={"service.name": service_name})
            provider = TracerProvider(resource=resource)
            processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)
        except Exception as e:
            sys.stderr.write(f"   [OTel Bridge] OTLP Initialization failed: {e}\n")

    def handle_event(self, event: Event):
        """Standard listener callback to map AgentV events to active OTel Spans."""
        try:
            from opentelemetry import trace

            ev_name = event.name
            ev_data = event.data

            # Map events to OTel Spans or Events on active Spans
            if ev_name == CoreEvents.TOOL_CALL:
                current_span = trace.get_current_span()
                if current_span and current_span.is_recording():
                    current_span.add_event(
                        "tool.call",
                        {
                            "tool.name": ev_data.get("tool", "unknown"),
                            "tool.arguments": str(ev_data.get("arguments", {})),
                        },
                    )
            elif ev_name == CoreEvents.TOOL_RESULT:
                current_span = trace.get_current_span()
                if current_span and current_span.is_recording():
                    current_span.add_event(
                        "tool.result",
                        {
                            "tool.name": ev_data.get("tool", "unknown"),
                            "tool.result": str(ev_data.get("result", "")),
                        },
                    )
            elif ev_name == CoreEvents.ERROR:
                current_span = trace.get_current_span()
                if current_span and current_span.is_recording():
                    current_span.set_attribute("error", True)
                    current_span.add_event(
                        "error",
                        {
                            "error.message": ev_data.get("message", ""),
                            "error.traceback": ev_data.get("traceback", ""),
                        },
                    )
        except Exception:
            pass
