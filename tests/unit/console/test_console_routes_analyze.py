"""
tests/unit/console/test_console_routes_analyze.py

Unit tests for eval_runner.console.routes.analyze.
Covers: leaderboard, leaderboard HTML export, failure search, triage,
        compliance (single + summary), and forensic diff endpoints.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.routes.analyze import analyze_bp

# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def analyze_jail(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    reports = tmp_path / "reports"
    reports.mkdir()
    return {"root": tmp_path, "runs": runs, "reports": reports}


@pytest.fixture
def analyze_client(analyze_jail, monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(analyze_bp, url_prefix="/api")

    monkeypatch.setattr(config, "PROJECT_ROOT", analyze_jail["root"])
    monkeypatch.setattr(config, "RUN_LOG_DIR", analyze_jail["runs"])
    monkeypatch.setattr(config, "REPORTS_DIR", analyze_jail["reports"])

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        yield app.test_client()


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------


def test_analyze_leaderboard_success(analyze_client):
    rows = [{"agent": "agt-a", "pass_rate": 0.9}]
    with patch(
        "eval_runner.console.routes.analyze.LeaderboardGenerator.generate_data", return_value=rows
    ):
        res = analyze_client.get("/api/leaderboard")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total"] == 1
    assert data["leaderboard"][0]["agent"] == "agt-a"


def test_analyze_leaderboard_exception(analyze_client):
    with patch(
        "eval_runner.console.routes.analyze.LeaderboardGenerator.generate_data",
        side_effect=RuntimeError("disk error"),
    ):
        res = analyze_client.get("/api/leaderboard")
    assert res.status_code == 500
    assert "disk error" in res.get_json()["error"]


def test_analyze_leaderboard_export_html_exception(analyze_client):
    with patch(
        "eval_runner.console.routes.analyze.send_file",
        side_effect=Exception("builder crash"),
    ):
        res = analyze_client.post("/api/leaderboard/export-html")
    assert res.status_code == 500


def test_analyze_leaderboard_export_html_success(analyze_client, analyze_jail):
    html_path = analyze_jail["root"] / "reports" / "leaderboard.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text("<html></html>", encoding="utf-8")

    with patch("eval_runner.console.routes.analyze.config.PROJECT_ROOT", analyze_jail["root"]):
        with patch("eval_runner.publication_suite.html_builder.HTMLBuilder") as mock_builder_class:
            mock_builder = MagicMock()
            mock_builder_class.return_value = mock_builder

            res = analyze_client.post("/api/leaderboard/export-html")
            assert res.status_code == 200
            assert b"<html>" in res.data
            mock_builder.build.assert_called_once()


# ---------------------------------------------------------------------------
# Failure search
# ---------------------------------------------------------------------------


def test_analyze_search_failures_missing_q(analyze_client):
    res = analyze_client.get("/api/failures/search")
    assert res.status_code == 400
    assert "required" in res.get_json()["error"]


def test_analyze_search_failures_no_master_log(analyze_client):
    res = analyze_client.get("/api/failures/search?q=test")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total"] == 0
    assert data["matches"] == []
    assert data["mode"] == "text"


def test_analyze_search_failures_text_match(analyze_client, analyze_jail):
    master_log = analyze_jail["runs"] / "run.jsonl"
    line1 = json.dumps(
        {"run_id": "r1", "event": "tool_call", "status": "FAIL", "content": "authentication error"}
    )
    line2 = json.dumps(
        {"run_id": "r2", "event": "metric_scored", "status": "PASS", "content": "ok"}
    )
    master_log.write_text(f"{line1}\n{line2}\n", encoding="utf-8")

    res = analyze_client.get("/api/failures/search?q=authentication")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total"] == 1
    assert data["matches"][0]["run_id"] == "r1"
    assert data["mode"] == "text"


def test_analyze_search_failures_regex_match(analyze_client, analyze_jail):
    master_log = analyze_jail["runs"] / "run.jsonl"
    line = json.dumps({"run_id": "r3", "event": "error", "status": "FAIL", "content": "timeout123"})
    master_log.write_text(f"{line}\n", encoding="utf-8")

    res = analyze_client.get("/api/failures/search?q=timeout%5Cd%2B")
    assert res.status_code == 200
    data = res.get_json()
    assert data["mode"] == "regex"
    assert data["total"] == 1


def test_analyze_search_failures_invalid_regex_falls_back_to_text(analyze_client, analyze_jail):
    master_log = analyze_jail["runs"] / "run.jsonl"
    line = json.dumps({"run_id": "r4", "event": "tool_call", "status": "FAIL", "content": "crash"})
    master_log.write_text(f"{line}\n", encoding="utf-8")

    res = analyze_client.get("/api/failures/search?q=%5B")
    assert res.status_code == 200
    assert res.get_json()["mode"] == "text"


def test_analyze_search_failures_pagination(analyze_client, analyze_jail):
    master_log = analyze_jail["runs"] / "run.jsonl"
    lines = [
        json.dumps({"run_id": f"r{i}", "event": "crash", "status": "FAIL", "content": "crash"})
        for i in range(5)
    ]
    master_log.write_text("\n".join(lines), encoding="utf-8")

    res = analyze_client.get("/api/failures/search?q=crash&page=1&limit=3")
    data = res.get_json()
    assert data["total"] == 5
    assert len(data["matches"]) == 3
    assert data["pages"] == 2


def test_analyze_search_failures_skips_empty_and_bad_json(analyze_client, analyze_jail):
    master_log = analyze_jail["runs"] / "run.jsonl"
    master_log.write_text(
        "\n\nnot-json\n"
        + json.dumps({"run_id": "r1", "event": "err", "status": "x", "content": "crash"})
        + "\n",
        encoding="utf-8",
    )
    res = analyze_client.get("/api/failures/search?q=crash")
    assert res.status_code == 200
    assert res.get_json()["total"] == 1


def test_analyze_search_failures_io_error(analyze_client, analyze_jail):
    master_log = analyze_jail["runs"] / "run.jsonl"
    master_log.write_text("{}", encoding="utf-8")

    with patch("builtins.open", side_effect=OSError("disk fail")):
        res = analyze_client.get("/api/failures/search?q=x")
    assert res.status_code == 500


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------


def test_analyze_triage_not_found(analyze_client):
    res = analyze_client.post("/api/triage/nonexistent-run")
    assert res.status_code == 404
    assert "not found" in res.get_json()["error"]


def test_analyze_triage_success(analyze_client, analyze_jail):
    run_id = "triage_run_a"
    run_dir = analyze_jail["runs"] / run_id
    run_dir.mkdir()
    trace = run_dir / "run.jsonl"
    trace.write_text(
        json.dumps({"run_id": run_id, "event": "tool_call", "task_id": "t1"}) + "\n",
        encoding="utf-8",
    )

    mock_result = {"task_id": "t1", "triage_tag": "TOOL_FAILURE", "metrics": []}
    mock_root_cause = {
        "category": "TOOL_FAILURE",
        "confidence": 0.95,
        "reason": "Tool returned error",
        "suggestion": "Check tool config",
        "index": 2,
    }

    with patch("eval_runner.console.routes.analyze.load_events", return_value=[{}]):
        with patch(
            "eval_runner.console.routes.analyze.reconstruct_results_from_events",
            return_value=[mock_result],
        ):
            with patch(
                "eval_runner.triage.TriageEngine.identify_root_cause",
                return_value=mock_root_cause,
            ):
                res = analyze_client.post(f"/api/triage/{run_id}")

    assert res.status_code == 200
    data = res.get_json()
    assert data["run_id"] == run_id
    assert data["total"] == 1
    assert data["results"][0]["category"] == "TOOL_FAILURE"


def test_analyze_triage_exception(analyze_client, analyze_jail):
    run_id = "triage_err_b"
    run_dir = analyze_jail["runs"] / run_id
    run_dir.mkdir()
    (run_dir / "run.jsonl").write_text("{}", encoding="utf-8")

    with patch("eval_runner.console.routes.analyze.load_events", side_effect=RuntimeError("bad")):
        res = analyze_client.post(f"/api/triage/{run_id}")

    assert res.status_code == 500


# ---------------------------------------------------------------------------
# Compliance (single run)
# ---------------------------------------------------------------------------


def test_analyze_compliance_single_not_found(analyze_client):
    res = analyze_client.get("/api/compliance/missing-run-xyz")
    assert res.status_code == 404


def test_analyze_compliance_single_success(analyze_client, analyze_jail):
    run_id = "comp_run_c"
    (analyze_jail["runs"] / run_id).mkdir()

    mock_status = {"quantum_safe": True, "algorithm": "ML-DSA-65"}
    with patch(
        "eval_runner.console.routes.analyze._compliance_svc.check_pqc_status",
        return_value=mock_status,
    ):
        res = analyze_client.get(f"/api/compliance/{run_id}")

    assert res.status_code == 200
    data = res.get_json()
    assert data["run_id"] == run_id
    assert data["quantum_safe"] is True


def test_analyze_compliance_single_exception(analyze_client, analyze_jail):
    run_id = "comp_err_d"
    (analyze_jail["runs"] / run_id).mkdir()

    with patch(
        "eval_runner.console.routes.analyze._compliance_svc.check_pqc_status",
        side_effect=RuntimeError("pqc exploded"),
    ):
        res = analyze_client.get(f"/api/compliance/{run_id}")

    assert res.status_code == 500
    assert "pqc exploded" in res.get_json()["error"]


# ---------------------------------------------------------------------------
# Compliance summary
# ---------------------------------------------------------------------------


def test_analyze_compliance_summary_empty(analyze_client):
    res = analyze_client.get("/api/compliance/summary")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total_certified"] == 0
    assert data["percent_quantum_safe"] == 0.0


def test_analyze_compliance_summary_with_runs(analyze_client, analyze_jail):
    for run_id in ["run-safe-e", "run-classic-f"]:
        run_dir = analyze_jail["runs"] / run_id
        run_dir.mkdir()
        (run_dir / "run_manifest.json").write_text(json.dumps({"run_id": run_id}), encoding="utf-8")

    def mock_pqc(run_id):
        return {"quantum_safe": "safe" in run_id}

    with patch(
        "eval_runner.console.routes.analyze._compliance_svc.check_pqc_status",
        side_effect=mock_pqc,
    ):
        res = analyze_client.get("/api/compliance/summary")

    assert res.status_code == 200
    data = res.get_json()
    assert data["total_certified"] == 2
    assert data["quantum_safe"] == 1
    assert data["classical_only"] == 1
    assert data["percent_quantum_safe"] == 50.0


def test_analyze_compliance_summary_date_filter(analyze_client, analyze_jail):
    for run_id in ["2026-07-run", "2025-12-run"]:
        run_dir = analyze_jail["runs"] / run_id
        run_dir.mkdir()
        (run_dir / "run_manifest.json").write_text("{}", encoding="utf-8")

    with patch(
        "eval_runner.console.routes.analyze._compliance_svc.check_pqc_status",
        return_value={"quantum_safe": True},
    ):
        res = analyze_client.get("/api/compliance/summary?range=2026-07")

    assert res.status_code == 200
    assert res.get_json()["total_certified"] == 1


def test_analyze_compliance_summary_exception_skips_run(analyze_client, analyze_jail):
    run_dir = analyze_jail["runs"] / "bad-run-g"
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text("{}", encoding="utf-8")

    with patch(
        "eval_runner.console.routes.analyze._compliance_svc.check_pqc_status",
        side_effect=RuntimeError("boom"),
    ):
        res = analyze_client.get("/api/compliance/summary")

    assert res.status_code == 200
    assert res.get_json()["total_certified"] == 0


# ---------------------------------------------------------------------------
# Forensic diff
# ---------------------------------------------------------------------------


def test_analyze_forensic_diff_missing_body(analyze_client):
    res = analyze_client.post("/api/forensics/diff", json={})
    assert res.status_code == 400


def test_analyze_forensic_diff_not_lists(analyze_client):
    res = analyze_client.post("/api/forensics/diff", json={"old": "str", "new": []})
    assert res.status_code == 400


def test_analyze_forensic_diff_success_identical(analyze_client):
    state = [{"id": "1", "val": "x"}]
    with patch("eval_runner.console.routes.analyze.list_diff", return_value=None):
        res = analyze_client.post("/api/forensics/diff", json={"old": state, "new": state})
    assert res.status_code == 200
    assert res.get_json()["identical"] is True


def test_analyze_forensic_diff_success_changed(analyze_client):
    old = [{"id": "1", "val": "old"}]
    new = [{"id": "1", "val": "new"}]
    with patch("eval_runner.console.routes.analyze.list_diff", return_value={"modified": []}):
        res = analyze_client.post("/api/forensics/diff", json={"old": old, "new": new})
    assert res.status_code == 200
    data = res.get_json()
    assert data["identical"] is False
    assert data["detected_primary_key"] == "id"


def test_analyze_forensic_diff_pk_detection_audit_id(analyze_client):
    old = [{"audit_id": "a1", "val": "v"}]
    new = [{"audit_id": "a1", "val": "v2"}]
    with patch("eval_runner.console.routes.analyze.list_diff", return_value={}):
        res = analyze_client.post("/api/forensics/diff", json={"old": old, "new": new})
    assert res.status_code == 200
    assert res.get_json()["detected_primary_key"] == "audit_id"


def test_analyze_forensic_diff_pk_no_match(analyze_client):
    old = [{"custom_key": "c1"}]
    new = [{"custom_key": "c2"}]
    with patch("eval_runner.console.routes.analyze.list_diff", return_value={}):
        res = analyze_client.post("/api/forensics/diff", json={"old": old, "new": new})
    assert res.status_code == 200
    assert res.get_json()["detected_primary_key"] is None


def test_analyze_forensic_diff_exception(analyze_client):
    with patch(
        "eval_runner.console.routes.analyze.list_diff", side_effect=RuntimeError("diff crash")
    ):
        res = analyze_client.post(
            "/api/forensics/diff", json={"old": [{"id": "1"}], "new": [{"id": "2"}]}
        )
    assert res.status_code == 500
    assert "diff crash" in res.get_json()["error"]


def test_analyze_forensic_diff_empty_old_skips_pk_detection(analyze_client):
    with patch("eval_runner.console.routes.analyze.list_diff", return_value=None):
        res = analyze_client.post("/api/forensics/diff", json={"old": [], "new": []})
    assert res.status_code == 200
    assert res.get_json()["detected_primary_key"] is None
