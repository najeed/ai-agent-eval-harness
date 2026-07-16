from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner import config
from eval_runner.events import EventEmitter
from eval_runner.tool_sandbox import (
    AbstractSandbox,
    ResourceRegistry,
    SharedStateRegistry,
    ToolSandbox,
)


@pytest.fixture
def base_scenario():
    return {
        "id": "test_scenario",
        "run_id": "test_run_123",
        "initial_state": {"key": "val"},
        "tools": {
            "my_tool": {
                "state_changes": [{"path": "new_key", "value": "new_val"}],
                "output": {"status": "success", "data": "tool_data"},
            }
        },
        "policies": {"restricted_tool": {"max_limit": 5}},
        "agent_topology": {"agent_a": {"reads": ["global", "ns:*"], "writes": ["global"]}},
    }


# --- Resource Registry Tests ---


def test_resource_registry_cleanup(tmp_path):
    registry = ResourceRegistry()
    f1 = tmp_path / "file1.txt"
    f1.write_text("data")
    d1 = tmp_path / "dir1"
    d1.mkdir()
    (d1 / "file2.txt").write_text("data2")

    registry.register(f1)
    registry.register(d1)

    registry.cleanup()

    assert not f1.exists()
    assert not d1.exists()


def test_resource_registry_cleanup_error(tmp_path, capsys):
    registry = ResourceRegistry()
    d1 = tmp_path / "dir1"
    d1.mkdir()
    registry.register(d1)

    with patch("eval_runner.utils.rmtree_resilient", side_effect=Exception("Disk locked")):
        registry.cleanup()

    captured = capsys.readouterr()
    assert "Cleanup failed" in captured.err


# --- Shared State Registry Tests ---


def test_shared_state_registry_permissions():
    topology = {"agent_a": {"writes": ["ns1", "ns2:*"], "reads": ["*"]}}
    bus = EventEmitter(run_id="test")
    reg = SharedStateRegistry(topology, event_bus=bus)

    assert reg.write("agent_a", "ns1:key1", "val1") is True
    assert reg.write("agent_a", "ns2:sub:key", "val2") is True

    assert reg.write("agent_a", "ns3:key", "val3") is False
    assert reg.registry.get("ns3:key") is None

    assert reg.read("agent_a", "ns1:key1") == "val1"


def test_shared_state_registry_wildcard_permissions():
    topology = {"agent_admin": {"writes": ["*"], "reads": ["*"]}}
    reg = SharedStateRegistry(topology)

    assert reg.write("agent_admin", "any:path", "data") is True
    assert reg.read("agent_admin", "any:path") == "data"


# --- Tool Sandbox Path Injection and Initialization ---


def test_sandbox_initialization_with_di(base_scenario, tmp_path):
    ws_root = tmp_path / "ws_root"
    jail_root = tmp_path / "jail_root"

    sandbox = ToolSandbox(scenario=base_scenario, workspace_root=ws_root, jail_root=jail_root)

    assert sandbox.workspace_dir == ws_root / "test_run_123"
    assert sandbox.terminal_jail == jail_root


def test_sandbox_fallback_jail_without_run_id(tmp_path):
    scenario = {"id": "no_run_id"}
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path)

    assert sandbox.run_id is not None
    assert "terminal_jail" in str(sandbox.terminal_jail)
    assert sandbox.workspace_dir == tmp_path / sandbox.run_id


# --- Sandbox Setup and Teardown ---


@pytest.mark.asyncio
async def test_sandbox_setup_teardown(base_scenario, tmp_path):
    ws_root = tmp_path / "ws_root"
    jail_root = tmp_path / "jail_root"

    sandbox = ToolSandbox(
        scenario=base_scenario, workspace_root=ws_root, jail_root=jail_root, forensics=MagicMock()
    )

    await sandbox.setup()
    assert sandbox.workspace_dir.exists()
    assert sandbox.terminal_jail.exists()
    sandbox.forensics.snapshot_state.assert_called()

    sandbox.scenario["metadata"] = {"cleanup_workspace": True, "cleanup_terminal_jail": True}

    mock_sim = AsyncMock()
    sandbox._simulator_cache = {"my_shim": mock_sim}

    await sandbox.teardown()

    mock_sim.cleanup.assert_awaited()
    assert not sandbox.workspace_dir.exists()
    assert not sandbox.terminal_jail.exists()


def test_register_artifact(base_scenario, tmp_path):
    sandbox = ToolSandbox(base_scenario, workspace_root=tmp_path, forensics=MagicMock())
    art_path = tmp_path / "art.txt"

    sandbox.register_artifact(art_path, alias="my_art")
    assert art_path in sandbox.resources._tracked_paths
    sandbox.forensics.register_artifact.assert_called_with(art_path, "my_art")


