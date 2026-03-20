import pytest
import json
from pathlib import Path
from eval_runner.linter import ScenarioLinter


def test_linter_basic(tmp_path):
    linter = ScenarioLinter()

    # 1. Test Valid Scenario — must include all mandatory top-level fields per current linter
    valid_scen = tmp_path / "valid.json"
    with open(valid_scen, "w") as f:
        json.dump(
            {
                "scenario_id": "v1",
                "title": "Valid Scenario",
                "description": "A valid test scenario",
                "use_case": "Customer Support",
                "core_function": "Query Handling",
                "industry": "tech",
                "complexity_level": "medium",
                "tasks": [
                    {
                        "task_id": "t1",
                        "description": "Do thing",
                        "expected_outcome": "Thing done",
                        "success_criteria": [
                            {"metric": "tool_call_correctness", "threshold": 1.0}
                        ],
                    }
                ],
            },
            f,
        )

    res = linter.lint(str(valid_scen))
    assert (
        res["status"] == "pass"
    ), f"Expected pass, got {res['status']}. Errors: {res['errors']}, Warnings: {res['warnings']}"
    assert (
        res["score"] == 100
    ), f"Expected score 100, got {res['score']}. Errors: {res['errors']}, Warnings: {res['warnings']}"

    # 2. Test Warning — scenario missing complexity_level triggers warning but no errors
    warn_scen = tmp_path / "warn.json"
    with open(warn_scen, "w") as f:
        json.dump(
            {
                "scenario_id": "w1",
                "title": "Warning Scenario",
                "description": "A warning test scenario",
                "use_case": "Customer Support",
                "core_function": "Query Handling",
                "industry": "tech",
                # Missing complexity_level → should trigger a warning
                "tasks": [
                    {
                        "task_id": "t1",
                        "description": "Do thing",
                        "expected_outcome": "Done",
                        "success_criteria": [
                            {"metric": "policy_compliance", "threshold": 1.0}
                        ],
                    }
                ],
            },
            f,
        )

    res = linter.lint(str(warn_scen))
    assert (
        res["status"] == "warning"
    ), f"Expected warning, got {res['status']}. Errors: {res['errors']}, Warnings: {res['warnings']}"
    assert res["score"] < 100

    # 3. Test Fail — missing 'tasks' key entirely
    fail_scen = tmp_path / "fail.json"
    with open(fail_scen, "w") as f:
        json.dump(
            {
                "scenario_id": "f1",
                "title": "Fail Scenario",
                "description": "fail",
                "use_case": "X",
                "core_function": "Y",
                "industry": "Z",
            },
            f,
        )

    res = linter.lint(str(fail_scen))
    assert (
        res["status"] == "fail"
    ), f"Expected fail, got {res['status']}. Errors: {res['errors']}"
    assert any(
        "tasks" in e.lower() for e in res["errors"]
    ), f"Expected error about tasks, got: {res['errors']}"


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
