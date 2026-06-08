import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import eval_runner.simulators as simulators
from eval_runner.plugins import BaseEvalPlugin, manager
from eval_runner.tool_sandbox import ToolSandbox


@pytest.mark.asyncio
async def test_base_simulator_logic():
    """Verify base simulator dispatch, state isolation, and hooks."""
    base = simulators.BaseSimulator({"init_key": "init_val", "active": True})
    assert base.state["init_key"] == "init_val"

    # 1. Dispatch
    res = await base.execute("invalid_action", {})
    assert res["status"] == "error"
    assert "Unknown action" in res["message"]

    # 2. Immutability
    snapshot = await base.get_snapshot()
    assert snapshot == base.state
    assert snapshot is not base.state

    # 3. on_poll (Liveness)
    assert await base.on_poll("active", {"expected_value": True}) is True
    assert await base.on_poll("active", {"expected_value": False}) is False
    assert await base.on_poll("active", {}) is True  # Truthiness
    assert await base.on_poll("missing", {}) is True  # Default fallback

    # 4. on_verify (Forensics)
    assert (await base.on_verify({}))["status"] == "success"
    assert (await base.on_verify({"criteria": {"active": True}}))["status"] == "success"
    res_err = await base.on_verify({"criteria": {"active": False}})
    assert res_err["status"] == "error"
    assert "State mismatch" in res_err["message"]


@pytest.mark.asyncio
async def test_git_simulator_logic(tmp_path):
    """Verify Git shim with mock repo and path safety."""
    git = simulators.GitSimulator()
    git.terminal_jail = tmp_path

    # Push (Simulated)
    assert (await git.execute("git_push", {}))["status"] == "success"

    # Error: No URL
    res = await git.execute("git_clone", {})
    assert res["status"] == "error"

    # Success: Clone
    with patch("git.Repo.clone_from") as mock_clone:
        res = await git.execute("git_clone", {"url": "https://github.com/test/repo"})
        assert res["status"] == "success"
        mock_clone.assert_called_once()

    # Hit _get_repo logic for existing repo
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()
    with patch("git.Repo") as mock_repo_init:
        git._repo = None  # Force re-fetch
        repo = git._get_repo()
        assert repo is not None
        mock_repo_init.assert_called_with(repo_dir)

    # Success: Add & Commit
    with patch("git.Repo") as mock_repo_class:
        mock_repo = mock_repo_class.return_value
        git._repo = mock_repo

        res = await git.execute("git_add", {"files": ["file1.txt"]})
        assert res["status"] == "success"
        mock_repo.index.add.assert_called_with(["file1.txt"])

        mock_commit = MagicMock()
        mock_commit.hexsha = "abc123"
        mock_repo.index.commit.return_value = mock_commit

        res = await git.execute("git_commit", {"message": "feat: test"})
        assert res["status"] == "success"
        assert res["dna"]["commit_sha"] == "abc123"

    # Exception Handling (Add/Commit/Clone)
    with patch("git.Repo") as mock_repo_class:
        mock_repo = mock_repo_class.return_value
        git._repo = mock_repo
        mock_repo.index.add.side_effect = Exception("ADD FAIL")
        assert (await git.execute("git_add", {"files": ["x"]}))["status"] == "error"

        mock_repo.index.commit.side_effect = Exception("GIT FAIL")
        res = await git.execute("git_commit", {"message": "fail"})
        assert res["status"] == "error"
        assert "GIT FAIL" in res["message"]

    # No repo error path
    git._repo = None
    with patch("eval_runner.simulators.GitSimulator._get_repo", return_value=None):
        assert (await git.execute("git_commit", {}))["status"] == "error"

    with patch("git.Repo.clone_from", side_effect=Exception("CLONE FAIL")):
        assert (await git.execute("git_clone", {"url": "u"}))["status"] == "error"

    await git.cleanup()


@pytest.mark.asyncio
async def test_jira_simulator_logic():
    """Verify Jira shim issue lifecycle and errors."""
    jira = simulators.JiraSimulator()
    # Create
    res = await jira.execute("jira_create", {"summary": "critical bug"})
    assert res["status"] == "success"
    issue_id = res["id"]

    # Update
    res = await jira.execute("jira_update", {"id": issue_id, "status": "In Progress"})
    assert res["status"] == "success"

    # Error: Update missing
    res = await jira.execute("jira_update", {"id": "NON-EXISTENT", "status": "Done"})
    assert res["status"] == "error"

    # List/Verify
    res = await jira.execute("jira_list", {})
    assert res["status"] == "success"
    issue = next(i for i in jira.state["issues"] if i["id"] == issue_id)
    assert issue["status"] == "In Progress"


