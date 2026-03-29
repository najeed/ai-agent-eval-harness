"""
Test suite for hardened simulation objects.
"""

import pytest
from eval_runner import simulators


def test_git_simulator():
    sim = simulators.GitSimulator()
    res = sim.execute("git_clone", {"url": "https://github.com/test/repo"})
    assert res["status"] == "success"
    res = sim.execute("git_add", {"files": ["file1.txt"]})
    assert res["status"] == "success"
    assert "file1.txt" in sim.state["staged_files"]
    res = sim.execute("git_commit", {"message": "feat: test"})
    assert res["status"] == "success"
    assert len(sim.state["history"]) == 2


def test_jira_simulator():
    sim = simulators.JiraSimulator()
    res = sim.execute("jira_create", {"summary": "bug report"})
    assert res["status"] == "success"
    issue_id = res["id"]
    res = sim.execute("jira_update", {"id": issue_id, "status": "Done"})
    assert res["status"] == "success"
    # Search for the updated issue
    updated = next((i for i in sim.state["issues"] if i["id"] == issue_id), None)
    assert updated is not None
    assert updated["status"] == "Done"


def test_cloud_simulator():
    sim = simulators.CloudSimulator()
    res = sim.execute("cloud_launch", {"type": "t2.micro"})
    assert res["status"] == "success"
    inst_id = res["id"]
    # Check instance exists
    assert any(i["id"] == inst_id for i in sim.state["instances"])


def test_terminal_simulator():
    sim = simulators.TerminalSimulator()
    res = sim.execute("terminal_execute", {"cmd": "ls"})
    assert res["status"] == "success"
    assert "file1.txt" in res.get("output", "")
    res = sim.execute("terminal_execute", {"cmd": "cd /tmp", "path": "/tmp"})
    assert res["status"] == "success"
    assert sim.state["cwd"] == "/tmp"
    # Legacy shim test
    res = sim.execute("ls", {})
    assert res is not None
    assert "file1.txt" in res.get("output", "")


def test_security_simulator():
    sim = simulators.SecuritySimulator()
    res = sim.execute("security_auth", {"user": "admin"})
    assert res is not None
    assert res.get("status") == "success"
    res = sim.execute("bad", {})
    assert res is not None
    assert res.get("status") == "error"


def test_erp_simulator():
    sim = simulators.ERPSimulator()
    res = sim.execute("erp_create_order", {"id": "O-100", "qty": 1})
    assert res is not None
    assert res.get("status") == "success"


def test_iot_simulator():
    sim = simulators.IoTSimulator()
    res = sim.execute("iot_update", {"device": "thermostat", "state": "75F"})
    assert res["status"] == "success"
    assert sim.state["devices"]["thermostat"] == "75F"
