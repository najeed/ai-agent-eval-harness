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


def test_linter_non_dict_non_list_top_level(linter, tmp_path):
    """A file whose root is a scalar (not dict/list) should fail with type error."""
    p = tmp_path / "scalar.json"
    p.write_text("42")
    res = linter.lint(str(p))
    assert res["status"] == "fail"
    assert any("JSON object" in e for e in res["errors"])
    assert res["tier"] == "UNRANKED"


def test_linter_non_dict_metadata(linter, tmp_path):
    """Metadata that is not a dict produces an error."""
    p = tmp_path / "badmeta.json"
    data = {
        "aes_version": 1.4,
        "industry": "test",
        "metadata": "just-a-string",
        "workflow": {"nodes": [{"id": "n1", "task_description": "ok"}], "edges": []},
        "complexity_level": "low",
    }
    p.write_text(json.dumps(data))
    res = linter.lint(str(p))
    assert res["status"] == "fail"
    assert any("Metadata must be a JSON object" in e for e in res["errors"])


def test_linter_workflow_missing_nodes_array(linter, tmp_path):
    """A workflow dict that has no 'nodes' key (or non-list) should fail."""
    p = tmp_path / "nonodes.json"
    data = {
        "aes_version": 1.4,
        "industry": "test",
        "metadata": {"id": "s1"},
        "workflow": {"edges": []},  # no 'nodes' key
        "complexity_level": "low",
    }
    p.write_text(json.dumps(data))
    res = linter.lint(str(p))
    assert res["status"] == "fail"
    assert any("nodes" in e for e in res["errors"])


def test_linter_node_missing_id_or_task_description(linter, tmp_path):
    """A node without an id or task_description gets an error entry."""
    p = tmp_path / "badnode.json"
    data = {
        "aes_version": 1.4,
        "industry": "test",
        "metadata": {"id": "s1", "attribution": "a", "version": "1"},
        "workflow": {
            "nodes": [{"task_description": "missing id"}],  # no id
            "edges": [],
        },
        "complexity_level": "low",
    }
    p.write_text(json.dumps(data))
    res = linter.lint(str(p))
    assert res["status"] == "fail"
    assert any("missing 'id'" in e for e in res["errors"])


def test_linter_expected_outcome_not_a_list(linter, tmp_path):
    """expected_outcome that is not a list triggers an AES v1.4 violation error."""
    p = tmp_path / "badoutcome.json"
    data = {
        "aes_version": 1.4,
        "industry": "test",
        "metadata": {"id": "s1", "attribution": "a", "version": "1"},
        "workflow": {
            "nodes": [
                {
                    "id": "n1",
                    "task_description": "ok",
                    "expected_outcome": "should-be-a-list",  # string, not list
                }
            ],
            "edges": [],
        },
        "complexity_level": "low",
    }
    p.write_text(json.dumps(data))
    res = linter.lint(str(p))
    assert res["status"] == "fail"
    assert any("must be an array" in e for e in res["errors"])


def test_linter_expected_outcome_empty_list(linter, tmp_path):
    """An empty expected_outcome list triggers a warning (score deduction)."""
    p = tmp_path / "emptyoutcome.json"
    data = {
        "aes_version": 1.4,
        "industry": "test",
        "metadata": {"id": "s1", "attribution": "a", "version": "1"},
        "workflow": {
            "nodes": [
                {
                    "id": "n1",
                    "task_description": "ok",
                    "expected_outcome": [],  # empty
                }
            ],
            "edges": [],
        },
        "complexity_level": "low",
    }
    p.write_text(json.dumps(data))
    res = linter.lint(str(p))
    assert any("empty expected_outcome" in w for w in res["warnings"])
    assert res["score"] < 100


def test_linter_edges_not_a_list(linter, tmp_path):
    """edges being a non-list value triggers an error."""
    p = tmp_path / "badedges.json"
    data = {
        "aes_version": 1.4,
        "industry": "test",
        "metadata": {"id": "s1", "attribution": "a", "version": "1"},
        "workflow": {
            "nodes": [{"id": "n1", "task_description": "ok"}],
            "edges": "not-a-list",
        },
        "complexity_level": "low",
    }
    p.write_text(json.dumps(data))
    res = linter.lint(str(p))
    assert any("edges" in e for e in res["errors"])


def test_linter_edge_missing_from_or_to(linter, tmp_path):
    """An edge dict with missing 'from' or 'to' keys produces an error."""
    p = tmp_path / "missingedge.json"
    data = {
        "aes_version": 1.4,
        "industry": "test",
        "metadata": {"id": "s1", "attribution": "a", "version": "1"},
        "workflow": {
            "nodes": [{"id": "n1", "task_description": "ok"}],
            "edges": [{"from": "n1"}],  # missing 'to'
        },
        "complexity_level": "low",
    }
    p.write_text(json.dumps(data))
    res = linter.lint(str(p))
    assert any("missing 'from' or 'to'" in e for e in res["errors"])


def test_linter_find_duplicates_skips_invalid_json(linter, tmp_path):
    """find_duplicates silently skips files that cannot be parsed as JSON."""
    p_good = tmp_path / "good.json"
    p_bad = tmp_path / "bad.json"
    p_good.write_text(json.dumps({"workflow": {"nodes": [{"id": "n1"}]}}))
    p_bad.write_text("{corrupted")

    dups = linter.find_duplicates(str(tmp_path))
    # No duplicates; bad file was skipped without raising
    assert isinstance(dups, list)


def test_run_lint_dir_with_failing_scenario(tmp_path, capsys):
    """Directory lint with a failing file prints the ❌ prefix."""
    p = tmp_path / "fail.json"
    # A JSON list in a non-index.json file triggers a fail
    p.write_text("[]")
    run_lint(str(tmp_path))
    captured = capsys.readouterr()
    assert "❌" in captured.out or "fail.json" in captured.out
    assert "Linting complete" in captured.out
