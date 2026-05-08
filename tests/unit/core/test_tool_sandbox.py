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


def test_shared_state_registry_permissions():
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
