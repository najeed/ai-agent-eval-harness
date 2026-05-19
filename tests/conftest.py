"""
conftest.py

Shared fixtures and configuration for the AgentV test suite.
"""

import asyncio

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


@pytest_asyncio.fixture(autouse=True)
async def reset_sessions():
    """
    Industrial-grade connection teardown.
    Closes pooled sessions and allows a grace period for underlying transport cleanup.
    """
    yield
    from eval_runner.adapters.common import SessionManager

    try:
        await SessionManager.close_all()
        # Cleanly await any pending background tasks (such as aiohttp's _wait_for_close)
        # to ensure no unawaited coroutine warnings under Python 3.14+
        await asyncio.sleep(0.05)
        loop = asyncio.get_running_loop()
        pending = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task(loop)]
        if pending:
            await asyncio.wait(pending, timeout=0.1)
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


@pytest_asyncio.fixture(autouse=True)
async def reset_environ():
    """Resets os.environ and triggers GC after each test for industrial isolation."""
    import gc
    import os

    orig = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(orig)
    # Physically purge stale references and close pending file handles (Windows Hardening)

    from eval_runner.simulators import BaseSimulator

    if hasattr(BaseSimulator, "_instances"):
        # Create a copy to iterate while modifying
        for sim in list(BaseSimulator._instances):
            try:
                if hasattr(sim, "cleanup"):
                    # Properly await the async cleanup in our async fixture
                    await sim.cleanup()
            except Exception:
                pass
        BaseSimulator._instances.clear()
    gc.collect()


@pytest.fixture(autouse=True)
def reset_cli_parser():
    """Reset CLI parser cache after each test to ensure clean state."""
    yield
    from eval_runner import cli

    cli._invalidate_parser_cache()


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
    import warnings

    config.addinivalue_line("markers", "asyncio: mark test as an asyncio test")
    config.addinivalue_line(
        "markers", "live: environment-gated integration tests running against CycleCore"
    )

    # Programmatically ignore aiohttp's unawaited _wait_for_close coroutine warning
    warnings.filterwarnings(
        "ignore",
        message=".*coroutine '_wait_for_close' was never awaited.*",
        category=RuntimeWarning,
    )

    # Programmatically ignore third-party site-packages deprecation/compatibility warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="google.*")
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="autogen.*")
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="daytona.*")
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="langchain_core.*")
    warnings.filterwarnings("ignore", category=DeprecationWarning, module="langgraph.*")
    warnings.filterwarnings("ignore", category=UserWarning, module="langchain_core.*")


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


@pytest.fixture
def pqc_client():
    """
    Conditional, environment-gated provider for the real CycleCoreClient.
    Protects against sys.modules mock pollution from other unit/integration tests
    by temporarily clearing the mocked cyclecore modules, performing the import,
    and restoring the mocks for subsequent tests.
    """
    import os
    import sys

    if not os.getenv("CYCLECORE_API_KEY"):
        pytest.skip("CYCLECORE_API_KEY not set; skipping live CycleCore test.")

    # Save existing sys.modules to isolate from mock pollution in other test suites
    saved_modules = {}
    for mod_name in ["cyclecore_pq", "cyclecore_pq.client"]:
        if mod_name in sys.modules:
            saved_modules[mod_name] = sys.modules.pop(mod_name)

    try:
        try:
            from cyclecore_pq.client import CycleCoreClient
        except ImportError as e:
            pytest.skip(f"cyclecore-pq package is not installed: {e}")
        client = CycleCoreClient(api_key=os.getenv("CYCLECORE_API_KEY"))

        # Dynamically inject sign_digest and verify_digest to match ZES interface
        import base64

        def sign_digest(digest: bytes, identity_id: str = None) -> str:
            result = client.sign(digest)
            return result.signature

        def verify_digest(signature: str | bytes, digest: bytes, identity_id: str = None) -> bool:
            if isinstance(signature, str):
                try:
                    # Try base64 decoding first
                    sig_bytes = base64.b64decode(signature)
                    if len(sig_bytes) < 100:
                        raise ValueError()
                except Exception:
                    try:
                        sig_bytes = bytes.fromhex(signature)
                    except Exception:
                        sig_bytes = signature.encode()
            else:
                sig_bytes = signature

            try:
                result = client.verify(digest, sig_bytes)
                return result.valid
            except Exception:
                return False

        client.sign_digest = sign_digest
        client.verify_digest = verify_digest
        return client
    finally:
        # Restore mock objects in sys.modules to prevent breaking other tests
        for mod_name, mod_obj in saved_modules.items():
            sys.modules[mod_name] = mod_obj
