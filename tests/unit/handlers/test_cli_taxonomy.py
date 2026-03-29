import pytest
import json
from unittest.mock import MagicMock, patch
from pathlib import Path
from eval_runner.handlers import scenarios, analysis

@pytest.fixture
def mock_args():
    args = MagicMock()
    args.scenario_path = "dummy.json"
    args.query = "test"
    return args

def test_handle_taxonomy(capsys):
    """Verifies 'taxonomy' command outputs current AES categories."""
    args = MagicMock()
    analysis.handle_taxonomy(args)
    out, _ = capsys.readouterr()
    assert "AGENT-EVAL FAILURE TAXONOMY" in out

def test_handle_inspect_success(tmp_path, capsys):
    """Verifies scenario inspector correctly extracts AES metadata. Forensic: v1.2 Sync."""
    scen_path = tmp_path / "inspect_me.json"
    scen_data = {
        "aes_version": 1.2,
        "metadata": {
            "name": "Inspection Test",
            "compliance_level": "Standard"
        },
        "industry": "finance",
        "description": "Verify it prints everything.",
        "workflow": {
            "nodes": [{"id": "t1", "task_description": "task"}],
            "edges": []
        }
    }
    scen_path.write_text(json.dumps(scen_data))
    
    args = MagicMock()
    args.scenario_path = str(scen_path)
    
    scenarios.handle_inspect(args)
    out, _ = capsys.readouterr()
    
    # Forensic: Inspector prints 'SCENARIO INSPECTOR' header
    assert "SCENARIO INSPECTOR" in out
    assert "Inspection Test" in out

def test_handle_inspect_failure(capsys):
    """Verifies inspector handles missing files gracefully. Forensic: Direct handler call."""
    args = MagicMock()
    args.scenario_path = "non_existent.json"
    scenarios.handle_inspect(args)
    out, _ = capsys.readouterr()
    assert "[ERROR] Scenario file not found" in out

@patch("eval_runner.handlers.scenarios.catalog.ScenarioCatalog.search")
def test_handle_catalog_search(mock_search, capsys):
    """Verifies catalog search command. Forensic: Correct patch target."""
    mock_search.return_value = [{"id": "s1", "title": "Scen 1"}]
    args = MagicMock(query="query")
    scenarios.handle_catalog_search(args)
    out, _ = capsys.readouterr()
    assert "s1: Scen 1" in out