# --- Sandbox Execution Logic ---


@pytest.mark.asyncio
async def test_sandbox_execute_standard_tool(base_scenario, tmp_path):
    bus = EventEmitter(run_id="r1")
    sandbox = ToolSandbox(base_scenario, event_bus=bus, workspace_root=tmp_path)

    res = await sandbox.execute("my_tool", {})
    assert res["status"] == "success"
    assert sandbox.state["new_key"] == "new_val"


@pytest.mark.asyncio
async def test_sandbox_execute_policy_violation(base_scenario, tmp_path):
    sandbox = ToolSandbox(base_scenario, workspace_root=tmp_path)

    res = await sandbox.execute("restricted_tool", {"amount": 10})
    assert res["status"] == "policy_violation"
    assert "exceeds limit" in res["violation"]


@pytest.mark.asyncio
async def test_sandbox_execute_shared_state(base_scenario, tmp_path):
    sandbox = ToolSandbox(base_scenario, workspace_root=tmp_path)

    res = await sandbox.execute(
        "my_tool", {"shared_write": {"path": "global:data", "value": 1}}, agent_name="agent_a"
    )
    assert res["status"] == "success"
    assert sandbox.shared_state.registry["global:data"] == 1

    res = await sandbox.execute(
        "my_tool", {"shared_read": {"path": "global:data"}}, agent_name="agent_a"
    )
    assert res["status"] == "success"

    res = await sandbox.execute(
        "my_tool", {"shared_write": {"path": "restricted:data", "value": 1}}, agent_name="agent_a"
    )
    assert res["status"] == "error"
    assert "no write permission" in res["message"]

    sandbox.shared_state.registry["restricted:data"] = 1
    res = await sandbox.execute(
        "my_tool", {"shared_read": {"path": "restricted:data"}}, agent_name="agent_a"
    )
    assert res["status"] == "error"
    assert "no read permission" in res["message"]


@pytest.mark.asyncio
async def test_sandbox_execute_shim_routing(base_scenario, tmp_path):
    sandbox = ToolSandbox(base_scenario, workspace_root=tmp_path)

    mock_sim = AsyncMock()
    mock_sim.execute.return_value = {"status": "success", "payload": {"shim": "response"}}
    sandbox._simulator_cache = {"db": mock_sim}

    res = await sandbox.execute("db_query", {"query": "SELECT *"})
    assert res == {"status": "success", "payload": {"shim": "response"}}
    mock_sim.execute.assert_awaited_with("db_query", {"query": "SELECT *"})


# --- Security and Sanitization ---


def test_sanitize_path():
    assert ToolSandbox._sanitize_path("valid/path") == f"{config.SANDBOX_VFS_PREFIX}valid/path"
    assert ToolSandbox._sanitize_path("../../../etc/passwd") == f"{config.SANDBOX_VFS_PREFIX}passwd"


def test_sanitize_value():
    dangerous = f"val {config.SHELL_METABLOCKS[0]} bad"
    safe = ToolSandbox._sanitize_value(dangerous)
    assert config.SHELL_METABLOCKS[0] not in safe

    assert ToolSandbox._sanitize_value("../../path") == "path"

    nested = {"k": ["../../v"]}
    safe_nested = ToolSandbox._sanitize_value(nested)
    assert safe_nested["k"][0] == "v"


# --- Shim Discovery and Registry Integration ---


@pytest.mark.asyncio
async def test_get_active_simulators_and_full_state(base_scenario, tmp_path, monkeypatch):
    sandbox = ToolSandbox(base_scenario, workspace_root=tmp_path)

    monkeypatch.setattr(config, "GLOBAL_ENABLED_SHIMS", ["test_shim"])
    sandbox.scenario["enabled_shims"] = ["test_shim"]

    class DummyShim:
        def __init__(self, config=None):
            self.terminal_jail = None
            self.sandbox = None

        async def get_snapshot(self):
            return {"shim_state": "ok"}

    mock_registry = {"shims": {"test_shim": {}}}

    with patch(
        "eval_runner.config.RegistryManager.get_resolved_registry", return_value=mock_registry
    ):
        with patch(
            "eval_runner.simulators.get_simulator_registry", return_value={"test_shim": DummyShim}
        ):
            active = sandbox.get_active_simulators()
            assert "test_shim" in active
            assert active["test_shim"].terminal_jail == sandbox.terminal_jail

            full = await sandbox.get_full_state()
            assert full["shims"]["test_shim"]["shim_state"] == "ok"
            assert "world" in full
            assert "shared" in full


