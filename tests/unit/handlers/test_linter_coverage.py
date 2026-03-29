# tests/test_linter_coverage.py
import pytest
import json
from pathlib import Path
from eval_runner.linter import ScenarioLinter, run_lint

def test_linter_registry_file(tmp_path):
    """Test that index.json is treated as a registry and skipped."""
    linter = ScenarioLinter()
    p = tmp_path / "index.json"
    p.write_text("[]") # Registry is a list
    
    res = linter.lint(str(p))
    assert res["tier"] == "REGISTRY"
    assert res["status"] == "pass"
    assert "Registry file ignored" in res["warnings"][0]

def test_linter_invalid_list_not_registry(tmp_path):
    """Test that a list in a non-registry file is an error."""
    linter = ScenarioLinter()
    p = tmp_path / "scenario.json"
    p.write_text("[]")
    
    res = linter.lint(str(p))
    assert res["status"] == "fail"
    assert "must be a JSON object" in res["errors"][0]

def test_linter_invalid_type(tmp_path):
    """Test that non-dict/list JSON is an error."""
    linter = ScenarioLinter()
    p = tmp_path / "string.json"
    p.write_text("\"just a string\"")
    
    res = linter.lint(str(p))
    assert res["status"] == "fail"
    assert "found str" in res["errors"][0]

def test_linter_v1_2_missing_workflow(tmp_path):
    """Test v1.2 scenario missing workflow block."""
    linter = ScenarioLinter()
    p = tmp_path / "v12_bad.json"
    p.write_text(json.dumps({
        "aes_version": 1.2,
        "description": "test",
        "industry": "finance"
    }))
    
    res = linter.lint(str(p))
    assert res["status"] == "fail"
    assert "Missing or invalid 'workflow' block (Standard requires nodes/edges)" in res["errors"]

def test_linter_v1_2_invalid_nodes(tmp_path):
    """Test v1.2 scenario with invalid nodes."""
    linter = ScenarioLinter()
    p = tmp_path / "v12_nodes.json"
    p.write_text(json.dumps({
        "aes_version": 1.2,
        "workflow": {"nodes": "not-a-list"},
        "description": "test",
        "industry": "finance"
    }))
    
    res = linter.lint(str(p))
    assert "Workflow missing 'nodes' array" in res["errors"]

def test_linter_v1_2_incomplete_node(tmp_path):
    """Test v1.2 node missing fields."""
    linter = ScenarioLinter()
    p = tmp_path / "v12_node_inc.json"
    p.write_text(json.dumps({
        "aes_version": 1.2,
        "workflow": {"nodes": [{"id": "1"}]}, # missing task_description
        "description": "test",
        "industry": "finance"
    }))
    
    res = linter.lint(str(p))
    assert any("missing 'id' or 'task_description'" in e for e in res["errors"])

def test_linter_duplicates_exception(tmp_path, monkeypatch):
    """Test find_duplicates handles I/O errors gracefully."""
    linter = ScenarioLinter()
    p = tmp_path / "bad.json"
    p.write_text("invalid json{")
    
    # find_duplicates should skip files it can't parse via Exception catch
    dupes = linter.find_duplicates(str(tmp_path))
    assert len(dupes) == 0

def test_linter_duplicates_v1_2(tmp_path):
    """Test find_duplicates with v1.2 signatures."""
    linter = ScenarioLinter()
    s1 = tmp_path / "s1.json"
    s2 = tmp_path / "s2.json"
    
    content = {
        "aes_version": 1.2,
        "workflow": {"nodes": [{"id": "n1", "task_description": "do X"}]},
        "description": "d",
        "industry": "i"
    }
    s1.write_text(json.dumps(content))
    s2.write_text(json.dumps(content))
    
    dupes = linter.find_duplicates(str(tmp_path))
    assert len(dupes) == 1
    assert "s1.json" in str(dupes[0].values())
    assert "s2.json" in str(dupes[0].values())

def test_run_lint_cli_directory(tmp_path, capsys):
    """Test run_lint CLI handler with a directory."""
    p = tmp_path / "test.json"
    p.write_text(json.dumps({
        "scenario_id": "test", 
        "aes_version": 1.2, 
        "description": "test",
        "industry": "finance",
        "workflow": {
            "nodes": [{"id": "t1", "task_description": "task"}],
            "edges": []
        }
    }))
    
    run_lint(str(tmp_path))
    captured = capsys.readouterr()
    assert "Linting complete" in captured.out
    assert "test.json" in captured.out
