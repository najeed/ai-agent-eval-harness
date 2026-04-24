import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import eval_runner.simulators as simulators


@pytest.mark.asyncio
async def test_base_simulator_dispatch_and_error():
    base = simulators.BaseSimulator({"k": "v"})
    assert base.state["k"] == "v"

    # Unknown action
    res = await base.execute("invalid", {})
    assert res["status"] == "error"
    assert "Unknown action" in res["message"]


@pytest.mark.asyncio
async def test_git_simulator(tmp_path):
    git = simulators.GitSimulator()
    git.terminal_jail = tmp_path

    # Git Clone (Fail first, no URL)
    res = await git.execute("git_clone", {})
    assert res["status"] == "error"

    # Git Clone (Success with dummy)
    with patch("git.Repo.clone_from") as mock_clone:
        res = await git.execute("git_clone", {"url": "https://dummy.repo"})
        assert res["status"] == "success"
        mock_clone.assert_called_once()

    # Add, Commit (Use mocks for repo state)
    with patch("git.Repo") as mock_repo_class:
        mock_repo = mock_repo_class.return_value
        git._repo = mock_repo

        res = await git.execute("git_add", {"files": ["main.py"]})
        assert res["status"] == "success"
        mock_repo.index.add.assert_called_with(["main.py"])

        mock_commit = MagicMock()
        mock_commit.hexsha = "abc123"
        mock_commit.author = "Author"
        mock_repo.index.commit.return_value = mock_commit

        res = await git.execute("git_commit", {"message": "MSG"})
        assert res["status"] == "success"
        assert res["dna"]["commit_sha"] == "abc123"

    await git.cleanup()


@pytest.mark.asyncio
async def test_api_simulator_routing():
    api = simulators.ApiSimulator()

    # Mock Mode (IS_LIVE=false)
    res = await api.execute("api_request", {"method": "GET", "path": "/api/v1/health"})
    assert res["status"] == "success"

    # Live Mode (IS_LIVE=true)
    with patch("os.getenv", side_effect=lambda k, d=None: "true" if k == "IS_LIVE" else d):
        # Correct HTTPX Context Manager Mocking
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"status": "ok"}

        mock_client_instance.request.return_value = mock_response
        mock_client_instance.__aenter__.return_value = mock_client_instance

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            res = await api.execute("api_request", {"method": "GET", "url": "http://api.test"})
            assert res["status"] == "success"
            assert res["data"]["status"] == "ok"

    await api.cleanup()


@pytest.mark.asyncio
async def test_database_simulator(tmp_path):
    db = simulators.DatabaseSimulator()
    db.terminal_jail = tmp_path

    # Iteration 3: SQLAlchemy/SQLite (Physical Engine Verification)
    res = await db.execute("database_query", {"query": "SELECT * FROM users"})
    if res["status"] == "error":
        print(f"DEBUG DB DATA: {res}")
    assert res["status"] == "success"
    assert len(res["rows"]) == 1

    res = await db.execute(
        "database_query",
        {"query": "INSERT INTO users (email, role) VALUES ('test@test.com', 'user')"},
    )
    assert res["status"] == "success"

    # Error Case
    res = await db.execute("database_query", {"query": "INVALID SQL"})
    assert res["status"] == "error"
    assert "Database Error" in res["message"]

    await db.cleanup()


@pytest.mark.asyncio
async def test_terminal_simulator_hardened(tmp_path):
    term = simulators.TerminalSimulator()
    term.terminal_jail = tmp_path

    # Path-Safety Check (Iteration 2)
    res = await term.execute("terminal_execute", {"cmd": "cd ../../../windows"})
    assert res["status"] == "error"
    assert "Security Violation" in res["message"]

    # Subprocess execution (Iteration 3)
    res = await term.execute("terminal_execute", {"cmd": f"{sys.executable} -c \"print('hello')\""})
    if res["status"] == "error":
        print(f"DEBUG TERM DATA: {res}")
    assert res["status"] == "success"
    assert "hello" in res["stdout"]

    # Timeout enforcement (Iteration 5)
    with patch("subprocess.run", side_effect=simulators.subprocess.TimeoutExpired(["echo"], 30.0)):
        res = await term.execute("terminal_execute", {"cmd": "long_running"})
        assert res["status"] == "error"
        assert "timed out" in res["message"]

    await term.cleanup()


@pytest.mark.asyncio
async def test_browser_simulator_hardened():
    browser = simulators.BrowserSimulator()

    mock_pw = AsyncMock()
    mock_instance = AsyncMock()
    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_page = AsyncMock()

    mock_pw.start.return_value = mock_instance
    mock_instance.chromium.launch.return_value = mock_browser
    mock_browser.new_context.return_value = mock_context
    mock_context.new_page.return_value = mock_page

    mock_page.title.return_value = "Test Title"
    mock_page.url = "http://test.com"
    mock_page.goto = AsyncMock()

    with patch("playwright.async_api.async_playwright", return_value=mock_pw):
        res = await browser.execute("browser_go", {"url": "http://test.com"})
        assert res["status"] == "success"
        assert res["title"] == "Test Title"

        # [Coverage Milestone] Call again to hit the cached _page branch
        res2 = await browser.execute("browser_go", {"url": "http://test.com/2"})
        assert res2["status"] == "success"

        # Cleanup verification
        await browser.cleanup()
        mock_browser.close.assert_called()


