"""
test_tool_sandbox.py

Test suite for the ToolSandbox mock tool execution environment.
Aligned with OpenCore modular architecture and explicit tool definitions.
"""

from pathlib import Path

import pytest

from eval_runner.tool_sandbox import ToolSandbox


@pytest.mark.asyncio
async def test_sandbox_known_tool(tmp_path):
    """Test that a known tool returns the expected result from the scenario."""
    scenario = {
        "aes_version": 1.4,
        "tools": {
            "get_customer_details": {
                "output": {
                    "status": "success",
                    "tool_name": "get_customer_details",
                    "data": "info",
                }
            }
        },
        "workflow": {
            "nodes": [
                {"id": "t1", "task_description": "task", "required_tools": ["get_customer_details"]}
            ],
            "edges": [],
        },
    }
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")

    result = await sandbox.execute("get_customer_details", {"customer_id": "cust_123"})
    assert result["status"] == "success"
    assert result["tool_name"] == "get_customer_details"


@pytest.mark.asyncio
async def test_sandbox_unknown_tool(tmp_path):
    """Test that an unknown tool returns a default or success message (per current impl)."""
    scenario = {
        "aes_version": 1.4,
        "workflow": {
            "nodes": [
                {"id": "t1", "task_description": "task", "required_tools": ["get_customer_details"]}
            ],
            "edges": [],
        },
    }
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")

    result = await sandbox.execute("nonexistent_tool", {})
    assert result["status"] == "success"  # Default behavior in updated tool_sandbox.py
    assert "Executed nonexistent_tool" in result["message"]


@pytest.mark.asyncio
async def test_sandbox_state_initialization(tmp_path):
    """Test that state is initialized correctly from the scenario."""
    scenario = {
        "aes_version": 1.4,
        "initial_state": {"customer_name": "Jane Doe", "balance": 100},
        "workflow": {
            "nodes": [{"id": "t1", "task_description": "task", "required_tools": ["any_tool"]}],
            "edges": [],
        },
    }
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    assert sandbox.state == {"customer_name": "Jane Doe", "balance": 100}


@pytest.mark.asyncio
async def test_sandbox_state_mutation(tmp_path):
    """Test that explicit 'state_changes' mutate the state."""
    scenario = {
        "aes_version": 1.4,
        "initial_state": {"current_plan": "Basic"},
        "tools": {
            "update_plan": {
                "state_changes": [{"path": "current_plan", "value": "Premium"}],
                "output": {"status": "success"},
            }
        },
        "workflow": {
            "nodes": [{"id": "t1", "task_description": "task", "required_tools": ["update_plan"]}],
            "edges": [],
        },
    }
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")

    await sandbox.execute("update_plan", {"current_plan": "Premium"})
    assert sandbox.state["current_plan"] == "Premium"


@pytest.mark.asyncio
async def test_sandbox_lifecycle(tmp_path):
    """Verify setup/teardown with a controlled tmp directory."""
    scenario = {
        "aes_version": 1.4,
        "id": "lifecycle-test",
        "metadata": {"cleanup_workspace": True},
    }
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")

    await sandbox.setup()
    assert Path(sandbox.workspace_dir).exists()

    await sandbox.teardown()
    assert not Path(sandbox.workspace_dir).exists()


@pytest.mark.asyncio
async def test_sandbox_cleanup_persistence(tmp_path):
    """Verify that cleanup_workspace=False preserves the directory."""
    scenario = {"id": "persist-test", "metadata": {"cleanup_workspace": False}}
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")

    await sandbox.setup()
    ws_dir = sandbox.workspace_dir
    assert Path(ws_dir).exists()

    await sandbox.teardown()
    assert Path(ws_dir).exists()  # Should still exist


def test_tool_sandbox_shared_state_registry_permissions():
    """Verify namespaced read/write permissions in SharedStateRegistry."""
    from eval_runner.tool_sandbox import SharedStateRegistry

    topology = {
        "agent_a": {"writes": ["namespace_1"], "reads": ["namespace_2"]},
        "agent_b": {"writes": ["namespace_2"], "reads": ["namespace_1"]},
    }
    registry = SharedStateRegistry(topology)

    # Agent A writes to allowed namespace
    assert registry.write("agent_a", "namespace_1:key", "val1") is True
    # Agent B cannot write to namespace_1
    assert registry.write("agent_b", "namespace_1:key", "val2") is False

    # Agent B can read from namespace_1
    assert registry.read("agent_b", "namespace_1:key") == "val1"
    # Agent A cannot read from namespace_1 (it only reads namespace_2)
    assert registry.read("agent_a", "namespace_1:key") is None