@pytest.mark.asyncio
async def test_database_simulator_logic(tmp_path):
    """Verify Database shim with SQLite engine and forensic snapshots."""
    db = simulators.DatabaseSimulator()
    db.terminal_jail = tmp_path

    # Query existing
    res = await db.execute("database_query", {"query": "SELECT * FROM users"})
    assert res["status"] == "success"
    assert len(res["rows"]) >= 1

    # Insert
    await db.execute(
        "database_query", {"query": "INSERT INTO users (email, role) VALUES ('a@b.com', 'admin')"}
    )
    # Update & Delete
    await db.execute("database_query", {"query": "UPDATE users SET role='user' WHERE id=1"})
    await db.execute("database_query", {"query": "DELETE FROM users WHERE id=1"})

    # Forensic Snapshot Verification
    snap = await db.get_snapshot()
    assert "audit_log" in snap
    assert len(snap["audit_log"]) >= 3
    assert "users" in snap["tables"]

    # Test JSON decoding failure in snapshot
    with patch("json.loads", side_effect=Exception("JSON ERROR")):
        snap_err = await db.get_snapshot()
        assert len(snap_err["audit_log"]) > 0  # Still returns, just logs error

    # Snapshot error path
    db._get_engine()
    db._engine = MagicMock()
    db._engine.connect.side_effect = Exception("DB DEAD")
    snap_fail = await db.get_snapshot()
    assert "error" in snap_fail

    # Error: Invalid SQL
    db._engine = None  # Restore
    res = await db.execute("database_query", {"query": "DROP TABLE non_existent"})
    assert res["status"] == "error"

    # Exception in execution
    with patch("sqlalchemy.text", side_effect=Exception("SQL FAIL")):
        res_e = await db.execute("database_query", {"query": "SELECT"})
        assert res_e["status"] == "error"

    await db.cleanup()


@pytest.mark.asyncio
async def test_terminal_simulator_logic(tmp_path):
    """Verify Terminal shim with subprocess execution and security."""
    term = simulators.TerminalSimulator()
    term.terminal_jail = tmp_path

    # Security: Path traversal
    res = await term.execute("terminal_execute", {"cmd": "cd ../../etc/passwd"})
    assert res["status"] == "error"
    assert "Security Violation" in res["message"]

    # Execution: Python script
    cmd = f"{sys.executable} -c \"print('hello-world')\""
    res = await term.execute("terminal_execute", {"cmd": cmd})
    assert res["status"] == "success"
    assert "hello-world" in res["stdout"]

    # Subprocess Exception
    with patch("subprocess.run", side_effect=Exception("CRASH")):
        res = await term.execute("terminal_execute", {"cmd": "ls"})
        assert res["status"] == "error"
        assert "CRASH" in res["message"]

    # Timeout
    with patch("subprocess.run", side_effect=simulators.subprocess.TimeoutExpired(["echo"], 5.0)):
        res = await term.execute("terminal_execute", {"cmd": "sleep 10"})
        assert res["status"] == "error"
        assert "timed out" in res["message"]

    await term.cleanup()


@pytest.mark.asyncio
async def test_browser_simulator_logic():
    """Verify Browser shim with Playwright mocks."""
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

    mock_page.title.return_value = "AgentV Portal"
    mock_page.url = "https://agentv.ai"
    mock_page.goto = AsyncMock()

    with patch("playwright.async_api.async_playwright", return_value=mock_pw):
        res = await browser.execute("browser_go", {"url": "https://agentv.ai"})
        assert res["status"] == "success"
        assert res["title"] == "AgentV Portal"

        # Browser Exception
        mock_page.goto.side_effect = Exception("PAGE CRASH")
        res_err = await browser.execute("browser_go", {"url": "https://fail.com"})
        assert res_err["status"] == "error"

    await browser.cleanup()
    mock_browser.close.assert_called_once()


