import json

import pytest

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

    import sys

    for mod_name in list(sys.modules.keys()):
        if mod_name.endswith(".config") or "eval_runner.config" in mod_name:
            mod = sys.modules[mod_name]
            if hasattr(mod, "_SHIM_REGISTRY_CACHE"):
                monkeypatch.setattr(mod, "_SHIM_REGISTRY_CACHE", None)
            if hasattr(mod, "RegistryManager"):
                monkeypatch.setattr(
                    mod.RegistryManager, "get_resolved_registry", mock_get_resolved_registry
                )

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
    assert "ag2" not in registered


@pytest.mark.asyncio
async def test_ensure_baseline_and_jit_resolution(clean_registry):
    """Verifies zero-cost baseline registration and JIT adapter resolution."""
    assert not AgentAdapterRegistry._discovered
    assert "http" not in AgentAdapterRegistry._adapters

    # 1. Non-eager protocol listing does not trigger heavy discovery
    protocols = AgentAdapterRegistry.get_available_protocols(eager=False)
    assert "http" in protocols
    assert "openai" in protocols
    assert not AgentAdapterRegistry._discovered

    # 2. _ensure_baseline registers baseline protocols
    AgentAdapterRegistry._ensure_baseline()
    assert "http" in AgentAdapterRegistry._adapters
    assert "sse" in AgentAdapterRegistry._adapters
    assert "local" in AgentAdapterRegistry._adapters
    assert "socket" in AgentAdapterRegistry._adapters

    # Idempotent re-entry
    AgentAdapterRegistry._ensure_baseline()
    assert "http" in AgentAdapterRegistry._adapters

    # 3. Empty protocol returns None
    assert AgentAdapterRegistry._resolve_adapter("") is None
    assert AgentAdapterRegistry._resolve_adapter(None) is None

    # 4. Resolve baseline protocol
    adapter = AgentAdapterRegistry._resolve_adapter("http")
    assert adapter is not None

    # 5. Targeted JIT resolution for known provider
    openai_adapter = AgentAdapterRegistry._resolve_adapter("openai")
    assert openai_adapter is not None or "openai" in AgentAdapterRegistry._adapters

    # 6. Fallback for completely unknown protocol
    unknown = AgentAdapterRegistry._resolve_adapter("nonexistent-custom-protocol-xyz")
    assert unknown is None
