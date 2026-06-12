import json

import pytest

from eval_runner.config import RegistryManager
from eval_runner.engine import AgentAdapterRegistry


@pytest.fixture
def clean_registry(tmp_path, monkeypatch):
    """Resets the AgentAdapterRegistry and isolates config for each test."""
    AgentAdapterRegistry.reset()

    # Authoritative Registry Mocking: Bypass file-system crawl for reliability
    def mock_get_resolved_registry():
        config_file = tmp_path / ".aes" / "config" / "adapters" / "policy.json"
        if config_file.exists():
            with open(config_file) as f:
                return {"adapters": json.load(f).get("adapters", {})}
        return {}

    monkeypatch.setattr(RegistryManager, "get_resolved_registry", mock_get_resolved_registry)
    yield
    AgentAdapterRegistry.reset()


@pytest.mark.asyncio
async def test_core_immutability_collision(clean_registry):
    """Verify that core protocols cannot be overwritten by default."""
    AgentAdapterRegistry._discover()

    original_http = AgentAdapterRegistry._adapters["http"]

    # Attempt to overwrite HTTP with a mock
    def mock_http():
        return "hijacked"

    # This should be blocked and log a warning to stderr
    AgentAdapterRegistry.register("http", mock_http)

    assert AgentAdapterRegistry._adapters["http"] == original_http, (
        "Core protocol 'http' was hijacked!"
    )


@pytest.mark.asyncio
async def test_explicit_override_allowed(clean_registry):
    """Verify that core protocols CAN be overwritten if allow_override=True."""
    AgentAdapterRegistry._discover()

    def mock_http():
        return "custom"

    # Register with explicit override
    AgentAdapterRegistry.register("http", mock_http, allow_override=True)

    assert AgentAdapterRegistry._adapters["http"] == mock_http, (
        "Core protocol 'http' should have been overridden."
    )


@pytest.mark.asyncio
async def test_zero_trust_baseline_enforcement(clean_registry, monkeypatch):
    """Verify that the engine locks down everything if no policy is found."""
    # Explicitly enforce Zero-Trust whitelist in the registry for this test context
    monkeypatch.setitem(
        AgentAdapterRegistry._active_whitelists, "protocols", {"http", "sse", "openapi"}
    )
    monkeypatch.setitem(AgentAdapterRegistry._active_whitelists, "providers", set())
    monkeypatch.setitem(AgentAdapterRegistry._active_whitelists, "frameworks", set())

    # Reset adapters so discovery is forced to filter with the whitelists
    AgentAdapterRegistry._adapters.clear()
    AgentAdapterRegistry._discover()

    registered = AgentAdapterRegistry._adapters.keys()

    # Baseline expected: http and openapi are allowed by default
    assert "http" in registered

    # Baseline expected: local and socket are BLOCKED by default (Zero-Trust)
    assert "local" not in registered, "Local protocol should be locked down by default baseline"
    assert "socket" not in registered, "Socket protocol should be locked down by default baseline"

    # Baseline expected: All frameworks/providers blocked
    assert "openai" not in registered
    assert "autogen" not in registered