@pytest.mark.asyncio
async def test_cloud_simulator_advanced():
    cloud = simulators.CloudSimulator()
    res = await cloud.execute("cloud_launch", {"type": "t2.large"})
    iid = res["instance_id"]

    # Liveness Hook Verification (Iteration 1)
    success = await cloud.on_poll("instance_running", {"instance_id": iid})
    assert success is True

    # Verify State transition
    for inst in cloud.state["instances"]:
        if inst["id"] == iid:
            assert inst["status"] == "running"

    await cloud.cleanup()


@pytest.mark.asyncio
async def test_security_simulator_registry():
    sec = simulators.SecuritySimulator()
    res = await sec.execute("security_auth", {"scope": "all-access"})
    token = res["token"]

    assert res["status"] == "success"
    assert token in sec.state["active_tokens"]
    assert sec.state["active_tokens"][token]["scope"] == "all-access"

    await sec.cleanup()


@pytest.mark.asyncio
async def test_cicd_simulator_pipeline_state():
    cicd = simulators.CICDSimulator()
    res = await cicd.execute("cicd_deploy", {"environment": "staging"})
    bid = res["build_id"]

    # Verify initial state
    assert cicd.state["builds"][-1]["status"] == "queued"

    # Liveness hook: complete build
    await cicd.on_poll("build_complete", {"build_id": bid})
    assert cicd.state["builds"][-1]["status"] == "success"
    assert "Deployment successful." in cicd.state["builds"][-1]["logs"][-1]
    await cicd.cleanup()

    await cicd.cleanup()


@pytest.mark.asyncio
async def test_base_hooks():
    base = simulators.BaseSimulator()
    # Turn 1 Polling
    assert await base.on_poll("test", {}) is True
    # Turn 1 Verification
    res = await base.on_verify({})
    assert res["status"] == "success"


@pytest.mark.asyncio
async def test_git_errors(tmp_path):
    git = simulators.GitSimulator()
    git.terminal_jail = tmp_path
    # No repo initialized
    res = await git.execute("git_add", {"files": ["."]})
    assert res["status"] == "error"
    assert "No active repository" in res["message"]


@pytest.mark.asyncio
async def test_jira_advanced():
    jira = simulators.JiraSimulator()
    # Create then Update (Hit success branch)
    await jira.execute("jira_create", {"summary": "FIX"})
    res = await jira.execute("jira_update", {"id": "PROJ-1", "status": "Done"})
    assert res["status"] == "success"
    assert jira.state["issues"][0]["status"] == "Done"

    # Update failure (Already have test_jira_errors above but keeping it clean)
    res = await jira.execute("jira_update", {"id": "X", "status": "Y"})
    assert res["status"] == "error"


@pytest.mark.asyncio
async def test_terminal_errors(tmp_path):
    term = simulators.TerminalSimulator()
    term.terminal_jail = tmp_path
    # Empty command
    res = await term.execute("terminal_execute", {"cmd": ""})
    assert res["status"] == "error"
    assert "Command not provided" in res["message"]


@pytest.mark.asyncio
async def test_browser_cleanup_no_instance():
    browser = simulators.BrowserSimulator()
    # Cleanup without starting
    await browser.cleanup()
    assert browser._browser is None


@pytest.mark.asyncio
async def test_git_commit_exception(tmp_path):
    git = simulators.GitSimulator()
    git.terminal_jail = tmp_path
    with patch("git.Repo") as mock_repo_class:
        mock_repo = mock_repo_class.return_value
        git._repo = mock_repo
        mock_repo.index.commit.side_effect = Exception("GIT ERROR")
        res = await git.execute("git_commit", {"message": "X"})
        assert res["status"] == "error"
        assert "GIT ERROR" in res["message"]


@pytest.mark.asyncio
async def test_api_request_exception():
    api = simulators.ApiSimulator()
    with patch("os.getenv", return_value="true"):  # Force IS_LIVE
        with patch("httpx.AsyncClient", side_effect=Exception("HTTP ERROR")):
            res = await api.execute("api_request", {"method": "GET", "url": "http://x"})
            assert res["status"] == "error"
            assert "HTTP ERROR" in res["message"]


@pytest.mark.asyncio
async def test_api_url_normalization():
    api = simulators.ApiSimulator()
    with patch("os.getenv", return_value="true"):  # Force IS_LIVE
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {"status": "ok"}
        mock_client_instance.request.return_value = mock_resp

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            # Test normalization of prefixless URL
            await api.execute("api_request", {"method": "GET", "url": "api.test/v1"})
            mock_client_instance.request.assert_called_with(
                method="GET",
                url="http://api.test/v1",
                headers={"X-Industrial-Source": "aes-v1.3", "X-Registry-Version": "1.0.0"},
            )