@pytest.mark.asyncio
async def test_get_active_simulators_error_handling(base_scenario, tmp_path, capsys):
    sandbox = ToolSandbox(base_scenario, workspace_root=tmp_path)
    sandbox._simulator_cache = {}

    mock_sim = AsyncMock()
    mock_sim.get_snapshot.side_effect = Exception("Shim crashed")
    sandbox._simulator_cache["broken_shim"] = mock_sim

    await sandbox.get_full_state()

    captured = capsys.readouterr()
    assert "Failed to snapshot shim" in captured.err


def test_get_scenario_relevant_shims(base_scenario, tmp_path, monkeypatch):
    base_scenario["workflow"] = {
        "nodes": [
            {
                "expected_outcome": [{"target": "shim:db.query", "expected": 1}],
                "required_tools": ["api_fetch"],
            }
        ]
    }

    monkeypatch.setattr(config, "GLOBAL_ENABLED_SHIMS", ["db", "api"])

    sandbox = ToolSandbox(base_scenario, workspace_root=tmp_path)
    with patch(
        "eval_runner.simulators.get_simulator_registry", return_value={"db": object, "api": object}
    ):
        relevant = sandbox._get_scenario_relevant_shims()

    assert "db" in relevant
    assert "api" in relevant


# --- Edge Case / Missing Coverage ---


class ConcreteSandbox(AbstractSandbox):
    def execute(self, *args, **kwargs):
        pass


@pytest.mark.asyncio
async def test_abstract_sandbox_get_full_state(base_scenario, tmp_path, capsys):
    sandbox = ConcreteSandbox(base_scenario, workspace_root=tmp_path)

    class OkShim:
        async def get_snapshot(self):
            return {"ok": 1}

    class BadShim:
        async def get_snapshot(self):
            raise Exception("disk")

    sandbox.get_active_simulators = MagicMock(
        return_value={"ok_shim": OkShim(), "bad_shim": BadShim()}
    )
    state = await sandbox.get_full_state()
    assert state["ok_shim"]["ok"] == 1
    assert "error" in state["bad_shim"]
    assert "Failed to snapshot shim" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_sandbox_setup_forensics_error(base_scenario, tmp_path, capsys):
    sandbox = ToolSandbox(base_scenario, workspace_root=tmp_path, forensics=MagicMock())
    sandbox.get_full_state = AsyncMock(side_effect=Exception("state error"))
    await sandbox.setup()
    assert "Failed to capture initial forensic baseline" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_sandbox_teardown_simulator_error(base_scenario, tmp_path):
    sandbox = ToolSandbox(base_scenario, workspace_root=tmp_path)
    sandbox.scenario["metadata"] = {}
    mock_sim = AsyncMock()
    mock_sim.cleanup.side_effect = Exception("Cleanup crash")
    sandbox._simulator_cache = {"broken": mock_sim}
    await sandbox.teardown()
    mock_sim.cleanup.assert_awaited()


def test_get_scenario_relevant_shims_all_global(base_scenario, tmp_path, monkeypatch):
    base_scenario["workflow"] = {"nodes": [{"expected_outcome": [{"target": "message"}]}]}
    base_scenario["tools"] = {"db_query": {}}
    monkeypatch.setattr(config, "GLOBAL_ENABLED_SHIMS", ["*"])
    sandbox = ToolSandbox(base_scenario, workspace_root=tmp_path)
    with patch("eval_runner.simulators.get_simulator_registry", return_value={"db": object}):
        relevant = sandbox._get_scenario_relevant_shims()
    assert "db" in relevant


@pytest.mark.asyncio
async def test_get_active_simulators_instantiation_errors(
    base_scenario, tmp_path, monkeypatch, capsys
):
    sandbox = ToolSandbox(base_scenario, workspace_root=tmp_path)
    monkeypatch.setattr(config, "GLOBAL_ENABLED_SHIMS", ["*"])
    sandbox.scenario["enabled_shims"] = ["*"]

    class CrashShim:
        def __init__(self, config=None):
            raise Exception("init crash")

    mock_registry = {"shims": {"db": {"type": "db"}, "unknown": {"type": "weird"}}}
    with patch(
        "eval_runner.config.RegistryManager.get_resolved_registry", return_value=mock_registry
    ):
        with patch("eval_runner.simulators.get_simulator_registry", return_value={"db": CrashShim}):
            sandbox.get_active_simulators()

    captured = capsys.readouterr().err
    assert "Failed to instantiate 'db'" in captured
    assert "Unknown shim type 'weird'" in captured