def test_sandbox_path_sanitization():
    """Verify that file paths are properly sanitized to prevent traversals."""
    # Test _sanitize_path logic (Lines 201+)
    # It should strip traversals and add prefix
    res = ToolSandbox._sanitize_path("../../etc/passwd")
    assert ".." not in res
    assert res == "vfs:/passwd"


def test_sandbox_value_sanitization():
    """Verify that command values are sanitized against shell meta-characters."""
    # Test _sanitize_value logic (Lines 231+)
    # It should strip shell meta-characters
    val = ToolSandbox._sanitize_value("ls -la; rm -rf /")
    assert ";" not in val
    assert "ls -la rm -rf /" in val


def test_shared_state_events():
    """Verify that SharedStateRegistry emits events for both reads and writes."""
    from unittest.mock import MagicMock

    from eval_runner.tool_sandbox import SharedStateRegistry

    mock_bus = MagicMock()
    topology = {"agent_a": {"writes": ["*"], "reads": ["*"]}}
    registry = SharedStateRegistry(topology, event_bus=mock_bus)

    # 1. Test state_write event
    registry.write("agent_a", "global:key", "value")
    mock_bus.emit.assert_any_call(
        "state_write", {"agent": "agent_a", "path": "global:key", "value": "value"}
    )

    # 2. Test state_read event
    val = registry.read("agent_a", "global:key")
    assert val == "value"
    mock_bus.emit.assert_any_call(
        "state_read", {"agent": "agent_a", "path": "global:key", "value": "value"}
    )


def test_abstract_sandbox_propagate_bus(tmp_path):
    """Verify that AbstractSandbox propagates the event_bus to the registry."""
    from unittest.mock import MagicMock

    from eval_runner.tool_sandbox import ToolSandbox

    mock_bus = MagicMock()
    scenario = {"id": "bus-test", "agent_topology": {"agent_a": {"writes": ["*"]}}}
    sandbox = ToolSandbox(
        scenario, event_bus=mock_bus, workspace_root=tmp_path, jail_root=tmp_path / "jail"
    )

    # Check propagation
    assert sandbox.shared_state.event_bus == mock_bus

    # Verify write through sandbox still emits
    sandbox.shared_state.write("agent_a", "test:path", 42)
    mock_bus.emit.assert_any_call(
        "state_write", {"agent": "agent_a", "path": "test:path", "value": 42}
    )


# --- Coverage booster for tool_sandbox.py ---


@pytest.mark.asyncio
async def test_sandbox_cleanup_missing_dir_and_no_jail_cleanup(tmp_path):
    from eval_runner.tool_sandbox import ToolSandbox

    # 1. Non-existent path for resources cleanup (Line 40->36 branch)
    scenario = {
        "id": "cleanup-test",
        "cleanup_workspace": True,
        "metadata": {"cleanup_terminal_jail": False},
    }
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    sandbox.resources.register(tmp_path / "non_existent_file_xyz")

    # 2. Cleanup workspace when it does not exist (Line 288->295 branch)
    # Delete workspace dir first
    import shutil

    if tmp_path.exists():
        shutil.rmtree(tmp_path)

    await sandbox.teardown()
    # Should complete without error and with cleanup_terminal_jail = False (Line 299->exit branch)


def test_sandbox_service_interceptor_branches():
    from eval_runner.tool_sandbox import ToolSandboxInterceptor, tool_sandbox_service

    class DummyInterceptor(ToolSandboxInterceptor):
        def __init__(self, can_isolate_val=True, raise_recursion=False):
            self.can_isolate_val = can_isolate_val
            self.raise_recursion = raise_recursion

        def can_isolate(self, tool_name: str) -> bool:
            return self.can_isolate_val

        async def isolate_call(self, call_data: dict, next_handler) -> dict:
            if self.raise_recursion:
                raise RecursionError("Simulated recursion")
            return await next_handler(call_data)

    # 1. Test register_interceptor when local_interceptors is not None (Line 358)
    tool_sandbox_service._local_interceptors.set([])
    interceptor = DummyInterceptor(can_isolate_val=False)
    tool_sandbox_service.register_interceptor(interceptor)
    assert interceptor in tool_sandbox_service._local_interceptors.get()
    tool_sandbox_service.reset()

    # 2. Test override_interceptor finally block where interceptor not in global (Line 383->exit)
    async def run_override():
        async with tool_sandbox_service.override_interceptor(interceptor):
            # Manually remove from global to trigger the branch in finally
            tool_sandbox_service._global_interceptors.remove(interceptor)

    import asyncio

    asyncio.run(run_override())

    # 3. Test max depth cycle detection (Line 396)
    async def run_pipeline():
        # Inject interceptor that calls isolate on itself/loop
        class CyclingInterceptor(ToolSandboxInterceptor):
            def can_isolate(self, t):
                return True

            async def isolate_call(self, data, next_h):
                # Force infinite recursion call to next_h
                return await next_h(data)

        # Call with index/depth starting high or manually trigger recursion
        # We can test by setting up a recursive list of interceptors
        # But even simpler: mock the interceptors list to be large, or call make_next directly.
        # Let's register many interceptors to hit depth > 50
        for _ in range(55):
            tool_sandbox_service.register_interceptor(CyclingInterceptor())

        with pytest.raises(RecursionError, match="Max tool sandbox pipeline depth"):
            await tool_sandbox_service.isolate({"tool_name": "test"}, lambda d: d)

    asyncio.run(run_pipeline())
    tool_sandbox_service.reset()

    # 4. Test interceptor raising RecursionError/KeyboardInterrupt (Line 409)
    async def run_raise_recursion():
        interceptor_err = DummyInterceptor(can_isolate_val=True, raise_recursion=True)
        async with tool_sandbox_service.override_interceptor(interceptor_err):
            with pytest.raises(RecursionError, match="Simulated recursion"):
                await tool_sandbox_service.isolate({"tool_name": "test"}, lambda d: d)

    asyncio.run(run_raise_recursion())
    tool_sandbox_service.reset()


