import pytest
import os
import json
import time
from pathlib import Path
from eval_runner.console.app import create_app
from eval_runner.console.auth_manager import Permission
from eval_runner import config
from unittest.mock import patch

def test_live_run_refresh_and_timestamps(tmp_path):
    """Verify that the reports list refreshes when a new eval is run and displays accurate timestamps."""
    
    # 1. Setup mock runs directory
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    
    with patch("eval_runner.config.PROJECT_ROOT", tmp_path), \
         patch("eval_runner.config.RUN_LOG_DIR", runs_dir), \
         patch("eval_runner.config.DASHBOARD_API_KEY", "test-key"):
        
        app = create_app()
        client = app.test_client()
        
        # Authenticate
        with client.session_transaction() as sess:
            sess["user"] = {"permissions": [Permission.RUNS_READ, Permission.SCENARIOS_READ]}
        
        # 2. Initially there should be no user runs (maybe just demo runs)
        resp = client.get("/api/runs")
        initial_data = resp.get_json()["runs"]
        user_runs_initial = [r for r in initial_data if not r.get("is_demo")]
        assert len(user_runs_initial) == 0
        
        # 3. Simulate a new run by writing to run.jsonl
        run_id = "test-live-run-123"
        timestamp = "2026-04-03T20:30:00.000Z"
        run_event = {
            "event": "run_start",
            "run_id": run_id,
            "scenario": "Live Refresh Scenario",
            "timestamp": timestamp
        }
        
        # Individual run file
        run_file = runs_dir / f"{run_id}.jsonl"
        run_file.write_text(json.dumps(run_event) + "\n", encoding="utf-8")
        
        # 4. Check the /api/runs endpoint again
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        data = resp.get_json()["runs"]
        
        user_runs = [r for r in data if r["run_id"] == run_id]
        assert len(user_runs) == 1
        assert user_runs[0]["run_id"] == run_id
        assert user_runs[0]["timestamp"] == timestamp
        # Ensure timestamp is correctly reflected in the list
        assert "2026-04-03" in user_runs[0]["timestamp"]