@pytest.mark.asyncio
async def test_api_simulator_logic():
    """Verify API shim with mock/live modes and URL normalization."""
    api = simulators.ApiSimulator()

    # Invalid URL
    assert (await api.execute("api_request", {"url": ""}))["status"] == "error"

    # Mock Mode
    res = await api.execute("api_request", {"method": "GET", "path": "/api/v1/health"})
    assert res["status"] == "success"
    # Snapshot
    snap = await api.get_snapshot()
    assert "/api/v1/health" in snap["endpoints"]

    # Backward compatibility dispatch
    res_bc = await api.execute("POST", {"path": "/api/v1/health"})
    assert res_bc["status"] == "success"

    # Live Mode + Exception
    with patch("os.getenv", side_effect=lambda k, d=None: "true" if k == "IS_LIVE" else d):
        with patch("httpx.AsyncClient", side_effect=Exception("NET FAIL")):
            res = await api.execute("api_request", {"method": "GET", "url": "api.io"})
            assert res["status"] == "error"
            assert "NET FAIL" in res["message"]

    # Live Mode + Success + Normalization + Timeout Parse + Content
    with patch(
        "os.getenv",
        side_effect=lambda k, d=None: (
            "true" if k == "IS_LIVE" else "INVALID" if k == "SHIM_TIMEOUT" else d
        ),
    ):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.is_success = True
        mock_resp.json.return_value = {"status": "ok"}
        mock_client.request.return_value = mock_resp

        with patch("httpx.AsyncClient", return_value=mock_client):
            res = await api.execute(
                "api_request", {"method": "POST", "url": "api.test/v1", "data": {"x": 1}}
            )
            assert res["status"] == "success"
            # Verify called correctly without positional mismatch
            args, kwargs = mock_client.request.call_args
            assert kwargs["method"] == "POST"
            assert kwargs["url"] == "http://api.test/v1"
            assert kwargs["json"] == {"x": 1}

    await api.cleanup()


@pytest.mark.asyncio
async def test_hotswap_and_discovery_guardrails(tmp_path):
    """Verify dynamic shim registration and discovery/filtering protocols."""

    class CustomShim:
        def __init__(self, **kwargs):
            pass

        async def execute(self, action, params):
            return {"status": "success", "msg": "custom-ok"}

    class CustomPlugin(BaseEvalPlugin):
        def on_register_simulators(self, registry):
            registry["custom"] = CustomShim

    plugin = CustomPlugin()
    manager.plugins.append(plugin)

    try:
        # Discovery
        registry = simulators.get_simulator_registry()
        assert "custom" in registry

        # Sandbox Filtering
        from eval_runner import config

        with patch.object(config, "GLOBAL_ENABLED_SHIMS", config.GLOBAL_ENABLED_SHIMS + ["custom"]):
            scen = {"id": "t", "enabled_shims": ["custom"]}
            sandbox = ToolSandbox(scen, workspace_root=tmp_path)
            res = await sandbox.execute("custom_action", {})
            assert res["status"] == "success"
            assert res["msg"] == "custom-ok"

    finally:
        manager.plugins.remove(plugin)


@pytest.mark.asyncio
async def test_miscellaneous_shims_logic():
    """Verify high-level shims coverage."""
    # Cloud
    cloud = simulators.CloudSimulator()
    res = await cloud.execute("cloud_launch", {"type": "t2.micro"})
    iid = res["instance_id"]
    assert await cloud.on_poll("instance_running", {"instance_id": iid}) is True
    assert await cloud.on_poll("unknown", {}) is False
    assert next(i for i in cloud.state["instances"] if i["id"] == iid)["status"] == "running"

    # CICD
    cicd = simulators.CICDSimulator()
    res = await cicd.execute("cicd_deploy", {"environment": "prod"})
    bid = res["build_id"]
    await cicd.on_poll("build_complete", {"build_id": bid})
    assert cicd.state["builds"][-1]["status"] == "success"

    # ERP
    erp = simulators.ERPSimulator()
    assert (await erp.execute("erp_create_order", {"item": "X"}))["status"] == "success"

    # Social/Slack/Email/CRM/Stripe/KB/Support/Vector/IoT
    for shim_class, action, params in [
        (simulators.SocialMediaSimulator, "social_post", {"text": "hi"}),
        (simulators.SlackSimulator, "slack_send", {"channel": "#dev", "message": "hi"}),
        (simulators.EmailSimulator, "email_send", {"to": "a@b.com", "body": "hi"}),
        (simulators.EmailSimulator, "email_list", {}),
        (simulators.CalendarSimulator, "calendar_book", {"title": "X"}),
        (simulators.CRMSimulator, "crm_update_lead", {"id": "L101", "status": "OK"}),
        (simulators.StripeSimulator, "stripe_charge", {"amount": 100}),
        (simulators.KnowledgeBaseSimulator, "kb_search", {"query": "q"}),
        (simulators.SupportDeskSimulator, "support_close", {"id": "TKT-123"}),
        (simulators.VectorDBSimulator, "vector_query", {"vec": [0, 1]}),
        (simulators.IoTSimulator, "iot_update", {"device": "lights", "state": "off"}),
    ]:
        shim = shim_class()
        res = await shim.execute(action, params)
        assert res["status"] == "success"
        # Hit truthiness on_poll for Social
        if shim_class == simulators.SocialMediaSimulator:
            assert await shim.on_poll("post_confirmed", {"post_id": res["id"]}) is True
            assert await shim.on_poll("post_confirmed", {"post_id": "missing"}) is False

        await shim.cleanup()

    # Specialized Errors
    assert (await simulators.CRMSimulator().execute("crm_update_lead", {"id": "MISSING"}))[
        "status"
    ] == "error"
    assert (await simulators.SupportDeskSimulator().execute("support_close", {"id": "MISSING"}))[
        "status"
    ] == "error"
    assert (
        await simulators.SocialMediaSimulator().on_poll("post_confirmed", {"post_id": "MISSING"})
    ) is False
    assert (await simulators.IoTSimulator().execute("iot_update", {"device": "OFFLINE"}))[
        "status"
    ] == "error"


