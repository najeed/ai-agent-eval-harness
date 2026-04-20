import sys
from unittest.mock import MagicMock, patch

import pytest

from eval_runner import simulators


@pytest.mark.asyncio
async def test_git_simulator():
    sim = simulators.GitSimulator()
    with patch("git.Repo.clone_from") as mock_clone:
        res = await sim.execute("git_clone", {"url": "https://github.com/test/repo"})
        assert res["status"] == "success"
        mock_clone.assert_called_once()

    with patch("git.Repo") as mock_repo_class:
        mock_repo = mock_repo_class.return_value
        sim._repo = mock_repo

        res = await sim.execute("git_add", {"files": ["file1.txt"]})
        assert res["status"] == "success"

        mock_commit = MagicMock()
        mock_commit.hexsha = "abc123"
        mock_repo.index.commit.return_value = mock_commit

        res = await sim.execute("git_commit", {"message": "feat: test"})
        assert res["status"] == "success"


@pytest.mark.asyncio
async def test_jira_simulator():
    sim = simulators.JiraSimulator()
    res = await sim.execute("jira_create", {"summary": "bug report"})
    assert res["status"] == "success"
    issue_id = res["id"]
    res = await sim.execute("jira_update", {"id": issue_id, "status": "Done"})
    assert res["status"] == "success"
    # Search for the updated issue
    updated = next((i for i in sim.state["issues"] if i["id"] == issue_id), None)
    assert updated is not None
    assert updated["status"] == "Done"


@pytest.mark.asyncio
async def test_cloud_simulator():
    sim = simulators.CloudSimulator()
    res = await sim.execute("cloud_launch", {"type": "t2.micro"})
    assert res["status"] == "success"
    inst_id = res["instance_id"]
    # Check instance exists
    assert any(i["id"] == inst_id for i in sim.state["instances"])


@pytest.mark.asyncio
async def test_terminal_simulator(tmp_path):
    sim = simulators.TerminalSimulator()
    sim.terminal_jail = tmp_path

    # Use a command that works without shell redirection
    # On Windows, 'echo' is a builtin but also exists as an executable in some envs
    # Better: use python to write a file for cross-platform reliability
    cmd = f"{sys.executable} -c \"with open('file1.txt', 'w') as f: f.write('test')\""
    res = await sim.execute("terminal_execute", {"cmd": cmd})
    assert res["status"] == "success"

    res = await sim.execute("terminal_execute", {"cmd": f"{sys.executable} --version"})
    assert res["status"] == "success"


@pytest.mark.asyncio
async def test_security_simulator():
    sim = simulators.SecuritySimulator()
    res = await sim.execute("security_auth", {"user": "admin"})
    assert res is not None
    assert res.get("status") == "success"
    res = await sim.execute("bad", {})
    assert res is not None
    assert res.get("status") == "error"


@pytest.mark.asyncio
async def test_erp_simulator():
    sim = simulators.ERPSimulator()
    res = await sim.execute("erp_create_order", {"id": "O-100", "qty": 1})
    assert res is not None
    assert res.get("status") == "success"


@pytest.mark.asyncio
async def test_base_simulator_immutability():
    sim = simulators.GitSimulator()  # GitSimulator inherits from BaseSimulator
    sim.state = {"a": {"b": 1}}

    snapshot = await sim.get_snapshot()
    assert snapshot == sim.state
    assert snapshot is not sim.state

    # Mutate snapshot
    snapshot["a"]["b"] = 2
    assert sim.state["a"]["b"] == 1, "State was mutated through snapshot"
