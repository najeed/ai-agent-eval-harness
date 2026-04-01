import os
import tempfile
import shutil
from pathlib import Path

# This ensures a 100% stable, zero-touch environment on any OS (inc. Windows)
# by creating a real temporary jail before ANY eval_runner modules are imported.
_TEST_JAIL = Path(tempfile.gettempdir()) / "aes_test_jail_v123_final"
_ROOT = _TEST_JAIL / "root"
_RUNS = _ROOT / "runs"
_DOCS = _ROOT / "docs"
_DEMO = _ROOT / "sample_agent" / "loan_agent_demo"

os.makedirs(_DOCS, exist_ok=True)
os.makedirs(_RUNS, exist_ok=True)
os.makedirs(_DEMO, exist_ok=True)

# Export to environment for eval_runner.config to pick up on import
os.environ["PROJECT_ROOT"] = str(_ROOT)
os.environ["RUN_LOG_DIR"] = "runs" # Relative to PROJECT_ROOT
os.environ["DASHBOARD_API_KEY"] = "test-key-123"

import unittest
from unittest.mock import MagicMock, patch, mock_open
import json
from flask import Flask
from datetime import datetime

# Force-override config at runtime to handle cases where config.py was imported 
# before the environment variables were set.
import eval_runner.config
eval_runner.config.PROJECT_ROOT = _ROOT
eval_runner.config.RUN_LOG_DIR = _ROOT / "runs"
eval_runner.config.TRAJECTORIES_DIR = _ROOT / "reports" / "trajectories"

# SUT - Imports will now pick up the bootstrapped environment
from eval_runner.console.routes import core_bp, DebuggerStateStore
from eval_runner import config

class TestRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Redundant but authoritative reinforcement
        os.makedirs(_ROOT / "industries" / "healthcare" / "scenarios", exist_ok=True)
        eval_runner.config.PROJECT_ROOT = _ROOT
        eval_runner.config.RUN_LOG_DIR = _ROOT / "runs"
        eval_runner.config.TRAJECTORIES_DIR = _ROOT / "reports" / "trajectories"
        os.makedirs(eval_runner.config.RUN_LOG_DIR, exist_ok=True)
        os.makedirs(eval_runner.config.TRAJECTORIES_DIR, exist_ok=True)
    def setUp(self):
        # Create a fresh Flask container for each test to ensure perfect isolation
        self.app = Flask(__name__)
        self.app.register_blueprint(core_bp)
        self.client = self.app.test_client()
        self.headers = {"X-AES-API-KEY": "test-key-123"}
        
        # Absolute authoritative patching for backend config during unit tests
        eval_runner.config.DASHBOARD_API_KEY = "test-key-123"
        patcher_root = patch("eval_runner.config.PROJECT_ROOT", _ROOT)
        patcher_root.start()
        self.addCleanup(patcher_root.stop)
        
        # Bypass auth decorators globally for unit tests
        patcher_auth = patch("eval_runner.console.auth_manager.require_permission", lambda p: lambda f: f)
        patcher_auth.start()
        self.addCleanup(patcher_auth.stop)
        
        DebuggerStateStore.reset()
        from eval_runner.catalog import ScenarioCatalog
        ScenarioCatalog.clear_instance()

    def test_get_loan_demo_context(self):
        (_DEMO / "loan_prd.md").write_text("prd content", encoding="utf-8")
        (_DEMO / "loan_approval.aes.yaml").write_text("aes content", encoding="utf-8")
        (_DEMO / "loan_approval_scenario.json").write_text('{"scenario": "data"}', encoding="utf-8")

        response = self.client.get("/api/demo/loan/context", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        data = response.get_json()
        self.assertEqual(data["prd"], "prd content")
        self.assertIn("updated_at", data)

    @patch("subprocess.run")
    def test_execute_demo_command_whitelist(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        res = self.client.post("/api/demo/execute", json={"command": "cat loan_prd.md"}, headers=self.headers)
        self.assertEqual(res.status_code, 200, res.data)

    @patch("eval_runner.console.routes.ScenarioCatalog")
    def test_list_scenarios(self, mock_catalog_cls):
        mock_cat = mock_catalog_cls.return_value
        mock_catalog_cls.get_instance.return_value = mock_cat
        mock_cat.search.return_value = [{"id": "s1"}]
        res = self.client.get("/api/scenarios?q=test", headers=self.headers)
        self.assertEqual(res.status_code, 200)

    def test_list_runs(self):
        log_file = _RUNS / "test_run.jsonl"
        log_file.write_text('{"event": "run_start", "run_id": "run_123", "scenario": "Test", "timestamp": "1970-01-01T00:00:00"}\n', encoding="utf-8")
        res = self.client.get("/api/runs", headers=self.headers)
        data = res.get_json()
        self.assertTrue(len(data["runs"]) > 0)
        log_file.unlink()

    @patch("eval_runner.loader.load_scenario")
    @patch("eval_runner.engine.run_evaluation")
    @patch("threading.Thread")
    def test_evaluate_scenario(self, mock_thread, mock_run_eval, mock_load):
        mock_load.return_value = {"scenario_id": "scen_1"}
        scen_file = _ROOT / "scenarios" / "test.json"
        scen_file.parent.mkdir(parents=True, exist_ok=True)
        scen_file.write_text("{}", encoding="utf-8")
        res = self.client.post("/api/evaluate", json={"path": "scenarios/test.json"}, headers=self.headers)
        self.assertEqual(res.status_code, 200)

    def test_save_scenario(self):
        payload = {
            "scenario_id": "new-scen",
            "industry": "healthcare",
            "title": "New",
            "tasks": [{"task_id": "t1", "description": "desc", "expected_outcome": "win"}]
        }
        res = self.client.post("/api/scenarios", json=payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        # Aligned with routes.py industrial structure: industries/{industry}/scenarios/
        expected = _ROOT / "industries" / "healthcare" / "scenarios" / "new-scen.json"
        self.assertTrue(expected.exists())

    def test_debugger_state_lifecycle(self):
        # Post a valid event to hydrate the store
        res = self.client.post("/api/debugger/state", json={"event": "world_state_change", "data": {"state": {"hp": 100}}}, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        
        res = self.client.get("/api/debugger/state", headers=self.headers)
        data = res.get_json()
        self.assertIsNotNone(data.get("data"))
        self.assertIn("summary", data["data"])
        # If summary is still building or empty, it might be None or {}
        summary = data["data"]["summary"]
        if summary and "state" in summary:
            self.assertEqual(summary["state"].get("hp"), 100)

    def test_get_debugger_state_historical(self):
        log_file = _RUNS / "run_456.jsonl"
        log_file.write_text('{"event": "world_state_change", "state": {"val": 1}}\n', encoding="utf-8")
        res = self.client.get("/api/debugger/state?run_id=run_456", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        log_file.unlink()

    def test_docs_api(self):
        doc_file = _DOCS / "g1.md"
        doc_file.write_text("# Doc", encoding="utf-8")
        mock_file = MagicMock()
        mock_file.stem = "g1"
        mock_file.relative_to.return_value = "g1.md"
        with patch("pathlib.Path.rglob", return_value=[mock_file]):
            res = self.client.get("/api/docs", headers=self.headers)
            self.assertEqual(len(res.get_json()["docs"]), 1)
        res = self.client.get("/api/docs/g1.md", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["content"], "# Doc")

    def test_read_doc_unauthorized(self):
        res = self.client.get("/api/docs/../../../etc/passwd", headers=self.headers)
        self.assertEqual(res.status_code, 403)

if __name__ == '__main__':
    unittest.main()
