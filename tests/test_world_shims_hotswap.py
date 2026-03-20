import pytest
from eval_runner.tool_sandbox import ToolSandbox
from eval_runner.plugins import BaseEvalPlugin, manager
from eval_runner.simulators import get_simulator_registry


class CustomShim:
    def execute(self, action, params):
        return {"status": "success", "message": "Custom shim executed"}


class CustomPlugin(BaseEvalPlugin):
    def on_register_simulators(self, registry):
        registry["custom"] = CustomShim()


def test_shim_hot_swapping():
    """Verify that a plugin can register a new shim dynamically."""
    # 1. Register a custom plugin
    plugin = CustomPlugin()
    manager.plugins.append(plugin)

    try:
        # 2. Get the registry and verify discovery
        registry = get_simulator_registry()
        assert "custom" in registry
        assert isinstance(registry["custom"], CustomShim)

        # 3. Execute via sandbox
        scenario = {"scenario_id": "test"}
        sandbox = ToolSandbox(scenario)
        result = sandbox.execute("custom_action", {})
        assert result["status"] == "success"
        assert result["message"] == "Custom shim executed"
    finally:
        # Cleanup
        manager.plugins.remove(plugin)


def test_shim_filtering_enabled():
    """Verify that only explicitly enabled shims are active if provided."""
    scenario = {"scenario_id": "filter-test", "enabled_shims": ["git"]}
    sandbox = ToolSandbox(scenario)
    active = sandbox.get_active_simulators()

    assert "git" in active
    assert "api" not in active
    assert "database" not in active


def test_shim_filtering_wildcard():
    """Verify that '*' (default) enables all shims."""
    scenario = {"scenario_id": "wildcard-test", "enabled_shims": ["*"]}
    sandbox = ToolSandbox(scenario)
    active = sandbox.get_active_simulators()

    assert len(active) >= 13  # All defaults
    assert "git" in active
    assert "stripe" in active


def test_shim_execution_not_enabled():
    """Verify that a shim call fails if it's not in the enabled list."""
    scenario = {"scenario_id": "denial-test", "enabled_shims": ["git"]}
    sandbox = ToolSandbox(scenario)

    # database_query is a shim tool, but 'database' is not enabled
    result = sandbox.execute("database_query", {"query": "SELECT *"})

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
    scenario = {"scenario_id": "global-clash-test", "enabled_shims": ["git", "api"]}
    sandbox = ToolSandbox(scenario)
    active = sandbox.get_active_simulators()

    assert "git" in active
    assert "api" not in active  # Should be blocked by global filter
