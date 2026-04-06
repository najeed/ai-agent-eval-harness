"""
conftest.py

Shared fixtures and configuration for the MultiAgentEval test suite.
"""

import sys

import pytest
import pytest_asyncio

try:
    from opentelemetry import trace

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False


@pytest.fixture(autouse=True)
def shutdown_tracer():
    """Explicitly shuts down the OpenTelemetry tracer provider at the end of each test."""
    yield
    if OTEL_AVAILABLE:
        try:
            provider = trace.get_tracer_provider()
            if hasattr(provider, "force_flush"):
                provider.force_flush()
            if hasattr(provider, "shutdown"):
                provider.shutdown()
        except Exception:
            pass


@pytest.fixture(autouse=True)
def reset_plugins():
    """Resets all registries before each test."""
    from eval_runner.engine import AgentAdapterRegistry
    from eval_runner.events import EventEmitter
    from eval_runner.metrics import MetricRegistry
    from eval_runner.plugins import manager

    manager.reset()
    AgentAdapterRegistry.reset()
    EventEmitter.reset()
    MetricRegistry.reset()
    yield


@pytest.fixture(autouse=True)
def reset_environ():
    """Resets os.environ after each test."""
    import os

    orig = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(orig)


@pytest.fixture(autouse=True)
def reset_cli_parser():
    """Reset CLI parser cache after each test to ensure clean state."""
    yield
    from eval_runner import cli

    cli._invalidate_parser_cache()


@pytest.fixture(autouse=True)
def check_loop_hygiene():
    """
    Diagnostic: Ensures that no event loop is left in a 'running' OR 'set' state after a test.
    In Python 3.14+, Runner.run() crashes if a loop is already running or if the policy is in a weird state.
    """
    import asyncio
    import warnings

    yield

    try:
        # get_event_loop() can return a loop that is set but not running.
        # Deprecated in some contexts but useful for diagnosing 3.14 policy noise.
        loop = asyncio.get_event_loop_policy().get_event_loop()
        if loop is not None:
            warnings.warn(
                f"Loop pollution: An event loop ({loop}) is still SET in the policy after test completion.",
                RuntimeWarning,
            )
    except Exception:
        # No loop set, which is the clean state we want.
        pass


@pytest_asyncio.fixture
async def adapter_stub(aiohttp_server):
    """Restore the correct aiohttp_server contract (returning the server object with .host and .port)."""  # noqa: E501
    from aiohttp import web

    async def handle_chat(request):
        return web.json_response({"summary": "This is a joke", "action": "final_answer"})

    app = web.Application()
    app.router.add_post("/api/chat", handle_chat)
    app.router.add_post("/execute_task", handle_chat)

    return await aiohttp_server(app)


pytest_plugins = []


def pytest_configure(config):
    """Register custom markers and configure pytest-asyncio for Python 3.14+."""
    config.addinivalue_line("markers", "asyncio: mark test as an asyncio test")
