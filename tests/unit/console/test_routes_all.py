import unittest
from unittest.mock import MagicMock, patch, mock_open
import json
import os
from pathlib import Path
from flask import Flask
from datetime import datetime

# SUT
from eval_runner.console.routes import core_bp, DebuggerStateStore, subscribe_debugger

class TestRoutes(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(core_bp)
        self.client = self.app.test_client()
        DebuggerStateStore.reset()

    @patch("eval_runner.config.PROJECT_ROOT", Path("/tmp/fake_root"))
    def test_get_loan_demo_context(self):
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.read_text", return_value="content"):
                response = self.client.get("/api/demo/loan/context")
                data = response.get_json()
                self.assertEqual(data["prd"], "content")
                self.assertIn("updated_at", data)

    @patch("subprocess.run")
    def test_execute_demo_command_whitelist(self, mock_run):
        # 1. Allowed command
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        res = self.client.post("/api/demo/execute", json={"command": "cat loan_prd.md"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")

        # 2. Blocked command (prefix)
        res = self.client.post("/api/demo/execute", json={"command": "rm -rf /"})
        self.assertEqual(res.status_code, 403)

        # 3. Blocked command (bad file)
        res = self.client.post("/api/demo/execute", json={"command": "cat /etc/passwd"})
        self.assertEqual(res.status_code, 403)

    @patch("eval_runner.catalog.ScenarioCatalog")
    def test_list_scenarios(self, mock_catalog_cls):
        mock_cat = mock_catalog_cls.return_value
        mock_cat.search.return_value = [{"id": "s1"}]
        
        res = self.client.get("/api/scenarios?q=test&industry=finance")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(len(data["scenarios"]), 1)
        mock_cat.search.assert_called_with(query="test", industry="finance", difficulty=None)

    @patch("eval_runner.config.RUN_LOG_DIR", Path("/tmp/runs"))
    def test_list_runs(self):
        # Mock run.jsonl content
        log_content = '{"event": "run_start", "run_id": "run_123", "scenario": "Test", "timestamp": "now"}\n'
        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=log_content)):
                res = self.client.get("/api/runs")
                data = res.get_json()
                self.assertTrue(len(data["runs"]) > 0)
                self.assertEqual(data["runs"][-1]["run_id"], "run_123")

    @patch("eval_runner.loader.load_scenario")
    @patch("eval_runner.engine.run_evaluation")
    @patch("threading.Thread")
    def test_evaluate_scenario(self, mock_thread, mock_run_eval, mock_load):
        mock_load.return_value = {"scenario_id": "scen_1"}
        with patch("pathlib.Path.exists", return_value=True):
            res = self.client.post("/api/evaluate", json={"path": "scenarios/test.json"})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.get_json()["status"], "started")
            mock_thread.assert_called()

    @patch("eval_runner.config.PROJECT_ROOT", Path("/tmp/root"))
    @patch("eval_runner.catalog.ScenarioCatalog")
    def test_save_scenario(self, mock_cat_cls):
        payload = {
            "scenario_id": "new-scen",
            "industry": "healthcare",
            "title": "New Healthcare Scenario",
            "tasks": [{"task_id": "t1", "description": "desc", "expected_outcome": "win"}]
        }
        with patch("pathlib.Path.mkdir"):
            with patch("builtins.open", mock_open()) as m_open:
                res = self.client.post("/api/scenarios", json=payload)
                self.assertEqual(res.status_code, 200)
                m_open.assert_called()
                # Verify JSON structure was written
                handle = m_open()
                written = "".join(call.args[0] for call in handle.write.call_args_list)
                written_json = json.loads(written)
                self.assertEqual(written_json["metadata"]["industry"], "healthcare")
                self.assertEqual(written_json["workflow"]["nodes"][0]["id"], "t1")

    def test_debugger_state_lifecycle(self):
        # 1. Update state
        res = self.client.post("/api/debugger/state", json={
            "event": "world_state_change",
            "data": {"state": {"hp": 100}}
        })
        self.assertEqual(res.status_code, 200)
        
        # 2. Get state
        res = self.client.get("/api/debugger/state")
        data = res.get_json()["data"]
        self.assertEqual(data["summary"]["state"]["hp"], 100)
        self.assertEqual(len(data["timeline"]), 1)

    @patch("eval_runner.config.RUN_LOG_DIR", Path("/tmp/runs"))
    def test_get_debugger_state_historical(self):
        # Mock historical .jsonl
        history = '{"event": "world_state_change", "state": {"val": 1}}\n'
        with patch("pathlib.Path.exists", return_value=True):
             with patch("builtins.open", mock_open(read_data=history)):
                 res = self.client.get("/api/debugger/state?run_id=run_456")
                 self.assertEqual(res.status_code, 200)
                 data = res.get_json()["data"]
                 self.assertEqual(data["summary"]["state"]["val"], 1)

    @patch("eval_runner.config.PROJECT_ROOT", Path("/tmp/root"))
    def test_docs_api(self):
        with patch("pathlib.Path.exists", return_value=True):
            with patch("pathlib.Path.is_dir", return_value=True):
                # Fake rglob
                mock_file = MagicMock()
                mock_file.stem = "guide1"
                mock_file.relative_to.return_value = "guide1.md"
                with patch("pathlib.Path.rglob", return_value=[mock_file]):
                    res = self.client.get("/api/docs")
                    self.assertEqual(len(res.get_json()["docs"]), 1)

        # Read doc with traversal protection
        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [Path("/tmp/root/docs/g1.md"), Path("/tmp/root/docs")]
            with patch("pathlib.Path.exists", return_value=True):
                with patch("pathlib.Path.is_file", return_value=True):
                    with patch("builtins.open", mock_open(read_data="# Doc")):
                        res = self.client.get("/api/docs/g1.md")
                        self.assertEqual(res.get_json()["content"], "# Doc")

    def test_get_info(self):
        with patch("eval_runner.simulators.get_simulator_registry", return_value=[1,2,3]):
             res = self.client.get("/api/info")
             data = res.get_json()
             self.assertEqual(data["world_shims"], 3)
             self.assertIn("v1.2.0-stable", data["version"])

    def test_register_core_routes(self):
        # Line 76-161
        nav = []
        from eval_runner.console.routes import register_core_routes
        with patch("eval_runner.config.ENABLE_DEMO", True):
             register_core_routes(self.app, nav)
             ids = [item["id"] for item in nav]
             self.assertIn("dashboard", ids)
             self.assertIn("loan_demo", ids)

    @patch("eval_runner.config.RUN_LOG_DIR", Path("/tmp/runs"))
    def test_list_runs_filtering(self):
        # Line 207-219: matching/non-matching queries
        log_content = '{"event": "run_start", "run_id": "match", "scenario": "Test", "timestamp": "now"}\n'
        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=log_content)):
                # Match
                res = self.client.get("/api/runs?q=match")
                self.assertEqual(len(res.get_json()["runs"]), 1) 
                # Non-match
                res = self.client.get("/api/runs?q=nomatch")
                self.assertEqual(len(res.get_json()["runs"]), 0)

    @patch("eval_runner.loader.load_scenario", side_effect=Exception("Load error"))
    def test_evaluate_scenario_error(self, mock_load):
        # Line 280-281
        with patch("pathlib.Path.exists", return_value=True):
             res = self.client.post("/api/evaluate", json={"path": "existing.json"})
             self.assertEqual(res.status_code, 500)
             self.assertIn("Load error", res.get_json()["error"])

    def test_save_scenario_validation_errors(self):
        # Line 291-296
        # Missing ID
        res = self.client.post("/api/scenarios", json={})
        self.assertEqual(res.status_code, 400)
        # Empty ID after stripping
        res = self.client.post("/api/scenarios", json={"scenario_id": " "})
        self.assertEqual(res.status_code, 400)

    def test_debugger_state_store_variants(self):
        # Line 384-396
        class MockE:
            def __init__(self, n, d): self.name, self.data = n, d
        DebuggerStateStore.handle_event(MockE("turn_start", {"turn_idx": 5, "agent_name": "A1"}))
        latest = DebuggerStateStore.get_latest()["summary"]
        self.assertIn("Turn 5", latest["message"])

        DebuggerStateStore.handle_event(MockE("tool_call", {"tool": "ls", "arguments": {}}))
        latest = DebuggerStateStore.get_latest()["summary"]
        self.assertEqual(latest["last_tool"], "ls")

        DebuggerStateStore.handle_event(MockE("run_end", {"status": "success"}))
        latest = DebuggerStateStore.get_latest()["summary"]
        self.assertIn("success", latest["message"])

    def test_get_debugger_state_failures(self):
        # Line 488-497 (Missing trace)
        with patch("pathlib.Path.exists", return_value=False):
             res = self.client.get("/api/debugger/state?run_id=missing")
             self.assertEqual(res.status_code, 404)
        
        # Line 542-557 (Read Error)
        with patch("pathlib.Path.exists", return_value=True):
             with patch("builtins.open", side_effect=Exception("Read Boom")):
                  res = self.client.get("/api/debugger/state?run_id=error")
                  self.assertEqual(res.status_code, 500)

    def test_read_doc_unauthorized(self):
        # Line 610: unauthorized path
        with patch("pathlib.Path.resolve") as mock_resolve:
            mock_resolve.side_effect = [Path("/etc/passwd"), Path("/tmp/root/docs")]
            res = self.client.get("/api/docs/../../../etc/passwd")
            self.assertEqual(res.status_code, 403)
        
    @patch("eval_runner.catalog.ScenarioCatalog.build_index", side_effect=Exception("Refresh error"))
    def test_refresh_index_error(self, mock_build):
        # Line 685-686
        res = self.client.post("/api/scenarios/refresh")
        self.assertEqual(res.status_code, 500)
        self.assertIn("Refresh error", res.get_json()["error"])

    def test_get_debugger_state_demo_memory_fallback(self):
        # Line 472-485
        from eval_runner.console.demo_traces import DEMO_IDS
        d_id = DEMO_IDS[0]
        # Simulate disk failure (mkdir fails)
        with patch("pathlib.Path.exists", return_value=False):
            with patch("pathlib.Path.mkdir", side_effect=Exception("Disk Full")):
                res = self.client.get(f"/api/debugger/state?run_id={d_id}")
                self.assertEqual(res.status_code, 200)
                self.assertIn("memory (disk write failed)", res.get_json()["message"])

    def test_get_info_multi_provider(self):
        # Line 639-653
        providers = [
            ("http://generativelanguage.googleapis.com", "google", {"GOOGLE_API_KEY": "k"}),
            ("http://api.anthropic.com", "anthropic", {"ANTHROPIC_API_KEY": "k"}),
            ("http://api.openai.com", "openai", {"OPENAI_API_KEY": "k"}),
            ("http://localhost:11434", "ollama", {}),
            ("http://localhost:5001", "local", {})
        ]
        for url, expected_p, keys in providers:
            with patch("eval_runner.config.AGENT_API_URLS", [url]):
                with patch("eval_runner.config.GOOGLE_API_KEY", keys.get("GOOGLE_API_KEY")), \
                     patch("eval_runner.config.ANTHROPIC_API_KEY", keys.get("ANTHROPIC_API_KEY")), \
                     patch("eval_runner.config.OPENAI_API_KEY", keys.get("OPENAI_API_KEY")):
                    res = self.client.get("/api/info")
                    agent = res.get_json()["agents"][0]
                    self.assertEqual(agent["provider"], expected_p)

if __name__ == '__main__':
    unittest.main()
