from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.simulators import (
    ApiSimulator,
    BaseSimulator,
    BrowserSimulator,
    CloudSimulator,
    DatabaseSimulator,
    GitSimulator,
    IoTSimulator,
    SocialMediaSimulator,
    TerminalSimulator,
)


@pytest.mark.asyncio
async def test_base_simulator_unknown_action():
    """Verify fallback for unknown simulator actions."""
    sim = BaseSimulator()
    res = await sim.execute("void_vortex", {})
    assert res["status"] == "error"
    assert "Unknown action" in res["message"]


@pytest.mark.asyncio
async def test_api_simulator_live_error():
    """Verify API simulator error handling in live mode."""
    sim = ApiSimulator()
    with patch.dict("os.environ", {"IS_LIVE": "true"}):
        with patch("httpx.AsyncClient.request", side_effect=Exception("Network Down")):
            res = await sim.handle_api_request({"url": "http://api.com"})
            assert res["status"] == "error"
            assert "Network Down" in res["message"]


@pytest.mark.asyncio
async def test_database_simulator_query_error():
    """Verify database simulator error handling."""
    sim = DatabaseSimulator()
    # Mock engine to fail
    sim._engine = MagicMock()
    sim._engine.connect.side_effect = Exception("SQL Syntax Error")

    res = await sim.handle_database_query({"query": "SELECT *"})
    assert res["status"] == "error"
    assert "Database Error" in res["message"]


@pytest.mark.asyncio
async def test_git_simulator_lazy_init_none(tmp_path):
    """Verify Git simulator handles missing repo gracefully."""
    sim = GitSimulator()
    sim.terminal_jail = str(tmp_path)
    # Repo doesn't exist yet
    assert sim._get_repo() is None


@pytest.mark.asyncio
async def test_cloud_simulator_polling():
    """Verify cloud simulator lifecycle polling."""
    sim = CloudSimulator()
    # Launch
    await sim.handle_cloud_launch({"type": "t2.large"})
    iid = sim.state["instances"][-1]["id"]

    # Poll
    res = await sim.on_poll("instance_running", {"instance_id": iid})
    assert res is True
    assert sim.state["instances"][-1]["status"] == "running"


@pytest.mark.asyncio
async def test_terminal_simulator_security_violation(tmp_path):
    """Verify terminal jail security containment."""
    sim = TerminalSimulator()
    sim.terminal_jail = str(tmp_path)

    # Attempt to CD outside jail
    res = await sim.handle_terminal_execute({"cmd": "cd /etc"})
    assert res["status"] == "error"
    assert "Security Violation" in res["message"]


@pytest.mark.asyncio
async def test_social_media_polling():
    """Verify specialized social media polling."""
    sim = SocialMediaSimulator()
    res = sim.handle_social_post({"text": "Hello"})
    pid = res["id"]

    assert await sim.on_poll("post_confirmed", {"post_id": pid}) is True
    assert await sim.on_poll("post_confirmed", {"post_id": "missing"}) is False


@pytest.mark.asyncio
async def test_iot_simulator_custom_execute():
    """Verify specialized IoT execution dispatch."""
    sim = IoTSimulator()
    res = await sim.execute("iot_update", {"device": "lights", "state": "on"})
    assert res["status"] == "success"
    assert res["state"] == "on"


@pytest.mark.asyncio
async def test_browser_simulator_cleanup():
    """Verify browser resource release."""
    sim = BrowserSimulator()
    sim._browser = AsyncMock()
    sim._playwright = AsyncMock()

    await sim.cleanup()
    sim._browser.close.assert_called_once()
    sim._playwright.stop.assert_called_once()
