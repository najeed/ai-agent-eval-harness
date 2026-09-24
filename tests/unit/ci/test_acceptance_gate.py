"""
tests/unit/ci/test_acceptance_gate.py
Comprehensive unit tests providing 100% line and branch coverage for tools/ci/acceptance_gate.py.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from tools.ci.acceptance_gate import GateDecision, evaluate_summary, main


def test_evaluate_summary_clean_pass():
    """Validates evaluate_summary on a fully compliant passing release suite."""
    summary = {
        "total_cases": 2,
        "results": [
            {"case_id": "AT-CASE-001", "accepted": True},
            {"case_id": "AT-CASE-002", "accepted": True},
        ],
    }
    suite = {
        "thresholds": {
            "allow_false_negatives": 0,
            "allow_false_positives": 0,
            "allow_security_failures": 0,
            "allow_evidence_failures": 0,
            "allow_execution_errors": 0,
        },
        "cases": [
            "tests/acceptance/corpus/AT-CASE-001.yaml",
            "tests/acceptance/corpus/AT-CASE-002.yaml",
        ],
    }

    decision = evaluate_summary(summary, suite)
    assert isinstance(decision, GateDecision)
    assert decision.passed is True
    assert decision.total_cases == 2
    assert decision.passed_cases == 2
    assert decision.failed_cases == 0
    assert decision.false_negatives == 0
    assert decision.false_positives == 0
    assert decision.security_failures == 0
    assert decision.evidence_failures == 0
    assert decision.execution_errors == 0
    assert decision.reasons == []


def test_evaluate_summary_empty_suite_and_mismatches():
    """Validates zero cases and claimed total mismatch."""
    summary_empty = {"total_cases": 5, "results": []}
    decision = evaluate_summary(summary_empty, None)
    assert decision.passed is False
    assert any("Summary integrity breach" in r for r in decision.reasons)
    assert any("Zero acceptance cases evaluated" in r for r in decision.reasons)


def test_evaluate_summary_membership_and_failure_types():
    """Validates detection of FN, FP, security, evidence, and execution failures."""
    summary = {
        "total_cases": 4,
        "results": [
            {
                "case_id": "AT-CASE-001",
                "accepted": False,
                "expected": {"policy": {"decision": "BLOCK"}},
                "actual": {"policy": {"decision": "ALLOW"}},
                "category": "security",
                "failures": ["Required evidence file missing: run.jsonl"],
            },
            {
                "case_id": "AT-CASE-002",
                "accepted": False,
                "expected": {"policy": {"decision": "ALLOW"}},
                "actual": {"policy": {"decision": "REJECT"}},
                "category": "functional",
                "failures": ["Expected execution_status COMPLETED, got FAILED"],
            },
        ],
    }
    suite = {
        "thresholds": {},
        "cases": [
            "tests/acceptance/corpus/AT-CASE-001.yaml",
            "tests/acceptance/corpus/AT-CASE-003.yaml",  # Mismatch: 003 missing, 002 unexpected
        ],
    }

    decision = evaluate_summary(summary, suite)
    assert decision.passed is False
    assert decision.failed_cases == 2
    assert decision.false_negatives == 1
    assert decision.false_positives == 1
    assert decision.security_failures == 1
    assert decision.evidence_failures == 1
    assert decision.execution_errors == 1
    assert any("Suite membership mismatch" in r for r in decision.reasons)
    assert any("False Negative(s) detected" in r for r in decision.reasons)
    assert any("False Positive(s) detected" in r for r in decision.reasons)
    assert any("Security Failure(s) detected" in r for r in decision.reasons)
    assert any("Evidence Integrity Failure(s) detected" in r for r in decision.reasons)
    assert any("Execution Error(s) detected" in r for r in decision.reasons)


def test_main_missing_summary(tmp_path):
    """CLI fails when acceptance-summary.json is missing."""
    empty_dir = tmp_path / "empty_report"
    empty_dir.mkdir()
    with patch("sys.argv", ["acceptance_gate.py", "--report-dir", str(empty_dir)]):
        code = main()
        assert code == 1


def test_main_corrupt_summary(tmp_path):
    """CLI fails when acceptance-summary.json is corrupt."""
    report_dir = tmp_path / "corrupt_report"
    report_dir.mkdir()
    (report_dir / "acceptance-summary.json").write_text("invalid { json", encoding="utf-8")
    with patch("sys.argv", ["acceptance_gate.py", "--report-dir", str(report_dir)]):
        code = main()
        assert code == 1


def test_main_corrupt_manifest(tmp_path):
    """CLI fails when manifest is invalid YAML."""
    report_dir = tmp_path / "valid_report"
    report_dir.mkdir()
    (report_dir / "acceptance-summary.json").write_text(
        json.dumps({"results": []}), encoding="utf-8"
    )
    bad_manifest = tmp_path / "bad_manifest.yaml"
    bad_manifest.write_text("bad: [unclosed", encoding="utf-8")

    with patch(
        "sys.argv",
        [
            "acceptance_gate.py",
            "--report-dir",
            str(report_dir),
            "--manifest",
            str(bad_manifest),
        ],
    ):
        code = main()
        assert code == 1


def test_main_pass_and_fail_json_and_text(tmp_path, capsys):
    """CLI prints text or json format and returns correct exit codes."""
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    manifest_p = tmp_path / "release.yaml"
    manifest_p.write_text(
        "thresholds: {}\ncases:\n  - tests/acceptance/corpus/AT-01.yaml\n",
        encoding="utf-8",
    )

    # 1. Successful run with --json
    valid_summary = {
        "total_cases": 1,
        "results": [{"case_id": "AT-01", "accepted": True}],
    }
    (report_dir / "acceptance-summary.json").write_text(json.dumps(valid_summary), encoding="utf-8")
    with patch(
        "sys.argv",
        [
            "acceptance_gate.py",
            "--report-dir",
            str(report_dir),
            "--manifest",
            str(manifest_p),
            "--json",
        ],
    ):
        code = main()
        assert code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["passed"] is True

    # 2. Failing run with text output
    failing_summary = {
        "total_cases": 1,
        "results": [
            {
                "case_id": "AT-01",
                "accepted": False,
                "category": "security",
                "failures": ["Critical vulnerability"],
            }
        ],
    }
    (report_dir / "acceptance-summary.json").write_text(
        json.dumps(failing_summary), encoding="utf-8"
    )
    with patch(
        "sys.argv",
        [
            "acceptance_gate.py",
            "--report-dir",
            str(report_dir),
            "--manifest",
            str(manifest_p),
        ],
    ):
        code = main()
        assert code == 1
        captured = capsys.readouterr()
        assert "AGENTV ACCEPTANCE RELEASE GATE" in captured.out
        assert "ZERO-TOLERANCE BREACH" in captured.out

    # 3. Successful run with text output (covers line 195)
    (report_dir / "acceptance-summary.json").write_text(json.dumps(valid_summary), encoding="utf-8")
    with patch(
        "sys.argv",
        [
            "acceptance_gate.py",
            "--report-dir",
            str(report_dir),
            "--manifest",
            str(manifest_p),
        ],
    ):
        code = main()
        assert code == 0
        captured = capsys.readouterr()
        assert "ALL THRESHOLDS SATISFIED" in captured.out


def test_main_relative_paths(tmp_path, monkeypatch):
    """Test relative paths resolution in CLI."""
    import tools.ci.acceptance_gate as gate_mod

    monkeypatch.setattr(gate_mod, "REPO_ROOT", tmp_path)

    rel_report_dir = tmp_path / "rel_reports"
    rel_report_dir.mkdir()
    rel_manifest = tmp_path / "rel_manifest.yaml"
    rel_manifest.write_text(
        "thresholds: {}\ncases:\n  - tests/acceptance/corpus/AT-01.yaml\n",
        encoding="utf-8",
    )

    summary = {
        "total_cases": 1,
        "results": [{"case_id": "AT-01", "accepted": True}],
    }
    (rel_report_dir / "acceptance-summary.json").write_text(json.dumps(summary), encoding="utf-8")

    with patch(
        "sys.argv",
        [
            "acceptance_gate.py",
            "--report-dir",
            "rel_reports",
            "--manifest",
            "rel_manifest.yaml",
            "--json",
        ],
    ):
        code = main()
        assert code == 0


def test_main_dunder_entrypoint(tmp_path, monkeypatch):
    """Test __main__ invocation via runpy."""
    import runpy

    import pytest

    rel_report_dir = tmp_path / "main_reports"
    rel_report_dir.mkdir()
    rel_manifest = tmp_path / "main_manifest.yaml"
    rel_manifest.write_text(
        "thresholds: {}\ncases:\n  - tests/acceptance/corpus/AT-01.yaml\n",
        encoding="utf-8",
    )
    summary = {
        "total_cases": 1,
        "results": [{"case_id": "AT-01", "accepted": True}],
    }
    (rel_report_dir / "acceptance-summary.json").write_text(json.dumps(summary), encoding="utf-8")

    with patch(
        "sys.argv",
        [
            "acceptance_gate.py",
            "--report-dir",
            str(rel_report_dir),
            "--manifest",
            str(rel_manifest),
            "--json",
        ],
    ):
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("tools.ci.acceptance_gate", run_name="__main__")
        assert exc_info.value.code == 0


def test_evaluate_summary_skipped_cases_rejected():
    """Verify that skipped cases immediately breach zero-tolerance release gate."""
    summary = {
        "total_cases": 1,
        "results": [{"case_id": "AT-01", "accepted": True, "skipped": True}],
    }
    decision = evaluate_summary(summary, None)
    assert decision.passed is False
    assert any("skipped acceptance test case(s) detected" in r for r in decision.reasons)


def test_evaluate_summary_mandatory_oracle_branches(monkeypatch):
    """Verify mandatory oracle evaluation branches."""
    suite = {
        "require_external_oracle": True,
        "thresholds": {},
        "cases": ["tests/acceptance/corpus/AT-01.yaml"],
    }
    # 1. Missing receipt hash when oracle required -> gate fails
    summary_no_receipt = {
        "total_cases": 1,
        "results": [
            {
                "case_id": "AT-01",
                "accepted": True,
                "expected": {"state": {"oracle_url": "http://127.0.0.1:8099"}},
                "actual": {"state": {"oracle_receipt_hash": ""}},
            }
        ],
    }
    decision = evaluate_summary(summary_no_receipt, suite)
    assert decision.passed is False
    assert any("Mandatory external acceptance oracle was required" in r for r in decision.reasons)

    # 2. Present receipt hash when oracle required -> passes
    summary_with_receipt = {
        "total_cases": 1,
        "results": [
            {
                "case_id": "AT-01",
                "accepted": True,
                "expected": {"state": {"oracle_url": "http://127.0.0.1:8099"}},
                "actual": {"state": {"oracle_receipt_hash": "sha256:abc1234"}},
            }
        ],
    }
    decision_ok = evaluate_summary(summary_with_receipt, suite)
    assert decision_ok.passed is True
