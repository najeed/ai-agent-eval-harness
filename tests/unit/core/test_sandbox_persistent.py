"""
test_sandbox_persistent.py

Verifies that world simulators maintain state across multiple execute() calls
within the same ToolSandbox instance (fixing the previous stateless regression).
"""

import pytest
from eval_runner.tool_sandbox import ToolSandbox

def test_git_state_persistence_in_sandbox():
    """Verify git_add then git_commit in the same sandbox session."""
    scenario = {
        "aes_version": 1.2,
        "scenario_id": "persistence_test",
        "title": "Persistence Test",
        "industry": "test",
        "description": "test",
        "metadata": {"name": "persistence_test", "compliance_level": "Standard"},
        "workflow": {"nodes": [], "edges": []}
    }
    
    sandbox = ToolSandbox(scenario)
    
    # 1. Stage a file
    res1 = sandbox.execute("git_add", {"files": ["README.md"]})
    assert res1["status"] == "success"
    
    # 2. Verify it's staged in the cached simulator
    sims = sandbox.get_active_simulators()
    assert "README.md" in sims["git"].state["staged_files"]
    
    # 3. Commit the file
    res2 = sandbox.execute("git_commit", {"message": "initial commit"})
    assert res2["status"] == "success"
    
    # 4. Verify original staged_files is now empty but history has 2 commits
    # (The cached instance should have been used)
    assert len(sims["git"].state["staged_files"]) == 0
    assert len(sims["git"].state["history"]) == 2
    
    # 5. Teardown (verifies cleanup)
    sandbox.teardown()

def test_jira_state_persistence_in_sandbox():
    """Verify jira_create then jira_update in the same sandbox session."""
    scenario = {
        "aes_version": 1.2,
        "scenario_id": "persistence_test",
        "metadata": {"name": "persistence_test", "compliance_level": "Standard"},
        "workflow": {"nodes": [], "edges": []}
    }
    sandbox = ToolSandbox(scenario)
    
    res1 = sandbox.execute("jira_create", {"summary": "bug 1"})
    issue_id = res1["id"]
    
    res2 = sandbox.execute("jira_update", {"id": issue_id, "status": "Done"})
    assert res2["status"] == "success"
    
    sims = sandbox.get_active_simulators()
    updated = next((i for i in sims["jira"].state["issues"] if i["id"] == issue_id), None)
    assert updated["status"] == "Done"
    
    sandbox.teardown()
