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
async def test_tripartite_isolation_enforcement(tmp_path, clean_registry):
    """
    Verify that Protocols, Providers, and Frameworks are correctly isolated
    and whitelisted.
    """
    config_dir = tmp_path / ".aes" / "config" / "adapters"
    config_dir.mkdir(parents=True, exist_ok=True)
    policy_path = config_dir / "policy.json"

    # Policy: Enable HTTP (Protocol) and OpenAI (Provider). DISABLE ALL FRAMEWORKS.
    policy = {
        "adapters": {
            "active_protocols": ["http"],
            "active_providers": ["openai"],
            "active_frameworks": [],  # Strict zero-framework policy
        }
    }

    with open(policy_path, "w") as f:
        json.dump(policy, f)

    # Trigger Discovery
    AgentAdapterRegistry._discover()

    registered = AgentAdapterRegistry._adapters.keys()

    # Assertions
    assert "http" in registered, "Protocol 'http' should be whitelisted."
    assert "openai" in registered, "Provider 'openai' should be whitelisted."

    # Negative Assertions
    assert "local" not in registered, "Protocol 'local' should be blacklisted."
    for r in registered:
        base = r.split(":")[0]
        if base in ["ag2", "crewai", "langgraph", "langchain"]:
            raise AssertionError(f"FAIL: Framework '{r}' should be blacklisted.")


@pytest.mark.asyncio
async def test_version_sanitization_governance(tmp_path, clean_registry):
    """
    Verify that versioned protocols (e.g., ag2:v1) are correctly mapped
    to their base categories for governance checks.
    """
    config_dir = tmp_path / ".aes" / "config" / "adapters"
    config_dir.mkdir(parents=True, exist_ok=True)
    policy_path = config_dir / "policy.json"

    # Policy: Enable providers but DISABLE frameworks
    policy = {
        "adapters": {
            "active_protocols": ["http"],
            "active_providers": ["openai"],
            "active_frameworks": [],
        }
    }
    with open(policy_path, "w") as f:
        json.dump(policy, f)

    AgentAdapterRegistry._discover()

    # Attempt to register a versioned framework variant manually
    def mock_handler(p, e):
        return {}

    AgentAdapterRegistry.register("ag2:v1", mock_handler)

    assert "ag2:v1" not in AgentAdapterRegistry._adapters, (
        "Security Bypass: Versioned framework was registered despite 'ag2' being blacklisted."
    )


@pytest.mark.asyncio
async def test_explicit_category_override(tmp_path, clean_registry):
    """
    Verify that explicit category metadata in registration takes precedence.
    """
    config_dir = tmp_path / ".aes" / "config" / "adapters"
    config_dir.mkdir(parents=True, exist_ok=True)
    policy_path = config_dir / "policy.json"

    # Policy: Allow 'experimental' category (custom)
    policy = {"adapters": {"active_protocols": ["http"], "active_experimental": ["custom_proto"]}}
    with open(policy_path, "w") as f:
        json.dump(policy, f)

    AgentAdapterRegistry._discover()
    # Manually inject the whitelist for the custom category for the test
    AgentAdapterRegistry._active_whitelists["experimental"] = {"custom_proto"}

    def mock_handler(p, e):
        return {}

    AgentAdapterRegistry.register("custom_proto", mock_handler, category="experimental")

    assert "custom_proto" in AgentAdapterRegistry._adapters, (
        "Explicit category registration failed."
    )
