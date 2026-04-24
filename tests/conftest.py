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
    from eval_runner.loader import reset_universal_registry
    from eval_runner.metrics import MetricRegistry
    from eval_runner.plugins import manager

    manager.reset()
    AgentAdapterRegistry.reset()
    reset()
    MetricRegistry.reset()
    reset_universal_registry()
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
    import asyncio

    from eval_runner.simulators import BaseSimulator

    if hasattr(BaseSimulator, "_instances"):
        # Create a copy to iterate while modifying
        for sim in list(BaseSimulator._instances):
            try:
                # Synchronous-safe cleanup for simulators that might be sync or async
                if hasattr(sim, "cleanup"):
                    # We use a transient loop if necessary, but simulators.py cleanup is async
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            loop.create_task(sim.cleanup())
                        else:
                            loop.run_until_complete(sim.cleanup())
                    except Exception:
                        pass
            except Exception:
                pass
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

    yield

    # Forensic loop cleanup (Python 3.14+ compliant)
    try:
        loop = asyncio.get_event_loop()
        if loop and not loop.is_closed():
            if loop.is_running():
                # This should not happen if tests are awaited properly
                pass
            loop.close()
    except RuntimeError:
        pass
    except Exception:
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


@pytest.fixture(autouse=True)
def isolate_plugin_registry(tmp_path, monkeypatch):
    """
    Global Safety Net: Automatically isolates the plugin registry for ALL tests.
    Redirects PERSISTENT_PLUGINS_PATH to a temporary file.
    Enables STRICT_PLUGINS mode to catch registration errors during tests.
    """
    import json

    # Create an empty registry in a nested directory to avoid polluting the root tmp_path
    # which some tests (like linter tests) scan for scenarios.
    registry_dir = tmp_path / ".isolated_config"
    registry_file = registry_dir / "registry.isolated"
    registry_dir.mkdir(parents=True, exist_ok=True)
    with open(registry_file, "w", encoding="utf-8") as f:
        json.dump({"plugins": []}, f)

    # Monkeypatch the paths in plugins.py
    from eval_runner import plugins

    monkeypatch.setattr(plugins, "PERSISTENT_PLUGINS_PATH", registry_file)
    monkeypatch.setattr(plugins, "STRICT_PLUGINS", True)

    # Also patch the environment variable for any child processes or lookups
    monkeypatch.setenv("STRICT_PLUGINS", "true")

    return registry_file
