"""
conftest.py

Shared fixtures and configuration for the MultiAgentEval test suite.
Includes logic to gracefully shut down OpenTelemetry to prevent I/O errors on closed files.
"""

import pytest

try:
    from opentelemetry import trace

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False


@pytest.fixture(scope="session", autouse=True)
def shutdown_tracer():
    """
    Explicitly flushes and shuts down the OpenTelemetry tracer provider at the end of the test session.
    This prevents 'ValueError: I/O operation on closed file' when the Python process exits.
    """
    yield
    if OTEL_AVAILABLE:
        try:
            provider = trace.get_tracer_provider()
            if hasattr(provider, "force_flush"):
                provider.force_flush()
            if hasattr(provider, "shutdown"):
                provider.shutdown()
        except Exception:
            # Best-effort shutdown; ignore errors during process teardown
            pass


@pytest.fixture(autouse=True)
def reset_plugins():
    """
    Ensures that the PluginManager and AgentAdapterRegistry are formally reset before each test.
    This respects Guardrail 4.6.6 (Singleton & Event-Bus Integrity).
    """
    from eval_runner.plugins import manager
    from eval_runner.engine import AgentAdapterRegistry
    from eval_runner.events import EventEmitter
    from eval_runner.console.routes import DebuggerStateStore
    
    manager.reset()
    AgentAdapterRegistry.reset()
    EventEmitter.reset()
    DebuggerStateStore.reset()
    yield