@pytest.mark.asyncio
async def test_security_simulator_logic():
    """Verify Security shim authentication lifecycle."""
    sec = simulators.SecuritySimulator()

    # Auth
    res = await sec.execute("security_auth", {"scope": "admin"})
    assert res["status"] == "success"
    token = res["token"]
    assert token in sec.state["active_tokens"]

    # Cleanup
    await sec.cleanup()


@pytest.mark.asyncio
async def test_git_simulator_extra_coverage(tmp_path):
    git = simulators.GitSimulator()
    git.terminal_jail = tmp_path

    # 1. git_add with no repo
    with patch.object(git, "_get_repo", return_value=None):
        res = await git.execute("git_add", {"files": ["x"]})
        assert res["status"] == "error"

    # 2. git.cleanup with self._repo present
    git._repo = MagicMock()
    await git.cleanup()
    assert git._repo is None


@pytest.mark.asyncio
async def test_api_simulator_timeout_type_error():
    api = simulators.ApiSimulator()
    mock_str = MagicMock()
    mock_str.replace.side_effect = TypeError("mocked type error")
    with patch("os.getenv", return_value=mock_str):
        res = await api.execute("GET", {"path": "/api/v1/health"})
        assert res["status"] == "success"


@pytest.mark.asyncio
async def test_database_simulator_extra_coverage(tmp_path):
    db = simulators.DatabaseSimulator()
    db.terminal_jail = tmp_path

    # 1. CREATE TABLE trigger creation
    res = await db.execute("database_query", {"query": "CREATE TABLE test_table (id INTEGER)"})
    assert res["status"] == "success"

    # 2. Table with no columns
    with patch("sqlalchemy.inspect") as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.get_table_names.return_value = ["empty_table"]
        mock_inspector.get_columns.return_value = []
        mock_inspect.return_value = mock_inspector
        db._provision_forensic_log(db._get_engine())

    # 3. get_snapshot when _engine is None
    with patch.object(db, "_get_engine"):
        db._engine = None
        snap = await db.get_snapshot()
        assert snap["engine"] == "mock"


@pytest.mark.asyncio
async def test_terminal_simulator_extra_coverage(tmp_path):
    term = simulators.TerminalSimulator()

    # 1. Execute empty command
    res = await term.execute("terminal_execute", {})
    assert res["status"] == "error"

    # 2. No terminal jail path
    res = await term.execute("terminal_execute", {"cmd": "ls"})
    assert res["status"] == "error"

    # 3. Successful cd command
    term.terminal_jail = tmp_path
    term.state["cwd"] = str(tmp_path)
    res = await term.execute("terminal_execute", {"cmd": "cd ."})
    assert res["status"] == "success"

    # 4. execute directly with command string (ls)
    res = await term.execute("ls", {})
    assert "status" in res


@pytest.mark.asyncio
async def test_miscellaneous_shims_on_poll_and_execute():
    social = simulators.SocialMediaSimulator()
    assert await social.on_poll("unknown", {}) is False

    cicd = simulators.CICDSimulator()
    assert await cicd.on_poll("unknown", {}) is False

    iot = simulators.IoTSimulator()
    res = await iot.execute("unknown", {})
    assert res["status"] == "error"
