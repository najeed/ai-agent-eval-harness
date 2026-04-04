import pytest
import os
import json
from pathlib import Path
from eval_runner.console.app import create_app
from eval_runner.console.auth_manager import Permission
from eval_runner import config

def test_scenario_index_hydration_on_load(tmp_path):
    """Verify that the scenario index is properly constructed on server loading and hydrates the dashboard."""
    
    # 1. Setup mock industries/scenarios
    industries_dir = tmp_path / "industries"
    finance_dir = industries_dir / "finance" / "scenarios"
    finance_dir.mkdir(parents=True)
    
    scenario_path = finance_dir / "test_hydrated.json"
    scenario_data = {
        "aes_version": 1.2,
        "metadata": {"id": "test_hydrated", "name": "Hydrated Scenario", "industry": "finance", "compliance_level": "Standard"},
        "workflow": {"steps": []}
    }
    scenario_path.write_text(json.dumps(scenario_data), encoding="utf-8")
    
    # 2. Mock config to use the tmp_path
    with patch("eval_runner.config.PROJECT_ROOT", tmp_path):
        with patch("eval_runner.config.DASHBOARD_API_KEY", "test-key"):
            # Ensure the catalog singleton is reset for the test
            from eval_runner.catalog import ScenarioCatalog
            ScenarioCatalog._instance = None
            
            # 3. Create the app (this should trigger hydration via create_app -> load_index)
            app = create_app()
            client = app.test_client()
            
            # 4. Authenticate
            with client.session_transaction() as sess:
                sess["user"] = {"permissions": [Permission.SCENARIOS_READ]}
            
            # 5. Verify the /api/scenarios endpoint returns the hydrated scenario
            resp = client.get("/api/scenarios")
            assert resp.status_code == 200
            data = resp.get_json()
            
            # Depending on how many scenarios are in the whole project, this might vary.
            # But the 'test_hydrated' should be in the list.
            found = any(s["id"] == "test_hydrated" for s in data["scenarios"])
            assert found is True
            assert data["total_count"] >= 1

from unittest.mock import patch
