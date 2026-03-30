import unittest
from unittest.mock import MagicMock, patch
from io import StringIO
import sys

# SUT
import eval_runner.simulators as simulators

class TestSimulators(unittest.TestCase):

    def test_base_simulator_dispatch_and_error(self):
        base = simulators.BaseSimulator({"k": "v"})
        self.assertEqual(base.state["k"], "v")
        
        # Unknown action (Line 21)
        res = base.execute("invalid", {})
        self.assertEqual(res["status"], "error")
        self.assertIn("Unknown action", res["message"])

        # Destructor cover (Line 31-33)
        with patch.object(base, "cleanup", side_effect=Exception("cleanup failed")):
            base.__del__() # Should pass silently

    def test_git_simulator(self):
        git = simulators.GitSimulator()
        self.assertEqual(git.execute("git_clone", {"url": "http://repo"})["status"], "success")
        self.assertEqual(git.execute("git_add", {"files": ["a.py"]})["status"], "success")
        self.assertEqual(git.state["staged_files"], ["a.py"])
        self.assertEqual(git.execute("git_commit", {"message": "MSG"})["status"], "success")
        self.assertEqual(len(git.state["history"]), 2)
        self.assertEqual(git.state["staged_files"], [])
        self.assertEqual(git.execute("git_push", {})["status"], "success")

    def test_api_simulator_routing(self):
        api = simulators.ApiSimulator()
        
        # GET success
        res = api.execute("api_request", {"method": "GET", "path": "/api/v1/health"})
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["data"]["status"], "healthy")

        # GET 404
        res = api.execute("api_request", {"method": "GET", "path": "/missing"})
        self.assertEqual(res["status"], "error")
        
        # POST registration (Line 88-92)
        res = api.execute("api_request", {"method": "POST", "path": "/new", "data": {"val": 1}})
        self.assertEqual(res["status"], "success")
        self.assertEqual(api.state["endpoints"]["/new"]["val"], 1)

        # Unsupported method (Line 93)
        res = api.execute("api_request", {"method": "DELETE", "path": "/api/v1/health"})
        self.assertEqual(res["status"], "error")

        # Backward compatibility shim (Line 96-99)
        res = api.execute("GET", {"path": "/api/v1/health"})
        self.assertEqual(res["status"], "success")

    def test_database_simulator(self):
        db = simulators.DatabaseSimulator()
        self.assertEqual(db.execute("database_query", {"query": "SELECT *"})["status"], "success")
        self.assertEqual(db.execute("database_query", {"query": "INSERT", "data": {"id": 2}})["status"], "success")
        self.assertEqual(len(db.state["tables"]["logs"]), 1)
        self.assertEqual(db.execute("database_query", {"query": "DROP"})["status"], "error")

    def test_slack_simulator(self):
        slack = simulators.SlackSimulator()
        res = slack.execute("slack_send", {"channel": "#dev", "message": "hello"})
        self.assertEqual(res["status"], "success")
        self.assertEqual(len(slack.state["messages"]), 1)

    def test_crm_simulator(self):
        crm = simulators.CRMSimulator()
        self.assertEqual(crm.execute("crm_update_lead", {"id": "L101", "status": "In Progress"})["status"], "success")
        self.assertEqual(crm.execute("crm_update_lead", {"id": "MISSING", "status": "X"})["status"], "error")

    def test_email_simulator(self):
        email = simulators.EmailSimulator()
        self.assertEqual(email.execute("email_list", {})["status"], "success")
        self.assertEqual(email.execute("email_send", {"to": "a", "body": "b"})["status"], "success")
        self.assertEqual(len(email.state["sent"]), 1)

    def test_calendar_simulator(self):
        cal = simulators.CalendarSimulator()
        self.assertEqual(cal.execute("calendar_book", {"title": "MTG"})["status"], "success")
        self.assertEqual(len(cal.state["events"]), 2)

    def test_jira_simulator(self):
        jira = simulators.JiraSimulator()
        res = jira.execute("jira_create", {"summary": "BUG"})
        self.assertEqual(res["status"], "success")
        self.assertEqual(jira.execute("jira_update", {"id": res["id"], "status": "Done"})["status"], "success")
        self.assertEqual(jira.execute("jira_update", {"id": "X", "status": "Y"})["status"], "error")
        self.assertEqual(jira.execute("jira_list", {})["status"], "success")

    def test_cloud_simulator(self):
        cloud = simulators.CloudSimulator()
        self.assertEqual(cloud.execute("cloud_launch", {"type": "p3.xlarge"})["status"], "success")
        self.assertEqual(len(cloud.state["instances"]), 2)

    def test_terminal_simulator_shims(self):
        term = simulators.TerminalSimulator()
        # Direct execute as "ls" (Line 251-253)
        res = term.execute("ls", {})
        self.assertEqual(res["status"], "success")
        self.assertIn("file1.txt", res["output"])
        
        # cd shim
        term.execute("cd", {"path": "/tmp"})
        self.assertEqual(term.state["cwd"], "/tmp")
        
        # regular execute
        self.assertEqual(term.execute("terminal_execute", {"cmd": "whoami"})["status"], "success")

    def test_various_small_simulators(self):
        # Stripe
        stripe = simulators.StripeSimulator()
        self.assertEqual(stripe.execute("stripe_charge", {"amt": 100})["status"], "success")
        
        # ERP
        erp = simulators.ERPSimulator()
        self.assertEqual(erp.execute("erp_create_order", {"id": "O1"})["status"], "success")
        
        # Browser
        browser = simulators.BrowserSimulator()
        self.assertEqual(browser.execute("browser_go", {"url": "http://google.com"})["status"], "success")
        
        # KB
        kb = simulators.KnowledgeBaseSimulator()
        self.assertEqual(kb.execute("kb_search", {})["status"], "success")
        
        # Support
        support = simulators.SupportDeskSimulator()
        self.assertEqual(support.execute("support_close", {"id": "TKT-123"})["status"], "success")
        self.assertEqual(support.execute("support_close", {"id": "MISSING"})["status"], "error")
        
        # Social
        social = simulators.SocialMediaSimulator()
        self.assertEqual(social.execute("social_post", {"text": "A"})["status"], "success")
        
        # Vector
        vector = simulators.VectorDBSimulator()
        self.assertEqual(vector.execute("vector_query", {})["status"], "success")
        
        # CICD
        cicd = simulators.CICDSimulator()
        self.assertEqual(cicd.execute("cicd_deploy", {})["status"], "success")
        self.assertEqual(len(cicd.state["builds"]), 2)
        
        # Security
        sec = simulators.SecuritySimulator()
        self.assertEqual(sec.execute("security_auth", {})["status"], "success")

    def test_iot_simulator_special_execute(self):
        iot = simulators.IoTSimulator()
        # Special case execute (Line 373)
        res = iot.execute("iot_update", {"device": "lights", "state": "on"})
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["state"], "on")
        # Error case
        self.assertEqual(iot.execute("iot_update", {"device": "door"})["status"], "error")
        # Base case via iot special execute
        self.assertEqual(iot.execute("invalid", {})["status"], "error")

    def test_registry_factory(self):
        # Line 415-427: get_simulator_registry
        with patch("eval_runner.plugins.manager.trigger") as mock_trigger:
            registry = simulators.get_simulator_registry()
            self.assertIn("git", registry)
            self.assertIn("api", registry)
            mock_trigger.assert_called_with("on_register_simulators", registry)

if __name__ == '__main__':
    unittest.main()
