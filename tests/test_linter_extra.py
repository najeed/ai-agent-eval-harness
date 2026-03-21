import pytest
import sys
import json
from pathlib import Path
from unittest.mock import patch
from eval_runner.linter import ScenarioLinter, run_lint

def test_linter_file_not_found(tmp_path):
    linter = ScenarioLinter()
    res = linter.lint(str(tmp_path / "ghost.json"))
    assert res["status"] == "fail"
    assert "File not found" in res["errors"][0]

def test_linter_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{bad", encoding="utf-8")
    linter = ScenarioLinter()
    res = linter.lint(str(p))
    assert res["status"] == "fail"
    assert "Invalid JSON" in res["errors"][0]
    assert res["score"] == 0

def test_linter_root_not_dict(tmp_path):
    p = tmp_path / "array.json"
    p.write_text('["hello"]', encoding="utf-8")
    linter = ScenarioLinter()
    res = linter.lint(str(p))
    assert res["status"] == "fail"
    assert "JSON object" in res["errors"][0]

def test_linter_missing_mandatory_and_complexity(tmp_path):
    p = tmp_path / "missing.json"
    p.write_text('{"scenario_id": "x"}', encoding="utf-8")
    linter = ScenarioLinter()
    res = linter.lint(str(p))
    assert res["status"] == "fail"
    # It misses multiple mandatory fields (title, desc, use_case, etc)
    assert any("Missing mandatory field" in e for e in res["errors"])
    assert any("Missing recommended field" in w for w in res["warnings"]) # complexity_level

def test_linter_tasks_validation(tmp_path):
    p = tmp_path / "tasks.json"
    data = {
        "scenario_id": "t1", "title": "t", "description": "d",
        "use_case": "u", "core_function": "c", "industry": "i",
        "complexity_level": "low",
        "tasks": [
            # Task missing expected_outcome and success_criteria
            {"task_id": "1", "description": "d"},
            # Valid task with tools dict
            {"task_id": "2", "description": "d", "expected_outcome": "o", "success_criteria": [], "tools": ["a", "b"]}
        ]
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    linter = ScenarioLinter()
    res = linter.lint(str(p))
    assert res["status"] == "fail"
    assert "Missing 'expected_outcome'" in res["errors"][0]
    assert res["complexity"]["suggested_tools"] == 2

def test_linter_zero_tasks(tmp_path):
    p = tmp_path / "zero.json"
    data = {
        "scenario_id": "t1", "title": "t", "description": "d",
        "use_case": "u", "core_function": "c", "industry": "i",
        "complexity_level": "low",
        "tasks": []
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    res = ScenarioLinter().lint(str(p))
    assert "0 tasks" in res["warnings"][0]

def test_linter_find_duplicates_exception(tmp_path):
    p1 = tmp_path / "bad.json"
    p1.write_text("{bad", encoding="utf-8")
    linter = ScenarioLinter()
    dupes = linter.find_duplicates(str(tmp_path))
    assert len(dupes) == 0

def test_run_lint_cli_directory_failure(tmp_path, capsys):
    # Setup a failing scenario inside a directory
    p = tmp_path / "fail.json"
    p.write_text('{"bad": 1}', encoding="utf-8")
    
    # We patch Path.is_file to be False so it assumes directory
    with patch("eval_runner.linter.Path.is_file", return_value=False):
        # We also need to patch the internal iter glob to just yield our file
        with patch("eval_runner.linter.Path.glob", return_value=[p]):
            run_lint(str(tmp_path))
            captured = capsys.readouterr()
            assert "failed." in captured.out
            assert "1 failed" in captured.out

def test_run_lint_cli_file(tmp_path, capsys):
    p = tmp_path / "single.json"
    p.write_text('{"bad": 1}', encoding="utf-8")
    run_lint(str(p))
    captured = capsys.readouterr()
    assert "status" in captured.out
