"""
conftest.py

Shared fixtures and configuration for the MultiAgentEval test suite.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock

try:
    from opentelemetry import trace
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

@pytest.fixture(scope="session", autouse=True)
def shutdown_tracer():
    """Explicitly shuts down the OpenTelemetry tracer provider at the end of the session."""
    yield
    if OTEL_AVAILABLE:
        try:
            provider = trace.get_tracer_provider()
            if hasattr(provider, "force_flush"): provider.force_flush()
            if hasattr(provider, "shutdown"): provider.shutdown()
        except Exception:
            pass

@pytest.fixture(autouse=True)
def reset_plugins():
    """Resets all registries before each test."""
    from eval_runner.plugins import manager
    from eval_runner.engine import AgentAdapterRegistry
    from eval_runner.events import EventEmitter
    from eval_runner.metrics import MetricRegistry
    
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

import pytest_asyncio

@pytest_asyncio.fixture
async def adapter_stub(aiohttp_server):
    """Restore the correct aiohttp_server contract (returning the server object with .host and .port)."""
    from aiohttp import web
    
    async def handle_chat(request):
        return web.json_response({
            "summary": "This is a joke",
            "action": "final_answer"
        })

    app = web.Application()
    app.router.add_post("/api/chat", handle_chat)
    app.router.add_post("/execute_task", handle_chat)
    
    return await aiohttp_server(app)
