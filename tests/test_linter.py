import pytest
import json
from pathlib import Path
from eval_runner.linter import ScenarioLinter

def test_linter_basic(tmp_path):
    linter = ScenarioLinter()
    
    # 1. Test Valid Scenario
    valid_scen = tmp_path / "valid.json"
    with open(valid_scen, "w") as f:
        json.dump({
            "scenario_id": "v1",
            "title": "Valid",
            "metadata": {"industry": "tech", "difficulty": "1"},
            "tasks": [{"task": "do thing", "tools": ["tool1"]}]
        }, f)
        
    res = linter.lint(str(valid_scen))
    assert res["status"] == "pass"
    assert res["score"] == 100
    
    # 2. Test Warning (Missing Metadata)
    warn_scen = tmp_path / "warn.json"
    with open(warn_scen, "w") as f:
        json.dump({
            "scenario_id": "w1",
            "tasks": [{"task": "do thing"}]
        }, f)
        
    res = linter.lint(str(warn_scen))
    assert res["status"] == "warning"
    assert res["score"] < 100
    assert any("Missing recommended metadata" in w for w in res["warnings"])

    # 3. Test Fail (No Tasks)
    fail_scen = tmp_path / "fail.json"
    with open(fail_scen, "w") as f:
        json.dump({"scenario_id": "f1"}, f)
        
    res = linter.lint(str(fail_scen))
    assert res["status"] == "fail"
    assert any("Scenario has no 'tasks'" in e for e in res["errors"])

def test_linter_duplicates(tmp_path):
    linter = ScenarioLinter()
    
    s1 = tmp_path / "s1.json"
    s2 = tmp_path / "s2.json"
    
    tasks = [{"task": "same task"}]
    
    with open(s1, "w") as f:
        json.dump({"tasks": tasks}, f)
    with open(s2, "w") as f:
        json.dump({"tasks": tasks}, f)
        
    dupes = linter.find_duplicates(str(tmp_path))
    assert len(dupes) == 1
    assert "s1.json" in dupes[0]["original"] or "s1.json" in dupes[0]["duplicate"]
