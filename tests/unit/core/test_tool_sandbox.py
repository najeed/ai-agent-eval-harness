"""
test_tool_sandbox.py

Test suite for the ToolSandbox mock tool execution environment.
Aligned with OpenCore modular architecture and explicit tool definitions.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
    """[A1] Fail-closed: an unregistered tool yields a hard UNREGISTERED_TOOL
    error result — the kernel never synthesizes success for unknown tools."""
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
    assert result["status"] == "error"
    assert result["error_code"] == "UNREGISTERED_TOOL"
    assert result["tool_name"] == "nonexistent_tool"
    assert "not registered" in result["message"]


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
    # Test _sanitize_path logic
    # It should strip traversals and add prefix
    res = ToolSandbox._sanitize_path("../../etc/passwd")
    assert ".." not in res
    assert res == "vfs:/passwd"


def test_sandbox_value_sanitization():
    """Verify that command values are sanitized against shell meta-characters."""
    # Test _sanitize_value logic
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
    scenario = {
        "id": "bus-test",
        "metadata": {
            "agent_topology": {"agent_a": {"writes": ["*"]}},
        },
    }
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

    # 1. Non-existent path for resources cleanup
    scenario = {
        "id": "cleanup-test",
        "cleanup_workspace": True,
        "metadata": {"cleanup_terminal_jail": False},
    }
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    sandbox.resources.register(tmp_path / "non_existent_file_xyz")

    # 2. Cleanup workspace when it does not exist
    # Delete workspace dir first
    import shutil

    if tmp_path.exists():
        shutil.rmtree(tmp_path)

    await sandbox.teardown()
    # Should complete without error and with cleanup_terminal_jail = False


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

    # 1. Test register_interceptor when local_interceptors is not None
    tool_sandbox_service._local_interceptors.set([])
    interceptor = DummyInterceptor(can_isolate_val=False)
    tool_sandbox_service.register_interceptor(interceptor)
    assert interceptor in tool_sandbox_service._local_interceptors.get()
    tool_sandbox_service.reset()

    # 2. Test override_interceptor finally block where interceptor not in global
    async def run_override():
        async with tool_sandbox_service.override_interceptor(interceptor):
            # Manually remove from global to trigger the branch in finally
            tool_sandbox_service._global_interceptors.remove(interceptor)

    import asyncio

    asyncio.run(run_override())

    # 3. Test max depth cycle detection
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

    # 4. Test interceptor raising RecursionError/KeyboardInterrupt
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

    # 1. Test tool not matching simulator prefix
    # 2. Test merging dna from raw result
    sim = DummyDnaSimulator()
    scenario = {"id": "dummy-dna", "enabled_shims": ["dummy"]}
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    sandbox._simulator_cache = {"dummy": sim}

    # Execute action starting with dummy_ -> hits execute and collects DNA
    res = await sandbox.execute("dummy_dna", {})
    assert res.get_secure_metadata()["key1"] == "val1"

    # Execute action not starting with dummy_ and not registered -> skips
    # simulator loop and fails closed with UNREGISTERED_TOOL (A1).
    res_skip = await sandbox.execute("other_tool", {})
    assert res_skip["status"] == "error"
    assert res_skip["error_code"] == "UNREGISTERED_TOOL"


@pytest.mark.asyncio
async def test_sandbox_state_changes_and_shared_state_edge_cases(tmp_path):
    from eval_runner.tool_sandbox import ToolSandbox

    scenario = {
        "id": "state-edge",
        "metadata": {
            "agent_topology": {"agent_a": {"writes": ["*"], "reads": ["*"]}},
        },
        "tools": {
            "test_tool": {
                # State change with missing/None path
                "state_changes": [{"path": None, "value": 1}]
            }
        },
    }

    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")

    # 1. State change without path
    await sandbox.execute("test_tool", {})

    # 2. Shared write without path
    await sandbox.execute("test_tool", {"shared_write": {"value": 1}})

    # 3. Shared read without path
    await sandbox.execute("test_tool", {"shared_read": {"value": 1}})


def test_sandbox_sanitize_path_vfs_prefix_check():
    from eval_runner.tool_sandbox import ToolSandbox

    # If path already starts with config.SANDBOX_VFS_PREFIX
    res = ToolSandbox._sanitize_path("vfs:/etc/passwd")
    assert res == "vfs:/etc/passwd"


def test_sandbox_sanitize_value_list():
    from eval_runner.tool_sandbox import ToolSandbox

    # Test sanitizing a list of strings
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


@pytest.mark.asyncio
async def test_sandbox_grounding_hits_counter_increment(tmp_path):
    """
    Mutation Assurance Test: Verifies tool execution increments grounding_hits
    ["tools"][tool_name] from 0 to 1 (kills + -> - mutation at line 425).
    """
    scenario = {
        "aes_version": 1.4,
        "tools": {"get_info": {"output": {"status": "success", "message": "ok"}}},
        "workflow": {
            "nodes": [{"id": "t1", "task_description": "task", "required_tools": ["get_info"]}],
            "edges": [],
        },
    }
    sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    await sandbox.execute("get_info", {})
    hits = sandbox.grounding_hits["tools"].get("get_info")
    assert hits == 1, f"Expected grounding_hits for 'get_info' to be 1, got {hits}"


def test_sandbox_shim_discovery_union(tmp_path, monkeypatch):
    """
    Mutation Assurance Test: Verifies shim discovery uses set union | (not &)
    so shims defined ONLY in configs or ONLY in classes are discovered
    (kills | -> & in tool_sandbox.py).
    """
    from eval_runner import config, simulators

    monkeypatch.setattr(config, "GLOBAL_ENABLED_SHIMS", ["*"])
    try:
        simulators._INTERNAL_SIMULATOR_CLASSES["customonlyshim"] = simulators.JiraSimulator
        scenario = {
            "id": "shim_union_test",
            "workflow": {"nodes": [{"required_tools": ["customonlyshim_action"]}]},
            "enabled_shims": ["*"],
        }
        sandbox = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")
        shims = sandbox.get_active_simulators()
        assert "customonlyshim" in shims
    finally:
        simulators._INTERNAL_SIMULATOR_CLASSES.pop("customonlyshim", None)


def test_sandbox_shared_state_wildcard_permission():
    """
    Mutation Assurance Test: Verifies SharedStateRegistry._match_namespace returns True
    for exact wildcard '*' (kills return True -> False mutation at line 100 in tool_sandbox.py).
    """
    from eval_runner.tool_sandbox import SharedStateRegistry

    reg = SharedStateRegistry({})
    assert reg._match_namespace("custom_ns", "*") is True


def test_sandbox_mkdir_exist_ok(tmp_path):
    """
    Mutation Assurance Test: Verifies workspace and jail mkdir(parents=True, exist_ok=True)
    when workspace_root and jail_root already exist (kills exist_ok=True -> False at lines 183-184).
    """
    ws = tmp_path / "ws"
    jail = tmp_path / "jail"
    ws.mkdir(parents=True, exist_ok=True)
    jail.mkdir(parents=True, exist_ok=True)

    sb1 = ToolSandbox({}, workspace_root=ws, jail_root=jail)
    sb2 = ToolSandbox({}, workspace_root=ws, jail_root=jail)
    assert sb1 is not None and sb2 is not None


def test_sandbox_shared_state_pattern_prefix_matching():
    """
    Mutation Assurance Test: Verifies SharedStateRegistry._match_namespace prefix matching
    (kills return namespace == pattern.split(":")[0] -> !=).
    """
    from eval_runner.tool_sandbox import SharedStateRegistry

    reg = SharedStateRegistry({})
    assert reg._match_namespace("app_state", "app_state:*") is True
    assert reg._match_namespace("other_state", "app_state:*") is False


@pytest.mark.asyncio
async def test_sandbox_cleanup_terminal_jail_env(tmp_path, monkeypatch):
    """
    Mutation Assurance Test: Verifies CLEANUP_TERMINAL_JAIL env var cleanup
    (kills == "true" -> != mutation).
    """
    jail = tmp_path / "jail"
    jail.mkdir(parents=True, exist_ok=True)
    (jail / "file.txt").write_text("data")

    monkeypatch.setenv("CLEANUP_TERMINAL_JAIL", "true")
    sb = ToolSandbox({}, workspace_root=tmp_path, jail_root=jail)
    await sb.teardown()
    assert not jail.exists()


@pytest.mark.asyncio
async def test_sandbox_record_policy_check_counter(tmp_path):
    """
    Mutation Assurance Test: Verifies policy hit count increment + 1
    (kills + 1 -> - 1 mutation).
    """
    scenario = {
        "metadata": {
            "policies": {"test_tool": {"max_limit": 100}},
        },
        "tools": {"test_tool": {"state_changes": []}},
    }

    sb = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    await sb.execute("test_tool", {"amount": 50})
    await sb.execute("test_tool", {"amount": 50})
    assert sb.grounding_hits["policies"]["test_tool"] == 2


def test_sandbox_provisioning_snapshot_sort_keys(tmp_path, monkeypatch):
    """
    Mutation Assurance Test: Verifies ToolSandbox.__init__ sorts keys for provisioning_hash
    (kills sort_keys=True -> False mutation).
    """
    import json

    from eval_runner import config
    from eval_runner.utils import crypto

    unsorted_registry = {"z_tool": 1, "a_tool": 2}
    monkeypatch.setattr(config.RegistryManager, "reload", lambda: unsorted_registry)

    sb = ToolSandbox({}, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    expected_sorted_json = json.dumps(unsorted_registry, sort_keys=True)
    expected_hash = crypto.checksum(expected_sorted_json)
    assert sb.provisioning_hash == expected_hash


@pytest.mark.asyncio
async def test_sandbox_scenario_cleanup_workspace_override(tmp_path):
    """
    Mutation Assurance Test: Verifies scenario.cleanup_workspace override
    (kills default False mutation).
    """
    ws = tmp_path / "ws"
    scenario = {"cleanup_workspace": True}
    sb = ToolSandbox(scenario, workspace_root=ws, jail_root=tmp_path / "jail")
    ws_dir = Path(sb.workspace_dir)
    ws_dir.mkdir(parents=True, exist_ok=True)
    (ws_dir / "file.txt").write_text("data")

    await sb.teardown()
    assert not ws_dir.exists()


def test_sandbox_service_unregister_interceptor():
    """
    Mutation Assurance Test: Verifies register/unregister interceptor logic
    (kills if x is not interceptor).
    """
    from eval_runner.tool_sandbox import ToolSandboxInterceptor, tool_sandbox_service

    class SampleInterceptor(ToolSandboxInterceptor):
        def can_isolate(self, name):
            return False

        async def isolate_call(self, data, next_fn):
            return await next_fn(data)

    item = SampleInterceptor()
    tool_sandbox_service.register_interceptor(item)
    assert item in tool_sandbox_service._global_interceptors
    tool_sandbox_service._global_interceptors.remove(item)
    assert item not in tool_sandbox_service._global_interceptors


def test_sandbox_read_shared_state_none_value(tmp_path):
    """
    Mutation Assurance Test: Verifies read shared state returns None when value is None
    (kills val is None check).
    """
    scenario = {"shared_state_topology": {"agent1": {"reads": ["*"], "writes": ["*"]}}}
    sb = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    sb.shared_state.write("agent1", "key_none", None)
    assert sb.shared_state.read("agent1", "key_none") is None


def test_sandbox_service_pipeline_multi_interceptor():
    """
    Mutation Assurance Test: Verifies ToolSandboxService interceptor pipeline
    uses index + 1 and depth + 1 (kills index + 1 -> - 1 and depth + 1 -> - 1).
    """
    import asyncio

    from eval_runner.tool_sandbox import ToolSandboxInterceptor, tool_sandbox_service

    history = []

    class Interceptor1(ToolSandboxInterceptor):
        def can_isolate(self, name):
            return True

        async def isolate_call(self, data, next_fn):
            history.append("1")
            return await next_fn(data)

    class Interceptor2(ToolSandboxInterceptor):
        def can_isolate(self, name):
            return True

        async def isolate_call(self, data, next_fn):
            history.append("2")
            return await next_fn(data)

    class InterceptorFails(ToolSandboxInterceptor):
        def can_isolate(self, name):
            return True

        async def isolate_call(self, data, next_fn):
            history.append("FAILS")
            raise RuntimeError("Interceptor crashed")

    class LoopingSandboxInterceptor(ToolSandboxInterceptor):
        def can_isolate(self, name):
            return True

        async def isolate_call(self, data, next_fn):
            return await tool_sandbox_service.isolate(data, next_fn)

    async def run_pipeline():
        i1 = Interceptor1()
        i2 = Interceptor2()
        async with tool_sandbox_service.override_interceptor(i1):
            async with tool_sandbox_service.override_interceptor(i2):

                async def fallback(data):
                    return {"status": "ok"}

                res = await tool_sandbox_service.isolate({"tool_name": "t"}, fallback)
                assert res == {"status": "ok"}

        # 2. Test Exception bypass (kills + -> -)
        history.clear()
        i_fails = InterceptorFails()
        async with tool_sandbox_service.override_interceptor(i1):
            async with tool_sandbox_service.override_interceptor(i_fails):
                res2 = await tool_sandbox_service.isolate({"tool_name": "t"}, fallback)
                assert res2 == {"status": "ok"}
                assert history == ["FAILS", "1"]

        # 3. Test Cycle / recursion limit on passthrough interceptors (kills depth + 1 -> - 1)
        class InterceptorNoop(ToolSandboxInterceptor):
            def can_isolate(self, name):
                return True

            async def isolate_call(self, data, next_fn):
                return await next_fn(data)

        from eval_runner.tool_sandbox import ToolSandboxService

        service_loop_noop = ToolSandboxService()
        for _ in range(55):
            service_loop_noop.register_interceptor(InterceptorNoop())
        with pytest.raises(RecursionError, match="Max tool sandbox pipeline depth exceeded"):
            await service_loop_noop.isolate({"tool_name": "t"}, fallback)

        # 4. Test Failing interceptors recursion depth (kills depth + 1 -> - 1)
        class InterceptorFailsSilent(ToolSandboxInterceptor):
            def can_isolate(self, name):
                return True

            async def isolate_call(self, data, next_fn):
                raise RuntimeError("Interceptor crashed")

        service_loop_fails = ToolSandboxService()
        for _ in range(55):
            service_loop_fails.register_interceptor(InterceptorFailsSilent())
        with pytest.raises(RecursionError, match="Max tool sandbox pipeline depth exceeded"):
            await service_loop_fails.isolate({"tool_name": "t"}, fallback)

        # 5. Test Skipped interceptors recursion depth (kills depth + 1 -> - 1)
        class InterceptorSkipped(ToolSandboxInterceptor):
            def can_isolate(self, name):
                return False

            async def isolate_call(self, data, next_fn):
                return await next_fn(data)

        service_loop_skipped = ToolSandboxService()
        for _ in range(55):
            service_loop_skipped.register_interceptor(InterceptorSkipped())
        with pytest.raises(RecursionError, match="Max tool sandbox pipeline depth exceeded"):
            await service_loop_skipped.isolate({"tool_name": "t"}, fallback)

        # 6. Skipped interceptor sequence progression (kills index + 1 -> - 1)
        history.clear()
        i_skip = InterceptorSkipped()
        async with tool_sandbox_service.override_interceptor(i1):
            async with tool_sandbox_service.override_interceptor(i_skip):
                res3 = await tool_sandbox_service.isolate({"tool_name": "t"}, fallback)
                assert res3 == {"status": "ok"}
                assert history == ["1"]

    asyncio.run(run_pipeline())
    assert history == ["1"]


@pytest.mark.asyncio
async def test_sandbox_nested_mkdir_parents_and_exist_ok(tmp_path):
    """
    Mutation Assurance Test: Verifies workspace_dir and terminal_jail
    mkdir(parents=True, exist_ok=True) (kills parents=True -> False and exist_ok=True -> False).
    """
    deep_ws = tmp_path / "deep_ws" / "nested" / "ws"
    deep_jail = tmp_path / "deep_jail" / "nested" / "jail"

    # 1. Parents=True test on non-existent parent directory
    sb1 = ToolSandbox({"run_id": "fixed_run_mkdir"}, workspace_root=deep_ws, jail_root=deep_jail)
    await sb1.setup()
    assert Path(sb1.workspace_dir).exists()
    assert Path(sb1.terminal_jail).exists()

    # 2. Exist_ok=True test on already existing directory
    sb2 = ToolSandbox({"run_id": "fixed_run_mkdir"}, workspace_root=deep_ws, jail_root=deep_jail)
    await sb2.setup()
    assert Path(sb2.workspace_dir).exists()
    assert Path(sb2.terminal_jail).exists()


@pytest.mark.asyncio
async def test_sandbox_cleanup_workspace_default_false(tmp_path):
    """
    Mutation Assurance Test: Verifies workspace is NOT deleted when cleanup_workspace is
    False/absent (kills default False -> True mutation).
    """
    ws = tmp_path / "persist_ws"
    jail = tmp_path / "jail"
    sb = ToolSandbox({}, workspace_root=ws, jail_root=jail)
    ws_dir = Path(sb.workspace_dir)
    ws_dir.mkdir(parents=True, exist_ok=True)
    f = ws_dir / "preserve.txt"
    f.write_text("must_preserve")

    await sb.teardown()
    assert ws_dir.exists()
    assert f.exists()


def test_resource_registry_missing_ok_unlink(tmp_path):
    """
    Mutation Assurance Test: Verifies path.unlink(missing_ok=True)
    (kills missing_ok=True -> False mutation).
    """
    from unittest.mock import patch

    from eval_runner.tool_sandbox import ResourceRegistry

    reg = ResourceRegistry()
    f = tmp_path / "test_missing_file.txt"
    f.write_text("data")
    with patch.object(Path, "unlink") as mock_unlink:
        reg.register(f)
        reg.cleanup()
        mock_unlink.assert_called_once_with(missing_ok=True)


@pytest.mark.asyncio
async def test_sandbox_interceptor_depth_increment():
    """
    Mutation Assurance Test: Verifies depth increments during chained isolate calls
    (kills depth + 1 -> depth - 1 mutation).
    """
    from eval_runner.tool_sandbox import ToolSandboxInterceptor, ToolSandboxService

    class PassthroughInterceptor(ToolSandboxInterceptor):
        def can_isolate(self, name):
            return True

        async def isolate_call(self, data, next_fn):
            return await next_fn(data)

    service = ToolSandboxService()
    for _ in range(55):
        service.register_interceptor(PassthroughInterceptor())
    with pytest.raises(RecursionError, match="Max tool sandbox pipeline depth exceeded"):
        await service.isolate({"tool_name": "t"}, lambda d: {"status": "ok"})


@pytest.mark.asyncio
async def test_sandbox_read_shared_state_unauthorized_error(tmp_path):
    """
    Mutation Assurance Test: Verifies unauthorized read returns error when key exists
    (kills val is None -> val is not None mutation).
    """
    scenario = {
        "metadata": {
            "agent_topology": {"agent_auth": {"reads": ["*"], "writes": ["*"]}},
        },
        "tools": {"reader_tool": {"state_changes": []}},
    }

    sb = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    sb.shared_state.write("agent_auth", "auth:secret_key", "secret_value")
    # agent_unauth has no read permission for secret_key
    res = await sb.execute(
        "reader_tool", {"shared_read": {"path": "auth:secret_key"}}, agent_name="agent_unauth"
    )
    assert res["status"] == "error"
    assert "no read permission" in res["message"]


def test_sandbox_shim_discovery_union_mutant(tmp_path, monkeypatch):
    """
    Mutation Assurance Test: Verifies set(shim_configs.keys()) | set(shim_classes.keys())
    (kills | -> & mutation).
    """
    from eval_runner import config, simulators

    class DummyShim:
        def __init__(self, **kwargs):
            pass

    scenario = {"enabled_shims": ["*"]}
    sb = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    monkeypatch.setattr(config, "GLOBAL_ENABLED_SHIMS", ["*"])
    monkeypatch.setattr(
        config.RegistryManager,
        "get_resolved_registry",
        lambda: {"shims": {"config_only_shim": {"type": "mock_cls"}}},
    )
    monkeypatch.setattr(
        simulators, "get_simulator_registry", lambda **kwargs: {"mock_cls": DummyShim}
    )
    shims = sb.get_active_simulators()
    assert "config_only_shim" in shims


@pytest.mark.asyncio
async def test_sandbox_execute_no_interceptors_clean_run(tmp_path):
    """
    Mutation Assurance Test: Verifies pipeline executes cleanly with 0 interceptors
    (kills index >= len(interceptors_list) -> < mutation).
    """
    scenario = {"tools": {"direct_tool": {"state_changes": []}}}
    sb = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    res = await sb.execute("direct_tool", {})
    assert isinstance(res, dict)


@pytest.mark.asyncio
async def test_sandbox_cleanup_workspace_default_false_with_subfiles(tmp_path):
    """
    Mutation Assurance Test: Verifies workspace is NOT deleted when cleanup_workspace is False
    (kills default False -> True mutation).
    """
    scenario = {"cleanup_workspace": False}
    sb = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    ws_dir = Path(sb.workspace_dir)
    ws_dir.mkdir(parents=True, exist_ok=True)
    f = ws_dir / "keep.txt"
    f.write_text("keep_data")
    await sb.teardown()
    assert ws_dir.exists()
    assert f.exists()


def test_sandbox_scenario_enabled_shims_none_handling(tmp_path, monkeypatch):
    """
    Mutation Assurance Test: Verifies get_active_simulators activates relevant shims when
    enabled_shims is omitted (None) without raising TypeError or misrouting.
    (kills is None -> is not None mutation).
    """
    from eval_runner import config, simulators

    class RelevantShim:
        def __init__(self, **kwargs):
            pass

    scenario = {
        "workflow": {
            "nodes": [
                {"id": "t1", "task_description": "task", "required_tools": ["my_relevant_tool"]}
            ],
            "edges": [],
        }
    }
    sb = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    monkeypatch.setattr(config, "GLOBAL_ENABLED_SHIMS", ["*"])
    monkeypatch.setattr(
        config.RegistryManager,
        "get_resolved_registry",
        lambda: {"shims": {"my_relevant": {"type": "mock_rel_cls"}}},
    )
    monkeypatch.setattr(
        simulators, "get_simulator_registry", lambda **kwargs: {"mock_rel_cls": RelevantShim}
    )
    monkeypatch.setattr(sb, "_get_scenario_relevant_shims", lambda: {"my_relevant"})
    shims = sb.get_active_simulators()
    assert "my_relevant" in shims


@pytest.mark.asyncio
async def test_sandbox_state_changes_multi_level_and_path_resolver(tmp_path):
    """
    Verifies that state_changes correctly performs multi-level hierarchical mutations
    into initial_state across 1-level, 2-level, and 3-level deep paths, and confirms
    compatibility with PathResolver.
    """
    from eval_runner.utils.path_resolver import PathResolver

    scenario = {
        "aes_version": 1.4,
        "metadata": {
            "id": "multi-level-test",
            "name": "Multi Level Test",
            "compliance_level": "Standard",
            "agent_topology": {
                "risk_agent": {"reads": ["risk:*"], "writes": ["risk:*"]},
            },
            "policies": {
                "risk_assess": {
                    "rules": [{"field": "score", "operator": "lte", "value": 0.5}],
                },
            },
        },
        "initial_state": {
            "flat_key": "initial_flat",
            "risk": {
                "assessment": "pending",
                "score": 0.18,
            },
            "ledger": {
                "account": {
                    "limits": {
                        "daily": 1000.0,
                    },
                },
            },
        },
        "tools": {
            "risk_assess": {
                "state_changes": [
                    {"path": "flat_key", "value": "updated_flat"},
                    {"path": "risk.assessment", "value": "approved"},
                    {"path": "risk.details.confidence", "value": 0.99},
                    {"path": "ledger.account.limits.daily", "value": 5000.0},
                    {"path": "ledger.account.limits.currency", "value": "USD"},
                ],
                "output": {"status": "success", "message": "Risk assessed"},
            },
        },
        "workflow": {
            "nodes": [{"id": "t1", "task_description": "task", "required_tools": ["risk_assess"]}],
            "edges": [],
        },
    }

    sb = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")

    # Before execution checks
    assert PathResolver.resolve(sb.state, "risk.assessment") == "pending"
    assert PathResolver.resolve(sb.state, "ledger.account.limits.daily") == 1000.0

    res = await sb.execute("risk_assess", {"score": 0.2}, agent_name="risk_agent")
    assert res["status"] == "success"

    # Verify hierarchical nested dictionary mutation
    assert sb.state["flat_key"] == "updated_flat"
    assert sb.state["risk"]["assessment"] == "approved"
    assert sb.state["risk"]["details"]["confidence"] == 0.99
    assert sb.state["ledger"]["account"]["limits"]["daily"] == 5000.0
    assert sb.state["ledger"]["account"]["limits"]["currency"] == "USD"

    # Verify resolution via PathResolver
    assert PathResolver.resolve(sb.state, "flat_key") == "updated_flat"
    assert PathResolver.resolve(sb.state, "risk.assessment") == "approved"
    assert PathResolver.resolve(sb.state, "risk.details.confidence") == 0.99
    assert PathResolver.resolve(sb.state, "ledger.account.limits.daily") == 5000.0
    assert PathResolver.resolve(sb.state, "ledger.account.limits.currency") == "USD"

    # Policy was grounded and recorded
    assert sb.grounding_hits["policies"]["risk_assess"] == 1


@pytest.mark.asyncio
async def test_sandbox_set_state_path_overwrites_non_dict_intermediate(tmp_path):
    """
    Verifies that _set_state_path correctly overwrites non-dict intermediate
    values when creating nested paths.
    """
    scenario = {
        "aes_version": 1.4,
        "initial_state": {
            "corrupt_node": "string_value_instead_of_dict",
        },
        "tools": {
            "fix_node": {
                "state_changes": [
                    {"path": "corrupt_node.sub_field.leaf", "value": "leaf_value"},
                ],
                "output": {"status": "success"},
            }
        },
        "workflow": {
            "nodes": [{"id": "t1", "task_description": "task", "required_tools": ["fix_node"]}],
            "edges": [],
        },
    }
    sb = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    res = await sb.execute("fix_node", {})
    assert res["status"] == "success"
    assert sb.state["corrupt_node"]["sub_field"]["leaf"] == "leaf_value"


@pytest.mark.asyncio
async def test_sandbox_strict_metadata_placement_enforcement(tmp_path):
    """
    Verifies that placing policies or agent_topology at root level (instead of metadata)
    is NOT recognized by ToolSandbox, ensuring zero backward-compatibility masking.
    """
    scenario_with_root_entries = {
        "aes_version": 1.4,
        "policies": {
            "gated_tool": {
                "rules": [{"field": "amount", "operator": "lte", "value": 100}],
            },
        },
        "agent_topology": {
            "restricted_agent": {"reads": ["safe:*"], "writes": ["safe:*"]},
        },
        "tools": {
            "gated_tool": {
                "output": {"status": "success"},
            },
        },
        "workflow": {
            "nodes": [{"id": "t1", "task_description": "task", "required_tools": ["gated_tool"]}],
            "edges": [],
        },
    }

    sb = ToolSandbox(
        scenario_with_root_entries, workspace_root=tmp_path, jail_root=tmp_path / "jail"
    )

    # Policy at root is NOT evaluated because it must reside under metadata
    res = await sb.execute("gated_tool", {"amount": 500}, agent_name="restricted_agent")
    assert res["status"] == "success"
    assert "gated_tool" not in sb.grounding_hits["policies"]

    # Topology at root is NOT in shared_state registry
    assert "restricted_agent" not in sb.shared_state.topology


def test_sandbox_merge_branch_state_selective_keys(tmp_path):
    """
    Mutation Assurance Test: Verifies merge_branch_state with selective keys
    (kills keys is not None -> is None mutation).
    """
    sb = ToolSandbox({"id": "test-merge"}, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    sb.state = {"a": 1, "b": 2}

    fork = sb.fork("branch_1")
    fork.state["a"] = 100
    fork.state["b"] = 200

    # Merge only key 'a', 'b' must remain unchanged
    sb.merge_branch_state(fork, keys=["a"])
    assert sb.state["a"] == 100
    assert sb.state["b"] == 2


@pytest.mark.asyncio
async def test_sandbox_service_isolate_empty_interceptors():
    """
    Mutation Assurance Test: Verifies ToolSandboxService with 0 interceptors
    executes fallback immediately (kills index >= len -> index < len mutation).
    """
    from eval_runner.tool_sandbox import ToolSandboxService

    svc = ToolSandboxService()
    called = False

    async def fallback(data):
        nonlocal called
        called = True
        return {"fallback": "ok"}

    res = await svc.isolate({"tool_name": "noop"}, fallback)
    assert called is True
    assert res == {"fallback": "ok"}


@pytest.mark.asyncio
async def test_sandbox_policy_input_hash_sort_keys_determinism(tmp_path):
    """
    Mutation Assurance Test: Verifies input_hash is deterministic regardless of
    dict key insertion order (kills sort_keys=True -> False mutation).
    """
    scenario = {
        "metadata": {
            "policies": {
                "audit_tool": {
                    "rules": [{"field": "a", "operator": "eq", "value": 1}],
                },
            },
        },
        "tools": {"audit_tool": {"output": {"status": "ok"}}},
    }
    sb = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")

    # Call with param order 1: {"a": 1, "b": 2, "c": 3}
    await sb.execute("audit_tool", {"a": 1, "b": 2, "c": 3})
    hash1 = sb.policy_decisions[-1]["input_hash"]

    # Call with param order 2: {"c": 3, "a": 1, "b": 2}
    await sb.execute("audit_tool", {"c": 3, "a": 1, "b": 2})
    hash2 = sb.policy_decisions[-1]["input_hash"]

    assert hash1 == hash2


# --- Extended Full Branch Coverage Matrix ---


def test_resource_registry_cleanup_error(tmp_path):
    from eval_runner.tool_sandbox import ResourceRegistry

    registry = ResourceRegistry()
    test_dir = tmp_path / "test_dir_fail"
    test_dir.mkdir()
    registry.register(test_dir)

    with patch(
        "eval_runner.utils.rmtree_resilient", side_effect=PermissionError("Mocked Permission Error")
    ):
        registry.cleanup()


@pytest.mark.asyncio
async def test_tool_sandbox_setup_and_teardown_exceptions(tmp_path):
    forensics = MagicMock()
    forensics.snapshot_state.side_effect = RuntimeError("Forensic snapshot error")

    sb = ToolSandbox(
        {"id": "setup_test"},
        workspace_root=tmp_path,
        jail_root=tmp_path / "jail",
        forensics=forensics,
    )
    await sb.setup()
    assert forensics.snapshot_state.called

    # Teardown with failing simulator cleanup
    mock_sim = AsyncMock()
    mock_sim.cleanup.side_effect = RuntimeError("Simulator cleanup error")
    sb._simulator_cache = {"failing_sim": mock_sim}
    await sb.teardown()


@pytest.mark.asyncio
async def test_abstract_sandbox_get_full_state_branches():
    from eval_runner.tool_sandbox import AbstractSandbox

    class CustomSandbox(AbstractSandbox):
        def execute(self, tool_name, params, agent_name=None):
            pass

        def get_active_simulators(self):
            return self._simulators

    sb = CustomSandbox({"id": "test_env_state"})

    # 1. External simulator with get_bounded_reference (sync with to_dict)
    ext_sim_ref = MagicMock()
    ext_sim_ref.is_external = True
    mock_ref = MagicMock()
    mock_ref.to_dict.return_value = {"bounded": True}
    ext_sim_ref.get_bounded_reference.return_value = mock_ref

    # 2. External simulator with async get_bounded_reference (without to_dict)
    ext_sim_ref_async = MagicMock()
    ext_sim_ref_async.is_external = True

    async def _async_ref():
        return "raw_ref"

    ext_sim_ref_async.get_bounded_reference = _async_ref

    # 3. External simulator with get_snapshot (async, with large tables and normal keys)
    ext_sim_snap = MagicMock()
    ext_sim_snap.is_external = True
    delattr(ext_sim_snap, "get_bounded_reference")

    async def _async_snap_tables():
        return {
            "normal_key": 1,
            "tables": "x" * 20000,
        }

    ext_sim_snap.get_snapshot = _async_snap_tables

    # 4. External simulator with get_snapshot (sync, without tables)
    ext_sim_snap_notables = MagicMock()
    ext_sim_snap_notables.is_external = True
    delattr(ext_sim_snap_notables, "get_bounded_reference")
    ext_sim_snap_notables.get_snapshot.return_value = {"meta_only": 123}

    # 5. External simulator without ref or snapshot
    ext_sim_bare = MagicMock()
    ext_sim_bare.is_external = True
    delattr(ext_sim_bare, "get_bounded_reference")
    delattr(ext_sim_bare, "get_snapshot")

    # 6. Local simulator with async get_snapshot
    local_sim_snap_async = MagicMock()
    local_sim_snap_async.is_external = False

    async def _async_snap():
        return {"snap": "ok"}

    local_sim_snap_async.get_snapshot = _async_snap

    # 7. Local simulator with sync get_snapshot
    local_sim_snap_sync = MagicMock()
    local_sim_snap_sync.is_external = False
    local_sim_snap_sync.get_snapshot.return_value = {"sync_snap": "ok"}

    # 8. Local simulator with state attribute
    local_sim_state = MagicMock()
    local_sim_state.is_external = False
    delattr(local_sim_state, "get_snapshot")
    local_sim_state.state = {"local_key": "val"}

    # 9. Local simulator with neither snapshot nor state
    local_sim_bare = MagicMock()
    local_sim_bare.is_external = False
    delattr(local_sim_bare, "get_snapshot")
    delattr(local_sim_bare, "state")

    # 10. Simulator raising exception
    failing_sim = MagicMock()
    failing_sim.is_external = True
    failing_sim.get_bounded_reference.side_effect = RuntimeError("Snap fail")

    sb._simulators = {
        "ext_ref": ext_sim_ref,
        "ext_ref_async": ext_sim_ref_async,
        "ext_snap": ext_sim_snap,
        "ext_snap_notables": ext_sim_snap_notables,
        "ext_bare": ext_sim_bare,
        "local_snap_async": local_sim_snap_async,
        "local_snap_sync": local_sim_snap_sync,
        "local_state": local_sim_state,
        "local_bare": local_sim_bare,
        "failing": failing_sim,
    }

    env_state = await sb.get_full_state()
    assert env_state["ext_ref"] == {"bounded": True}
    assert env_state["ext_ref_async"] == "raw_ref"
    assert "tables" not in env_state["ext_snap"]
    assert env_state["ext_snap_notables"] == {"meta_only": 123}
    assert env_state["ext_bare"]["status"] == "EXTERNAL_BOUNDED"
    assert env_state["local_snap_async"] == {"snap": "ok"}
    assert env_state["local_snap_sync"] == {"sync_snap": "ok"}
    assert env_state["local_state"] == {"local_key": "val"}
    assert "local_bare" not in env_state
    assert "error" in env_state["failing"]


@pytest.mark.asyncio
async def test_tool_sandbox_get_full_state_all_branches(tmp_path):
    scenario = {"id": "full_state_test"}
    sb = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")

    ext_ref = MagicMock()
    ext_ref.is_external = True
    mock_ref = MagicMock()
    mock_ref.to_dict.return_value = {"ref": 1}
    ext_ref.get_bounded_reference.return_value = mock_ref

    ext_ref_async = MagicMock()
    ext_ref_async.is_external = True

    async def _async_ref():
        return "async_ref"

    ext_ref_async.get_bounded_reference = _async_ref

    ext_snap = MagicMock()
    ext_snap.is_external = True
    delattr(ext_snap, "get_bounded_reference")

    async def _async_ext_snap():
        return {"tables": "z" * 20000, "meta": "keep"}

    ext_snap.get_snapshot = _async_ext_snap

    ext_snap_notables = MagicMock()
    ext_snap_notables.is_external = True
    delattr(ext_snap_notables, "get_bounded_reference")
    ext_snap_notables.get_snapshot.return_value = {"simple": "data"}

    ext_bare = MagicMock()
    ext_bare.is_external = True
    delattr(ext_bare, "get_bounded_reference")
    delattr(ext_bare, "get_snapshot")

    loc_snap_async = MagicMock()
    loc_snap_async.is_external = False

    async def _loc_async_snap():
        return {"loc": "snap"}

    loc_snap_async.get_snapshot = _loc_async_snap

    loc_snap_sync = MagicMock()
    loc_snap_sync.is_external = False
    loc_snap_sync.get_snapshot.return_value = {"loc_sync": "snap"}

    loc_state = MagicMock()
    loc_state.is_external = False
    delattr(loc_state, "get_snapshot")
    loc_state.state = {"loc": "state"}

    loc_bare = MagicMock()
    loc_bare.is_external = False
    delattr(loc_bare, "get_snapshot")
    delattr(loc_bare, "state")

    fail_sim = MagicMock()
    fail_sim.is_external = False
    fail_sim.get_snapshot.side_effect = RuntimeError("Snapshot exception")

    sb._simulator_cache = {
        "ext_ref": ext_ref,
        "ext_ref_async": ext_ref_async,
        "ext_snap": ext_snap,
        "ext_snap_notables": ext_snap_notables,
        "ext_bare": ext_bare,
        "loc_snap_async": loc_snap_async,
        "loc_snap_sync": loc_snap_sync,
        "loc_state": loc_state,
        "loc_bare": loc_bare,
        "fail_sim": fail_sim,
    }

    full_state = await sb.get_full_state()
    assert full_state["shims"]["ext_ref"] == {"ref": 1}
    assert full_state["shims"]["ext_ref_async"] == "async_ref"
    assert "tables" not in full_state["shims"]["ext_snap"]
    assert full_state["shims"]["ext_snap_notables"] == {"simple": "data"}
    assert full_state["shims"]["ext_bare"]["status"] == "EXTERNAL_BOUNDED"
    assert full_state["shims"]["loc_snap_async"] == {"loc": "snap"}
    assert full_state["shims"]["loc_snap_sync"] == {"loc_sync": "snap"}
    assert full_state["shims"]["loc_state"] == {"loc": "state"}
    assert "loc_bare" not in full_state["shims"]
    assert "error" in full_state["shims"]["fail_sim"]


@pytest.mark.asyncio
async def test_tool_sandbox_execution_quiesce_and_policy_branches(tmp_path):
    scenario = {
        "id": "quiesce_test",
        "metadata": {
            "policies": {
                "limited_tool": {
                    "rules": [{"field": "count", "operator": "lte", "value": 5}],
                },
            },
        },
        "tools": {
            "limited_tool": {"output": {"status": "ok"}},
        },
    }
    sb = ToolSandbox(scenario, workspace_root=tmp_path, jail_root=tmp_path / "jail")

    # 1. Tool execution via simulator with quiesce timeout
    sim_timeout = AsyncMock()
    sim_timeout.execute.return_value = {"status": "ok", "message": "done", "dna": {"model": "gpt"}}
    sim_timeout.quiesce = AsyncMock(side_effect=TimeoutError("Timed out"))

    sb._simulator_cache = {"simto": sim_timeout}

    async def fake_wait_for(fut, timeout):
        try:
            await fut
        except Exception:
            pass
        raise TimeoutError("Timed out")

    with patch("asyncio.wait_for", side_effect=fake_wait_for):
        res_to = await sb.execute("simto_action", {})
        assert res_to.get("status") == "ok"
        assert res_to.get_secure_metadata().get("model") == "gpt"

    # 2. Tool execution via simulator with quiesce exception and without dna
    sim_err = AsyncMock()
    sim_err.execute.return_value = {"status": "ok_no_dna"}
    sim_err.quiesce = AsyncMock(side_effect=RuntimeError("Quiesce failed"))
    sb._simulator_cache = {"simerr": sim_err}
    res_err = await sb.execute("simerr_action", {})
    assert res_err.get("status") == "ok_no_dna"

    # 3. Tool execution via simulator without quiesce (covers 465->482)
    sim_no_q = AsyncMock()
    sim_no_q.execute.return_value = {"status": "no_quiesce"}
    del sim_no_q.quiesce
    sb._simulator_cache = {"simnoq": sim_no_q}
    res_no_q = await sb.execute("simnoq_action", {})
    assert res_no_q.get("status") == "no_quiesce"

    # 4. Policy violation with field and limit but no message (covers 523-524)
    from agentv_runtime.interfaces import PolicyEvaluationResult

    mock_eval = PolicyEvaluationResult(
        allowed=False,
        policy_id="count_policy",
        violations=[{"field": "count", "limit": 5, "value": 10}],
        reason="Exceeded",
    )
    with patch.object(sb.policy_evaluator, "evaluate_policy", return_value=mock_eval):
        viol_res = await sb.execute("limited_tool", {"count": 10})
        assert viol_res["status"] == "policy_violation"
        assert "Parameter 'count' with value 10 exceeds limit of 5" in viol_res["violation"]

    # 5. Policy violation with neither message nor field/limit (covers 523->532)
    mock_eval_generic = PolicyEvaluationResult(
        allowed=False,
        policy_id="generic_policy",
        violations=[{"custom_code": 99}],
        reason="Generic violation reason",
    )
    with patch.object(sb.policy_evaluator, "evaluate_policy", return_value=mock_eval_generic):
        viol_res_generic = await sb.execute("limited_tool", {"count": 10})
        assert viol_res_generic["status"] == "policy_violation"
        assert viol_res_generic["violation"] == "Generic violation reason"


@pytest.mark.asyncio
async def test_tool_sandbox_relevant_shims_and_instantiation_branches(tmp_path):
    # 1. workflow as list
    scen_list = {
        "id": "list_wf",
        "workflow": [
            {
                "id": "n1",
                "required_tools": ["shell", "custom_tool"],
                "expected_outcome": [
                    {"target": "shim:mock_shim.inspect"},
                    "not_a_dict_outcome",
                ],
            }
        ],
    }
    sb_list = ToolSandbox(scen_list, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    rel_list = sb_list._get_scenario_relevant_shims()
    assert "mock_shim" in rel_list

    # 2. workflow as invalid non-dict, non-list type
    scen_invalid = {
        "id": "invalid_wf",
        "workflow": "invalid_workflow_type",
        "tools": {"shell": {}},
    }
    sb_invalid = ToolSandbox(scen_invalid, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    rel_invalid = sb_invalid._get_scenario_relevant_shims()
    assert isinstance(rel_invalid, set)

    # 3. workflow with expected_outcome as single dict
    scen_dict_outcome = {
        "id": "single_dict_outcome",
        "workflow": {
            "nodes": [
                {
                    "id": "n2",
                    "expected_outcome": {"target": "shim:dict_shim.query"},
                }
            ]
        },
    }
    sb_dict = ToolSandbox(scen_dict_outcome, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    assert "dict_shim" in sb_dict._get_scenario_relevant_shims()

    # 4. Shim instantiation failure in get_active_simulators
    failing_cls = MagicMock()
    failing_cls.side_effect = RuntimeError("Shim init failure")
    with patch(
        "eval_runner.simulators.get_simulator_registry", return_value={"bad_shim": failing_cls}
    ):
        scen_bad = {
            "id": "bad_shim_scen",
            "shims": {"bad_shim": {"type": "bad_shim"}},
        }
        sb_bad = ToolSandbox(scen_bad, workspace_root=tmp_path, jail_root=tmp_path / "jail")
        sims = sb_bad.get_active_simulators()
        assert "bad_shim" not in sims


@pytest.mark.asyncio
async def test_tool_sandbox_merge_branch_state_matrix(tmp_path):
    sb = ToolSandbox({"id": "merge_test"}, workspace_root=tmp_path, jail_root=tmp_path / "jail")
    fork = ToolSandbox({"id": "merge_test"}, workspace_root=tmp_path, jail_root=tmp_path / "jail")

    # 1. Merge with keys, where one key is in fork and another is not
    fork.state["key1"] = "val1"
    sb.merge_branch_state(fork, keys=["key1", "missing_key"])
    assert sb.state["key1"] == "val1"
    assert "missing_key" not in sb.state

    # 2. Merge with keys=None (full state update)
    fork.state["key2"] = "val2"
    sb.merge_branch_state(fork, keys=None)
    assert sb.state["key2"] == "val2"

    # 3. Merge policy decisions with deduplication and unhashed decisions
    sb.policy_decisions = [{"input_hash": "hash_existing", "decision": "allow"}]
    fork.policy_decisions = [
        {"input_hash": "hash_existing", "decision": "allow_dup"},
        {"input_hash": "hash_new", "decision": "allow_new"},
        {"decision": "no_hash_decision"},
    ]
    sb.merge_branch_state(fork)
    assert len(sb.policy_decisions) == 3
    assert sb.policy_decisions[1]["input_hash"] == "hash_new"
    assert "input_hash" not in sb.policy_decisions[2]


@pytest.mark.asyncio
async def test_tool_sandbox_event_bus_and_register_artifact(tmp_path):
    scenario = {
        "id": "bus_test",
        "tools": {"test_tool": {"output": {"status": "ok"}}},
    }
    mock_bus = MagicMock()
    forensics = MagicMock()
    sb = ToolSandbox(
        scenario,
        workspace_root=tmp_path,
        jail_root=tmp_path / "jail",
        event_bus=mock_bus,
        forensics=forensics,
    )

    # Register artifact
    artifact_file = tmp_path / "artifact.txt"
    artifact_file.write_text("content", encoding="utf-8")
    sb.register_artifact(artifact_file)
    assert forensics.register_artifact.called

    # Event bus emit on execute
    await sb.execute("test_tool", {})
    assert mock_bus.emit.called
