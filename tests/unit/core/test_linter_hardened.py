import json

import pytest
import yaml

from eval_runner.linter import ScenarioLinter, run_lint


@pytest.fixture
def linter():
    return ScenarioLinter()


def test_linter_get_quality_tier(linter):
    assert linter.get_quality_tier(95) == "GOLD"
    assert linter.get_quality_tier(75) == "SILVER"
    assert linter.get_quality_tier(55) == "BRONZE"
    assert linter.get_quality_tier(10) == "UNRANKED"


def test_linter_file_not_found(linter):
    res = linter.lint("non_existent.json")
    assert res["status"] == "fail"
    assert "File not found" in res["errors"]


def test_linter_invalid_json(linter, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{invalid")
    res = linter.lint(str(p))
    assert res["status"] == "fail"
    assert "Invalid JSON" in res["errors"][0]


def test_linter_registry_ignore(linter, tmp_path):
    p = tmp_path / "index.json"
    p.write_text("[]")
    res = linter.lint(str(p))
    assert res["status"] == "pass"
    assert res["tier"] == "REGISTRY"


def test_linter_list_error(linter, tmp_path):
    p = tmp_path / "scen.json"
    p.write_text("[]")
    res = linter.lint(str(p))
    assert res["status"] == "fail"
    assert "Scenario file must be a JSON object" in res["errors"][0]


def test_linter_basic_success(linter, tmp_path):
    p = tmp_path / "good.json"
    data = {
        "aes_version": 1.4,
        "industry": "finance",
        "metadata": {"id": "scen-1", "attribution": "test", "version": "1.0"},
        "workflow": {"nodes": [{"id": "n1", "task_description": "do thing"}], "edges": []},
        "complexity_level": "low",
    }
    p.write_text(json.dumps(data))
    res = linter.lint(str(p))
    assert res["status"] == "pass"
    assert res["score"] == 100
    assert res["tier"] == "GOLD"


def test_linter_weak_score(linter, tmp_path):
    p = tmp_path / "weak.json"
    data = {
        "aes_version": 1.1,  # Error -50
        "industry": "finance",
        "metadata": {"id": "s1"},  # Warning -15 (attribution/version)
        "workflow": {"nodes": []},  # Warning -20
    }
    p.write_text(json.dumps(data))
    res = linter.lint(str(p))
    assert res["status"] == "fail"
    assert res["score"] < 50
    assert "aes_version" in str(res["errors"])


def test_linter_workflow_errors(linter, tmp_path):
    p = tmp_path / "bad_wf.json"
    data = {
        "aes_version": 1.4,
        "industry": "test",
        "metadata": {"id": "s1"},
        "workflow": {
            "nodes": [{"id": "n1", "task_description": "ok"}],
            "edges": [{"from": "n1", "to": "ghost"}],  # Invalid edge
        },
    }
    p.write_text(json.dumps(data))
    res = linter.lint(str(p))
    assert res["status"] == "fail"
    assert "references invalid node" in str(res["errors"])


def test_linter_find_duplicates(linter, tmp_path):
    d1 = tmp_path / "d1"
    d1.mkdir()
    p1 = d1 / "s1.json"
    p2 = d1 / "s2.json"

    scen = {"workflow": {"nodes": [{"id": "n1", "task_description": "dup"}]}}
    content = json.dumps(scen)
    p1.write_text(content)
    p2.write_text(content)

    dups = linter.find_duplicates(str(d1))
    assert len(dups) == 1
    assert "s1.json" in str(dups[0].values())
    assert "s2.json" in str(dups[0].values())


def test_linter_yaml_support(linter, tmp_path):
    p = tmp_path / "scen.yaml"
    data = {
        "aes_version": 1.4,
        "industry": "test",
        "metadata": {"id": "y1"},
        "workflow": {"nodes": []},
    }
    p.write_text(yaml.dump(data))
    res = linter.lint(str(p))
    assert res["status"] in ["pass", "warning"]
    assert res["aes_version"] == 1.4


def test_run_lint_cli_file(tmp_path, capsys):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"aes_version": 1.4}))
    run_lint(str(p))
    captured = capsys.readouterr()
    assert '"aes_version": 1.4' in captured.out


def test_run_lint_cli_dir(tmp_path, capsys):
    p = tmp_path / "scen.json"
    p.write_text(
        json.dumps(
            {
                "aes_version": 1.4,
                "industry": "t",
                "metadata": {"id": "1"},
                "workflow": {"nodes": []},
            }
        )
    )
    run_lint(str(tmp_path))
    captured = capsys.readouterr()
    assert "scen.json" in captured.out
    assert "Linting complete" in captured.out