@pytest.mark.asyncio
async def test_sandbox_execute_missing_branches(tmp_path):
    from eval_runner.simulators import BaseSimulator
    from eval_runner.tool_sandbox import ToolSandbox

    class DummyDnaSimulator(BaseSimulator):
        async def handle_dummy_dna(self, params):
            return {"status": "success", "dna": {"key1": "val1"}}

    # 1. Test tool not matching simulator prefix (Line 475->474)
    # 2. Test merging dna from raw result (Line 506)
    sim = DummyDnaSimulator()
    scenario = {"id": "dummy-dna", "enabled_shims": ["dummy"]}
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    sandbox._simulator_cache = {"dummy": sim}

    # Execute action starting with dummy_ -> hits execute and collects DNA
    res = await sandbox.execute("dummy_dna", {})
    assert res.get_secure_metadata()["key1"] == "val1"

    # Execute action not starting with dummy_ -> skips loop (Line 475->474)
    res_skip = await sandbox.execute("other_tool", {})
    assert res_skip["status"] == "success"  # fallback success output


@pytest.mark.asyncio
async def test_sandbox_state_changes_and_shared_state_edge_cases(tmp_path):
    from eval_runner.tool_sandbox import ToolSandbox

    scenario = {
        "id": "state-edge",
        "tools": {
            "test_tool": {
                # State change with missing/None path (Line 531->528 branch)
                "state_changes": [{"path": None, "value": 1}]
            }
        },
        "agent_topology": {"agent_a": {"writes": ["*"], "reads": ["*"]}},
    }
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")

    # 1. State change without path
    await sandbox.execute("test_tool", {})

    # 2. Shared write without path (Line 539->547 branch)
    await sandbox.execute("test_tool", {"shared_write": {"value": 1}})

    # 3. Shared read without path (Line 549->558 branch)
    await sandbox.execute("test_tool", {"shared_read": {"value": 1}})


def test_sandbox_sanitize_path_vfs_prefix_check():
    from eval_runner.tool_sandbox import ToolSandbox

    # If path already starts with config.SANDBOX_VFS_PREFIX (Line 631->634 branch)
    res = ToolSandbox._sanitize_path("vfs:/etc/passwd")
    assert res == "vfs:/etc/passwd"


def test_sandbox_sanitize_value_list():
    from eval_runner.tool_sandbox import ToolSandbox

    # Test sanitizing a list of strings (Line 782-784)
    res = ToolSandbox._sanitize_value(["ls -la; rm -rf", "ok"])
    assert ";" not in res[0]
    assert res[1] == "ok"


def test_sandbox_interceptor_bypassed_make_next():
    import asyncio

    from eval_runner.tool_sandbox import tool_sandbox_service

    # Interceptor that cannot isolate the call (can_isolate returns False)
    class BypassedInterceptor:
        def can_isolate(self, tool_name):
            return False

        async def isolate_call(self, data, next_h):
            return {"status": "error", "message": "should not be called"}

    interceptor = BypassedInterceptor()
    tool_sandbox_service.register_interceptor(interceptor)

    try:
        # Call should bypass interceptor and proceed to handler
        async def dummy_handler(d):
            return {"status": "success"}

        res = asyncio.run(tool_sandbox_service.isolate({"tool_name": "test"}, dummy_handler))
        assert res["status"] == "success"
    finally:
        tool_sandbox_service.reset()