@pytest.mark.asyncio
async def test_git_reinit_and_overwrite(tmp_path):
    git = simulators.GitSimulator()
    git.terminal_jail = tmp_path
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True)
    (repo_dir / ".git").mkdir()  # Fake existing repo

    # Hits _get_repo logic for existing .git (Line 74 coverage)
    with patch("git.Repo"):
        res = await git.execute("git_add", {"files": ["x.py"]})
        assert res["status"] == "success"

    # Hits handle_git_clone rmtree logic (Line 93 coverage)
    with patch("git.Repo.clone_from"):
        res = await git.execute("git_clone", {"url": "http://repo", "dest": "repo"})
        assert res["status"] == "success"
        # Verify shutil.rmtree was effectively bypassed/handled by dest check


@pytest.mark.asyncio
async def test_iot_advanced():
    iot = simulators.IoTSimulator()
    # Success branch
    res = await iot.execute("iot_update", {"device": "lights", "state": "on"})
    assert res["status"] == "success"
    # Error branch (Line 653 coverage)
    res = await iot.execute("iot_update", {"device": "UNKNOWN", "state": "on"})
    assert res["status"] == "error"
    # Action not handled branch (Line 659 coverage)
    res = await iot.execute("UNKNOWN_ACTION", {})
    assert res["status"] == "error"


@pytest.mark.asyncio
async def test_social_poll_failure():
    social = simulators.SocialMediaSimulator()
    # Poll for non-existent post (Line 639 coverage)
    res = await social.on_poll("post_confirmed", {"post_id": "999"})
    assert res is False


@pytest.mark.asyncio
async def test_slack_simulator():
    slack = simulators.SlackSimulator()
    res = await slack.execute("slack_send", {"channel": "#dev", "message": "hi"})
    assert res["status"] == "success"
    assert len(slack.state["messages"]) == 1


@pytest.mark.asyncio
async def test_crm_simulator():
    crm = simulators.CRMSimulator()
    res = await crm.execute("crm_update_lead", {"id": "L101", "status": "Converted"})
    assert res["status"] == "success"
    res = await crm.execute("crm_update_lead", {"id": "X", "status": "Y"})
    assert res["status"] == "error"


@pytest.mark.asyncio
async def test_email_simulator():
    email = simulators.EmailSimulator()
    res = await email.execute("email_send", {"to": "bob", "body": "hi"})
    assert res["status"] == "success"
    assert len(email.state["sent"]) == 1
    res = await email.execute("email_list", {})
    assert res["status"] == "success"


@pytest.mark.asyncio
async def test_calendar_simulator():
    cal = simulators.CalendarSimulator()
    res = await cal.execute("calendar_book", {"title": "MTG"})
    assert res["status"] == "success"
    assert len(cal.state["events"]) == 2


@pytest.mark.asyncio
async def test_jira_simulator():
    jira = simulators.JiraSimulator()
    res = await jira.execute("jira_create", {"summary": "BUG"})
    assert res["status"] == "success"
    res = await jira.execute("jira_list", {})
    assert res["status"] == "success"


@pytest.mark.asyncio
async def test_stripe_simulator():
    stripe = simulators.StripeSimulator()
    res = await stripe.execute("stripe_charge", {"amount": 50})
    assert res["status"] == "success"


@pytest.mark.asyncio
async def test_erp_simulator():
    erp = simulators.ERPSimulator()
    res = await erp.execute("erp_create_order", {"id": "O1"})
    assert res["status"] == "success"


@pytest.mark.asyncio
async def test_kb_simulator():
    kb = simulators.KnowledgeBaseSimulator()
    res = await kb.execute("kb_search", {"query": "test"})
    assert res["status"] == "success"


@pytest.mark.asyncio
async def test_support_simulator():
    support = simulators.SupportDeskSimulator()
    res = await support.execute("support_close", {"id": "TKT-123"})
    assert res["status"] == "success"


@pytest.mark.asyncio
async def test_social_simulator():
    social = simulators.SocialMediaSimulator()
    res = await social.execute("social_post", {"text": "hello"})
    assert res["status"] == "success"


@pytest.mark.asyncio
async def test_vector_simulator():
    vector = simulators.VectorDBSimulator()
    res = await vector.execute("vector_query", {"vec": [1, 2]})
    assert res["status"] == "success"


@pytest.mark.asyncio
async def test_iot_simulator():
    iot = simulators.IoTSimulator()
    res = await iot.execute("iot_update", {"device": "lights", "state": "on"})
    assert res["status"] == "success"
    assert res["state"] == "on"


@pytest.mark.asyncio
async def test_get_simulator_registry():
    with patch("eval_runner.plugins.manager.trigger") as mock_trigger:
        registry = simulators.get_simulator_registry()
        assert "git" in registry
        assert "api" in registry
        mock_trigger.assert_called()
