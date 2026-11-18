"""Acceptance fixture reports must reach the release gate's configured input."""

import json
from pathlib import Path

import pytest
import yaml

from tests.acceptance.conftest import acceptance_aggregator
from tests.acceptance.result import AcceptanceResult
from tools.ci.acceptance_gate import evaluate_summary


@pytest.mark.parametrize("destination", ["temporary", "relative", "absolute"])
def test_acceptance_fixture_publishes_gate_input(
    destination, tmp_path, tmp_path_factory, monkeypatch
):
    repo_root = tmp_path / "repository"
    repo_root.mkdir()
    monkeypatch.delenv("AGENTV_ACCEPTANCE_REPORT_DIR", raising=False)
    if destination == "relative":
        monkeypatch.setenv("AGENTV_ACCEPTANCE_REPORT_DIR", "reports/acceptance")
        reports = repo_root / "reports" / "acceptance"
    elif destination == "absolute":
        reports = tmp_path / "exported-reports"
        monkeypatch.setenv("AGENTV_ACCEPTANCE_REPORT_DIR", str(reports))
    else:
        reports = tmp_path / "temporary-reports"
        from unittest.mock import Mock

        tmp_path_factory = Mock()
        tmp_path_factory.mktemp.return_value = reports

    lifecycle = acceptance_aggregator.__wrapped__(repo_root, tmp_path_factory)
    aggregator = next(lifecycle)
    aggregator.add_result(
        AcceptanceResult.from_dict(
            {
                "case_id": "AT-REPORT",
                "category": "evidence",
                "accepted": True,
                "expected": {},
                "actual": {},
            }
        )
    )
    with pytest.raises(StopIteration):
        next(lifecycle)

    summary = json.loads((reports / "latest" / "acceptance-summary.json").read_text("utf-8"))
    assert summary["results"][0]["case_id"] == "AT-REPORT"
    assert (reports / "latest" / "acceptance-summary.md").is_file()
    assert evaluate_summary(summary, {"cases": ["AT-REPORT.yaml"]}).passed
    if destination == "temporary":
        assert not (repo_root / "reports").exists()


@pytest.mark.parametrize("workflow", ["acceptance.yml", "release.yml"])
def test_release_workflows_publish_acceptance_reports_for_gate(workflow):
    repository = Path(__file__).resolve().parents[3]
    document = yaml.safe_load((repository / ".github" / "workflows" / workflow).read_text("utf-8"))
    steps = document["jobs"][
        "acceptance-release" if workflow == "acceptance.yml" else "acceptance-release-gate"
    ]["steps"]
    corpus_step = next(
        step
        for step in steps
        if "pytest" in step.get("run", "")
        and (
            "test_acceptance_corpus.py" in step["run"] or "tests/acceptance tests/ui" in step["run"]
        )
    )
    report_dir = corpus_step["env"]["AGENTV_ACCEPTANCE_REPORT_DIR"]
    gate_step = next(step for step in steps if "acceptance_gate.py" in step.get("run", ""))
    assert f"--report-dir {report_dir}/latest" in gate_step["run"]
