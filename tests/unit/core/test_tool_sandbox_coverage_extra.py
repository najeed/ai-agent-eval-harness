from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.tool_sandbox import ResourceRegistry, ToolSandbox


# --- ResourceRegistry ---
def test_resource_registry_cleanup_exception(tmp_path):
    registry = ResourceRegistry()
    test_dir = tmp_path / "test_dir"
    test_dir.mkdir()
    registry.register(test_dir)

    # Force an exception during rmtree_resilient
    with patch(
        "eval_runner.utils.rmtree_resilient", side_effect=PermissionError("Mocked Permission Error")
    ):
        # Should not crash
        registry.cleanup()


# --- SharedStateRegistry (via ToolSandbox) ---
@pytest.mark.asyncio
async def test_sandbox_shared_state_failures():
    scenario = {
        "id": "test",
        "agent_topology": {"agent_1": {"writes": ["ns_1:*"], "reads": ["ns_1:*"]}},
        "tools": {"write_tool": {}, "read_tool": {}},
    }
    sandbox = ToolSandbox(scenario)

    # Try writing to unauthorized namespace
    res_write = await sandbox.execute(
        "write_tool", {"shared_write": {"path": "ns_unauth:key", "value": 1}}, agent_name="agent_1"
    )
    assert res_write.get("status") == "error"
    assert "no write permission" in res_write.get("message", "")

    # Try reading from unauthorized namespace.
    # Must exist to trigger the missing coverage path properly.
    sandbox.shared_state.registry["ns_unauth:key"] = 1
    res_read = await sandbox.execute(
        "read_tool", {"shared_read": {"path": "ns_unauth:key"}}, agent_name="agent_1"
    )
    assert res_read.get("status") == "error"
    assert "no read permission" in res_read.get("message", "")


# --- AbstractSandbox Error Handling ---
@pytest.mark.asyncio
async def test_sandbox_setup_forensic_exception(tmp_path):
    scenario = {"id": "test", "run_id": "test_run"}
    forensics = MagicMock()
    forensics.snapshot_state.side_effect = Exception("Forensic snapshot failed")

    sandbox = ToolSandbox(scenario, forensics=forensics)
    sandbox.workspace_dir = tmp_path / "workspace"
    sandbox.terminal_jail = tmp_path / "jail"

    # Should catch exception and print to stderr, not crash
    await sandbox.setup()
    assert forensics.snapshot_state.called


@pytest.mark.asyncio
async def test_sandbox_get_full_state_exception():
    from eval_runner.tool_sandbox import AbstractSandbox

    class DummySandbox(AbstractSandbox):
        def execute(self, tool_name, params, agent_name=None):
            pass

        def get_active_simulators(self):
            return self._simulator_cache or {}

    scenario = {"id": "test"}
    sandbox = DummySandbox(scenario)

    mock_sim = AsyncMock()
    mock_sim.get_snapshot.side_effect = Exception("Simulator snapshot failed")

    sandbox._simulator_cache = {"broken_sim": mock_sim}

    state = await sandbox.get_full_state()
    assert state["broken_sim"] == {"error": "Simulator snapshot failed"}


@pytest.mark.asyncio
async def test_sandbox_teardown_simulator_cleanup_exception():
    scenario = {"id": "test"}
    sandbox = ToolSandbox(scenario)

    mock_sim = AsyncMock()
    mock_sim.cleanup.side_effect = Exception("Simulator cleanup failed")

    sandbox._simulator_cache = {"broken_sim": mock_sim}

    # Should catch exception and proceed
    await sandbox.teardown()
    assert mock_sim.cleanup.called


# --- ToolSandbox Edge Cases ---
@pytest.mark.asyncio
async def test_sandbox_active_simulators_instantiation_error():
    scenario = {"id": "test", "enabled_shims": ["dummy"]}
    sandbox = ToolSandbox(scenario)

    # Mock registry to return a shim that will raise an error on init
    with patch("eval_runner.config.RegistryManager.get_resolved_registry") as mock_reg:
        mock_reg.return_value = {"shims": {"dummy": {"type": "dummy"}}}

        class BrokenShim:
            def __init__(self, config):
                raise ValueError("Broken init")

        with (
            patch("eval_runner.simulators._INTERNAL_SIMULATOR_CLASSES", {"dummy": BrokenShim}),
            patch("eval_runner.config.GLOBAL_ENABLED_SHIMS", ["*"]),
        ):
            sims = sandbox.get_active_simulators()
            assert "dummy" not in sims


def test_sandbox_sanitize_value_dict_list():
    val = {"nested_dict": {"path": "../secret"}, "nested_list": ["..\\windows_secret"]}
    sanitized = ToolSandbox._sanitize_value(val)
    assert sanitized["nested_dict"]["path"] == "secret"
    assert sanitized["nested_list"][0] == "windows_secret"


def test_sandbox_scenario_relevant_shims_non_dict_outcome():
    scenario = {
        "workflow": {
            "nodes": [
                {"expected_outcome": "not_a_dict"},
                {"expected_outcome": ["not_a_dict", {"target": "shim:db"}]},
            ]
        }
    }
    sandbox = ToolSandbox(scenario)
    relevant = sandbox._get_scenario_relevant_shims()
    assert "db" in relevant
