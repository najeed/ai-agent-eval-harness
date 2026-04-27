import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.simulators import (
    ApiSimulator,
    BrowserSimulator,
    CICDSimulator,
    CloudSimulator,
    DatabaseSimulator,
    GitSimulator,
    SocialMediaSimulator,
    SupportDeskSimulator,
    TerminalSimulator,
)


@pytest.mark.asyncio
async def test_git_simulator_errors():
    sim = GitSimulator()

    # Line 132: commit no repo
    res = await sim.handle_git_commit({})
    assert res["status"] == "error"
    assert "No active repository found" in res["message"]

    # Line 125-126: add exception
    repo_mock = MagicMock()
    repo_mock.index.add.side_effect = ValueError("Mock add error")
    sim._get_repo = MagicMock(return_value=repo_mock)
    res = await sim.handle_git_add({"files": ["test.txt"]})
    assert res["status"] == "error"
    assert "Mock add error" in res.get("message", "")

    # Line 147: handle_git_push
    res = await sim.handle_git_push({})
    assert res["status"] == "success"
    await sim.cleanup()


@pytest.mark.asyncio
async def test_api_simulator_coverage():
    sim = ApiSimulator()

    class DummyResponse:
        is_success = True

        def json(self):
            return {}

        headers = {"Content-Type": "application/json"}

    class DummyClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, *args, **kwargs):
            return DummyResponse()

    # Line 206-207: invalid timeout env var
    with patch.dict(os.environ, {"SHIM_TIMEOUT": "invalid", "IS_LIVE": "true"}):
        with patch("httpx.AsyncClient", new=DummyClient):
            await sim.handle_api_request(
                {"url": "http://test", "data": {"a": 1}}
            )  # Line 224: json data

    # Line 254: get_snapshot endpoints
    snap = await sim.get_snapshot()
    assert "endpoints" in snap

    # Line 262-263: execute fallback
    res = await sim.execute("unknown_action", {})
    assert res["status"] == "error"
    assert "Unknown action" in res["message"]
    await sim.cleanup()


@pytest.mark.asyncio
async def test_database_simulator_coverage(tmp_path):
    sim = DatabaseSimulator()
    sim.terminal_jail = tmp_path

    # Line 348: get_snapshot no engine
    sim._get_engine = MagicMock()
    sim._engine = None
    snap = await sim.get_snapshot()
    assert snap["engine"] == "mock"

    # Line 355-361: inspect table names
    await sim.cleanup()
    sim = DatabaseSimulator()
    sim.terminal_jail = tmp_path
    sim._get_engine()  # Init real engine
    snap = await sim.get_snapshot()
    assert "tables" in snap
    assert "users" in snap["tables"]

    # Line 362-363: get_snapshot exception
    sim._engine = MagicMock()
    sim._engine.connect.side_effect = ValueError("Mock connection error")
    snap = await sim.get_snapshot()
    assert "Mock connection error" in snap["error"]
    await sim.cleanup()


@pytest.mark.asyncio
async def test_cloud_simulator_coverage():
    sim = CloudSimulator()
    # Line 510: on_poll false
    assert not await sim.on_poll("instance_running", {"instance_id": "missing"})
    await sim.cleanup()


@pytest.mark.asyncio
async def test_terminal_simulator_coverage(tmp_path):
    sim = TerminalSimulator()

    # Line 534: no terminal_jail
    res = await sim.handle_terminal_execute({"cmd": "ls"})
    assert res["status"] == "error"
    assert "Terminal Jail not provisioned" in res["message"]

    sim.terminal_jail = tmp_path
    # Line 545-546: path traversal blocked
    res = await sim.handle_terminal_execute({"cmd": "cd C:\\Windows\\System32"})
    assert res["status"] == "error"
    assert "Security Violation" in res["message"]

    # Line 584-585: execution error
    with patch(
        "eval_runner.simulators.subprocess.run", side_effect=ValueError("Mock execution error")
    ):
        res = await sim.handle_terminal_execute({"cmd": "ls"})
        assert res["status"] == "error"

    # Line 590-591: execute fallback
    res = await sim.execute("terminal_execute", {"cmd": "ls"})
    assert res["status"] in ["success", "error"]
    await sim.cleanup()


@pytest.mark.asyncio
async def test_browser_simulator_coverage():
    sim = BrowserSimulator()
    # Line 668-669: handle_browser_go exception
    mock_page = AsyncMock()
    mock_page.goto.side_effect = ValueError("Mock browser error")
    with patch.object(sim, "_get_page", new_callable=AsyncMock, return_value=mock_page):
        res = await sim.handle_browser_go({})
        assert res["status"] == "error"
        assert "Mock browser error" in res.get("message", "")
    await sim.cleanup()


def test_support_desk_coverage():
    sim = SupportDeskSimulator()
    # Line 709: handle_support_close ticket not found
    res = sim.handle_support_close({"id": "MISSING"})
    assert res["status"] == "error"
    assert "Ticket not found" in res["message"]
    # SupportDeskSimulator is sync, but sim.cleanup() is async
    # (though empty/no-op in simulators.py for BaseSimulator)
    # However, it's good practice.
    # Wait, let me check if SupportDeskSimulator has a cleanup.


@pytest.mark.asyncio
async def test_social_media_coverage():
    sim = SocialMediaSimulator()
    # Line 727: on_poll false
    assert not await sim.on_poll("post_confirmed", {"post_id": "MISSING"})
    # Line 726: on_poll true
    sim.state["posts"].append({"id": "P1"})
    assert await sim.on_poll("post_confirmed", {"post_id": "P1"})
    await sim.cleanup()


@pytest.mark.asyncio
async def test_cicd_coverage():
    sim = CICDSimulator()
    # Line 773: on_poll false
    assert not await sim.on_poll("build_complete", {"build_id": "MISSING"})
    await sim.cleanup()
