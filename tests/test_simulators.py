import pytest
from eval_runner import simulators


def test_simulator_registry_discovery():
    """Test that all internal simulators are in the registry."""
    registry = simulators.get_simulator_registry()
    assert "git" in registry
    assert "api" in registry
    assert "slack" in registry
    assert "security" in registry


def test_git_simulator():
    sim = simulators.GitSimulator()
    res = sim.execute("git_clone", {"url": "http://repo.com"})
    assert res["status"] == "success"
    res = sim.execute("git_commit", {"message": "feat: test"})
    assert res["status"] == "success"
    assert sim.state["history"][-1]["message"] == "feat: test"
    res = sim.execute("git_push", {})
    assert res["status"] == "success"
    res = sim.execute("unknown", {})
    assert res["status"] == "error"


def test_api_simulator():
    sim = simulators.ApiSimulator()
    res = sim.execute("api_call", {"method": "GET", "path": "/api/v1/health"})
    assert res["status"] == "success"
    assert res["data"]["status"] == "healthy"
    res = sim.execute("api_call", {"method": "POST", "path": "/api/v1/user"})
    assert res["status"] == "success"
    res = sim.execute("api_call", {"method": "PATCH", "path": "/"})
    assert res["status"] == "error"


def test_database_simulator():
    sim = simulators.DatabaseSimulator()
    res = sim.execute("database_query", {"query": "SELECT *"})
    assert res["status"] == "success"
    res = sim.execute("database_query", {"query": "INSERT into logs", "data": {"msg": "hi"}})
    assert res["status"] == "success"
    assert len(sim.tables["logs"]) == 1
    res = sim.execute("bad", {})
    assert res["status"] == "error"


def test_slack_simulator():
    sim = simulators.SlackSimulator()
    res = sim.execute("slack_send", {"channel": "#dev", "message": "hello"})
    assert res["status"] == "success"
    assert len(sim.messages) == 1
    res = sim.execute("bad", {})
    assert res["status"] == "error"


def test_crm_simulator():
    sim = simulators.CRMSimulator()
    res = sim.execute("crm_update_lead", {"id": "L101", "status": "In Progress"})
    assert res["status"] == "success"
    assert sim.leads[0]["status"] == "In Progress"
    res = sim.execute("crm_update_lead", {"id": "BAD", "status": "In Progress"})
    assert res["status"] == "error"


def test_email_simulator():
    sim = simulators.EmailSimulator()
    res = sim.execute("email_send", {"to": "user@test.com"})
    assert res["status"] == "success"
    res = sim.execute("email_list", {})
    assert len(res["messages"]) > 0
    res = sim.execute("bad", {})
    assert res["status"] == "error"


def test_calendar_simulator():
    sim = simulators.CalendarSimulator()
    res = sim.execute("calendar_book", {"event": "meeting"})
    assert res["status"] == "success"
    res = sim.execute("bad", {})
    assert res["status"] == "error"


def test_jira_simulator():
    sim = simulators.JiraSimulator()
    res = sim.execute("jira_create", {"summary": "bug"})
    assert res["status"] == "success"
    res = sim.execute("jira_update", {"id": "PROJ-1", "status": "Done"})
    assert res["status"] == "success"
    res = sim.execute("jira_list", {})
    assert len(res["issues"]) > 0
    res = sim.execute("bad", {})
    assert res["status"] == "error"


def test_cloud_simulator():
    sim = simulators.CloudSimulator()
    res = sim.execute("cloud_launch", {})
    assert res["status"] == "success"
    res = sim.execute("bad", {})
    assert res["status"] == "error"


def test_terminal_simulator():
    sim = simulators.TerminalSimulator()
    res = sim.execute("run", {"cmd": "ls"})
    assert "file1.txt" in res["output"]
    res = sim.execute("run", {"cmd": "cd /tmp", "path": "/tmp"})
    assert res["status"] == "success"
    assert sim.cwd == "/tmp"
    res = sim.execute("run", {"cmd": "echo hi"})
    assert "Command executed" in res["output"]


def test_stripe_simulator():
    sim = simulators.StripeSimulator()
    res = sim.execute("stripe_charge", {"amount": 100})
    assert res["status"] == "success"
    res = sim.execute("bad", {})
    assert res["status"] == "error"


def test_erp_simulator():
    sim = simulators.ERPSimulator()
    res = sim.execute("erp_create_order", {"item": "Bolts"})
    assert res["status"] == "success"
    res = sim.execute("bad", {})
    assert res["status"] == "error"


def test_browser_simulator():
    sim = simulators.BrowserSimulator()
    res = sim.execute("browser_go", {"url": "http://google.com"})
    assert res["status"] == "success"
    assert sim.url == "http://google.com"
    res = sim.execute("bad", {})
    assert res["status"] == "success"


def test_kb_simulator():
    sim = simulators.KnowledgeBaseSimulator()
    res = sim.execute("kb_search", {"query": "test"})
    assert res["status"] == "success"
    res = sim.execute("bad", {})
    assert res["status"] == "error"


def test_support_simulator():
    sim = simulators.SupportDeskSimulator()
    res = sim.execute("support_close", {"id": "TKT-123"})
    assert res["status"] == "success"
    res = sim.execute("support_close", {"id": "BAD"})
    assert res["status"] == "error"


def test_social_simulator():
    sim = simulators.SocialMediaSimulator()
    res = sim.execute("social_post", {"text": "hello"})
    assert res["status"] == "success"
    res = sim.execute("social_list", {})
    assert res["status"] == "success"


def test_vector_simulator():
    sim = simulators.VectorDBSimulator()
    res = sim.execute("vector_query", {"v": [0.1]})
    assert res["status"] == "success"
    res = sim.execute("bad", {})
    assert res["status"] == "success"


def test_cicd_simulator():
    sim = simulators.CICDSimulator()
    res = sim.execute("cicd_deploy", {})
    assert res["status"] == "success"
    res = sim.execute("bad", {})
    assert res["status"] == "success"


def test_iot_simulator():
    sim = simulators.IoTSimulator()
    res = sim.execute("iot_update", {"device": "thermostat", "state": "75F"})
    assert res["status"] == "success"
    res = sim.execute("iot_update", {"device": "bad"})
    assert res["status"] == "error"


def test_security_simulator():
    sim = simulators.SecuritySimulator()
    res = sim.execute("security_auth", {})
    assert res["status"] == "success"
    res = sim.execute("bad", {})
    assert res["status"] == "error"
