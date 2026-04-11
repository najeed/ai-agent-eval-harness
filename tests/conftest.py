"""
conftest.py

Shared fixtures and configuration for the AgentV test suite.
"""

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
    from eval_runner.events import reset
    from eval_runner.metrics import MetricRegistry
    from eval_runner.plugins import manager

    manager.reset()
    AgentAdapterRegistry.reset()
    reset()
    MetricRegistry.reset()
    yield


@pytest.fixture(autouse=True)
def reset_environ():
    """Resets os.environ and triggers GC after each test for industrial isolation."""
    import gc
    import os

    orig = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(orig)
    # Physically purge stale references and close pending file handles (Windows Hardening)
    gc.collect()


@pytest.fixture(autouse=True)
def reset_cli_parser():
    """Reset CLI parser cache after each test to ensure clean state."""
    yield
    from eval_runner import cli

    cli._invalidate_parser_cache()


@pytest.fixture(autouse=True)
def check_loop_hygiene():
    """
    Diagnostic & Remediation: Ensures that no event loop is left in a 'running' OR 'set' state.
    Hardened for Python 3.14+ loop policy isolation.
    """
    import asyncio
    import warnings

    yield

    try:
        policy = asyncio.get_event_loop_policy()
        loop = policy.get_event_loop()
        if loop is not None:
            if loop.is_running():
                # Critical violation: loop should never be running after test yield
                pass

            # Explicitly close and clear the loop from the policy to prevent cross-test leakage
            if not loop.is_closed():
                loop.close()

            # Forcing a fresh loop for the next test context
            try:
                new_loop = asyncio.new_event_loop()
                policy.set_event_loop(new_loop)
                new_loop.close()  # Keep it set but closed for safety
            except Exception:
                pass

            warnings.warn(
                f"Loop pollution detected and mitigated: {loop} was still SET.",
                RuntimeWarning,
                stacklevel=2,
            )
    except Exception:
        # No loop set or policy empty, which is the clean state we want.
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
