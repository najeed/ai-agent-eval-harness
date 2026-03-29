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
    """
    from eval_runner.plugins import manager
    from eval_runner.engine import AgentAdapterRegistry
    from eval_runner.events import EventEmitter
    from eval_runner.console.routes import DebuggerStateStore
    from eval_runner.metrics import MetricRegistry
    
    manager.reset()
    AgentAdapterRegistry.reset()
    EventEmitter.reset()
    DebuggerStateStore.reset()
    MetricRegistry.reset()
    yield


@pytest.fixture(autouse=True)
def reset_environ():
    """
    Provides an automatic rollback for os.environ changes after every test.
    Prevents configuration leakage between test cases.
    """
    import os
    original_environ = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(original_environ)


@pytest.fixture
def async_mock():
    """
    Standardized AsyncMock fixture for cross-version compatibility.
    """
    from unittest.mock import MagicMock
    try:
        from unittest.mock import AsyncMock
    except ImportError:
        # Fallback for Python < 3.8
        class AsyncMock(MagicMock):
            async def __call__(self, *args, **kwargs):
                return super(AsyncMock, self).__call__(*args, **kwargs)
    
    return AsyncMock


import pytest_asyncio

@pytest_asyncio.fixture
async def adapter_stub(aiohttp_server):
    """
    High-fidelity aiohttp server stub for simulating agent provider APIs.
    """
    from aiohttp import web
    
    async def handle_chat(request):
        data = await request.json()
        if data.get("force_error"):
            return web.Response(text="Claude internal error", status=500)
        
        prompt = data.get("prompt") or data.get("task_description") or data.get("task_description", "")
        
        if prompt == "Crash":
             return web.Response(status=500, text="Internal Error")
        
        if prompt == "Hello agent":
            return web.json_response({
                "summary": "Hello user!",
                "action": "call_tool",
                "tool_name": "search",
                "tool_params": {"query": "test"},
                "tool_output": "test results",
            })
            
        return web.json_response({
            "choices": [{"message": {"content": "This is a joke"}}],
            "outputs": [{"text": "This is a joke"}],
            "summary": "This is a joke",
            "action": "final_answer"
        })

    app = web.Application()
    app.router.add_post("/api/chat", handle_chat)
    app.router.add_post("/v1/messages", handle_chat)
    app.router.add_post("/execute_task", handle_chat)
    app.router.add_post("/invoke", handle_chat)
    app.router.add_post("/{model}:generateContent", handle_chat)
    app.router.add_post("/v1/models/{model}:generateContent", handle_chat)
    
    return await aiohttp_server(app)
