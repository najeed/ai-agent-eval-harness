"""
test_sandbox_persistent.py

Verifies that world simulators maintain state across multiple execute() calls
within the same ToolSandbox instance (fixing the previous stateless regression).
"""

import pytest
from eval_runner.tool_sandbox import ToolSandbox
from unittest.mock import MagicMock


@pytest.mark.asyncio
async def test_git_state_persistence_in_sandbox():
    """Verify git_add then git_commit in the same sandbox session."""
    scenario = {
        "aes_version": 1.3,
        "scenario_id": "persistence_test",
        "title": "Persistence Test",
        "industry": "test",
        "description": "test",
        "metadata": {"name": "persistence_test", "compliance_level": "Standard"},
        "workflow": {"nodes": [], "edges": []},
    }

    sandbox = ToolSandbox(scenario)
    
    # [Hardening Fix] The industrial GitSimulator requires an active repo for git_add
    # We mock git.Repo logic inside the simulator to avoid real FS operations in unit tests
    from unittest.mock import MagicMock
    mock_repo = MagicMock()
    sandbox.get_active_simulators()["git"]._repo = mock_repo

    # 1. Stage a file
    res1 = await sandbox.execute("git_add", {"files": ["README.md"]})
    assert res1["status"] == "success"

    # 2. Verify it's staged in the cached simulator
    sims = sandbox.get_active_simulators()
    # Note: In mock mode, we check calls on mock_repo.index.add
    mock_repo.index.add.assert_called_with(["README.md"])

    # 3. Commit the file
    mock_commit = MagicMock()
    mock_commit.hexsha = "abc123"
    mock_repo.index.commit.return_value = mock_commit
    
    res2 = await sandbox.execute("git_commit", {"message": "initial commit"})
    assert res2["status"] == "success"

    # 4. Teardown (verifies cleanup)
    await sandbox.teardown()


@pytest.mark.asyncio
async def test_jira_state_persistence_in_sandbox():
    """Verify jira_create then jira_update in the same sandbox session."""
    scenario = {
        "aes_version": 1.3,
        "scenario_id": "persistence_test",
        "metadata": {"name": "persistence_test", "compliance_level": "Standard"},
        "workflow": {"nodes": [], "edges": []},
    }
    sandbox = ToolSandbox(scenario)

    res1 = await sandbox.execute("jira_create", {"summary": "bug 1"})
    issue_id = res1["id"]

    res2 = await sandbox.execute("jira_update", {"id": issue_id, "status": "Done"})
    assert res2["status"] == "success"

    sims = sandbox.get_active_simulators()
    updated = next((i for i in sims["jira"].state["issues"] if i["id"] == issue_id), None)
    assert updated["status"] == "Done"

    await sandbox.teardown()
