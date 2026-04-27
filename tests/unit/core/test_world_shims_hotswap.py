import pytest

from eval_runner.plugins import BaseEvalPlugin, manager
from eval_runner.simulators import get_simulator_registry
from eval_runner.tool_sandbox import ToolSandbox


class CustomShim:
    def __init__(self, **kwargs):
        pass

    async def execute(self, action, params):
        return {"status": "success", "message": "Custom shim executed"}


class CustomPlugin(BaseEvalPlugin):
    def on_register_simulators(self, registry):
        registry["custom"] = CustomShim


@pytest.mark.asyncio
async def test_shim_hot_swapping():
    """Verify that a plugin can register a new shim dynamically."""
    # 1. Register a custom plugin
    plugin = CustomPlugin()
    manager.plugins.append(plugin)

    try:
        # 2. Get the registry and verify discovery
        registry = get_simulator_registry()
        assert "custom" in registry
        assert registry["custom"] is CustomShim

        # 3. Execute via sandbox
        # Mocking admin approval for 'custom' shim as per new Master Gate architecture
        from unittest.mock import patch

        from eval_runner import config

        with patch.object(config, "GLOBAL_ENABLED_SHIMS", config.GLOBAL_ENABLED_SHIMS + ["custom"]):
            # Updated: Explicitly enable 'custom' or use a relevant tool
            # to satisfy the new discovery logic.
            scenario = {"id": "test", "enabled_shims": ["custom"]}
            sandbox = ToolSandbox(scenario)
            result = await sandbox.execute("custom_action", {})
        assert result["status"] == "success"
        assert result["message"] == "Custom shim executed"
    finally:
        # Cleanup
        manager.plugins.remove(plugin)


def test_shim_filtering_enabled():
    """Verify that only explicitly enabled shims are active if provided."""
    scenario = {"id": "filter-test", "enabled_shims": ["git"]}
    sandbox = ToolSandbox(scenario)
    active = sandbox.get_active_simulators()

    assert "git" in active
    assert "api" not in active
    assert "database" not in active


def test_shim_filtering_wildcard():
    """Verify that '*' (default) enables all shims."""
    scenario = {"id": "wildcard-test", "enabled_shims": ["*"]}
    sandbox = ToolSandbox(scenario)
    active = sandbox.get_active_simulators()

    assert len(active) >= 13  # All defaults
    assert "git" in active
    assert "stripe" in active


@pytest.mark.asyncio
async def test_shim_execution_not_enabled():
    """Verify that a shim call fails if it's not in the enabled list."""
    scenario = {"id": "denial-test", "enabled_shims": ["git"]}
    sandbox = ToolSandbox(scenario)

    # database_query is a shim tool, but 'database' is not enabled
    result = await sandbox.execute("database_query", {"query": "SELECT *"})

    # Should fall back to the default "Executed database_query" message
    # instead of being routed to the DatabaseSimulator.
    assert "rows" not in result
    assert "Executed database_query" in result["message"]


def test_shim_global_filtering(monkeypatch):
    """Verify that global system-wide filtering takes precedence."""
    # 1. Force global filter to ONLY include 'git'
    import eval_runner.config as config

    monkeypatch.setattr(config, "GLOBAL_ENABLED_SHIMS", ["git"])

    # 2. Scenario tries to enable 'api' (which is globally disabled)
    scenario = {"id": "global-clash-test", "enabled_shims": ["git", "api"]}
    sandbox = ToolSandbox(scenario)
    active = sandbox.get_active_simulators()

    assert "git" in active
    assert "api" not in active  # Should be blocked by global filter


def test_shim_relevance_global_gate(monkeypatch):
    """Verify that even relevant shims are blocked if not globally enabled."""
    import eval_runner.config as config

    # 1. Block 'database' globally
    monkeypatch.setattr(config, "GLOBAL_ENABLED_SHIMS", ["git"])

    # 2. Scenario contract mentions 'database' as relevant
    scenario = {
        "id": "relevance-gate-test",
        "workflow": {
            "nodes": [{"id": "n1", "expected_outcome": [{"target": "shim:database.users"}]}]
        },
    }
    sandbox = ToolSandbox(scenario)
    active = sandbox.get_active_simulators()

    # Even though it's relevant, it's not globally enabled
    assert "database" not in active


def test_shim_strict_discovery_omitted():
    """Verify that omitting enabled_shims auto-activates relevant shims."""
    scenario = {
        "id": "discovery-test",
        "workflow": {
            "nodes": [{"id": "n1", "expected_outcome": [{"target": "shim:database.users"}]}]
        },
    }
    sandbox = ToolSandbox(scenario)
    active = sandbox.get_active_simulators()

    assert "database" in active
    assert "git" not in active  # Not relevant, not enabled


def test_shim_discovery_via_tool_prefix():
    """Verify that tool prefixes trigger auto-discovery when enabled_shims is omitted."""
    scenario = {
        "id": "tool-discovery-test",
        "workflow": {"nodes": [{"id": "n1", "required_tools": ["git_commit"]}]},
    }
    sandbox = ToolSandbox(scenario)
    active = sandbox.get_active_simulators()

    assert "git" in active
    assert "database" not in active


def test_shim_explicit_whitelist_disables_discovery():
    """Verify that an explicit whitelist ignores other relevant shims (Hard Guardrail)."""
    scenario = {
        "id": "whitelist-guardrail-test",
        "enabled_shims": ["git"],  # ONLY Git
        "workflow": {
            "nodes": [
                # Database is relevant, but NOT in the whitelist above
                {"id": "n1", "expected_outcome": [{"target": "shim:database.users"}]}
            ]
        },
    }
    sandbox = ToolSandbox(scenario)
    active = sandbox.get_active_simulators()

    assert "git" in active
    assert "database" not in active  # Blocked by the explicit whitelist guardrail
