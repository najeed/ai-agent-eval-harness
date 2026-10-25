"""
tests/unit/console/test_console_routes_analyze.py

Unit tests for eval_runner.console.routes.analyze.
Covers: leaderboard, leaderboard HTML export, failure search, triage,
        compliance (single + summary), and forensic diff endpoints.
"""

from unittest.mock import patch

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
    from eval_runner.reference.local_run_store import LocalFileRunStore

    app = Flask(__name__)
    app.secret_key = "test-secret"
    store = LocalFileRunStore(analyze_jail["runs"])
    app.extensions["agentv_run_store"] = store
    app.register_blueprint(analyze_bp, url_prefix="/api")

    monkeypatch.setattr(config, "PROJECT_ROOT", analyze_jail["root"])
    monkeypatch.setattr(config, "RUN_LOG_DIR", analyze_jail["runs"])
    monkeypatch.setattr(config, "REPORTS_DIR", analyze_jail["reports"])

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        yield app.test_client()


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------


class FakeLeaderboardRunStore:
    def __init__(self, fail: bool = False):
        self.fail = fail

    def list_runs(self, limit=10_000, context=None):
        if self.fail:
            raise RuntimeError("disk error")
        return [{"run_id": "run-1", "agent": "agt-a", "score": 0.9, "result_status": "PASS"}]

    def get_manifest(self, run_id, context=None):
        return {"agent_name": "agt-a", "score": 0.9}

    def get_events(self, run_id, offset=0, limit=10_000_000, context=None):
        return [{"event": "run_end", "data": {"finalization": {"score": 0.9, "outcome": "PASS"}}}]


def test_analyze_leaderboard_success(analyze_client):
    fake_store = FakeLeaderboardRunStore()
    with patch("eval_runner.console.routes.analyze._run_store", return_value=fake_store):
        res = analyze_client.get("/api/leaderboard")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total"] == 1
    assert data["leaderboard"][0]["agent"] == "agt-a"


def test_analyze_leaderboard_exception(analyze_client):
    fake_store = FakeLeaderboardRunStore(fail=True)
    with patch("eval_runner.console.routes.analyze._run_store", return_value=fake_store):
        res = analyze_client.get("/api/leaderboard")
    assert res.status_code == 500
    assert "disk error" in res.get_json()["error"]


def test_analyze_leaderboard_export_html_exception(analyze_client):
    with patch(
        "eval_runner.console.routes.analyze._provider_leaderboard_rows",
        side_effect=Exception("builder crash"),
    ):
        res = analyze_client.post("/api/leaderboard/export-html")
    assert res.status_code == 500


def test_analyze_leaderboard_export_html_success(analyze_client):
    fake_store = FakeLeaderboardRunStore()
    with patch("eval_runner.console.routes.analyze._run_store", return_value=fake_store):
        res = analyze_client.post("/api/leaderboard/export-html")
        assert res.status_code == 200
        assert b"<!doctype html>" in res.data
        assert b"agt-a" in res.data


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
    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(analyze_jail["runs"])
    store.create_run("r1", "test")
    store.append_events(
        "r1",
        [
            {
                "run_id": "r1",
                "event": "tool_call",
                "status": "FAIL",
                "content": "authentication error",
            }
        ],
    )
    store.create_run("r2", "test")
    store.append_events(
        "r2",
        [{"run_id": "r2", "event": "metric_scored", "status": "PASS", "content": "ok"}],
    )

    res = analyze_client.get("/api/failures/search?q=authentication")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total"] == 1
    assert data["matches"][0]["run_id"] == "r1"
    assert data["mode"] == "text"


def test_analyze_search_failures_regex_match(analyze_client, analyze_jail):
    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(analyze_jail["runs"])
    store.create_run("r3", "test")
    store.append_events(
        "r3",
        [{"run_id": "r3", "event": "error", "status": "FAIL", "content": "timeout123"}],
    )

    res = analyze_client.get("/api/failures/search?q=timeout%5Cd%2B")
    assert res.status_code == 200
    data = res.get_json()
    assert data["mode"] == "regex"
    assert data["total"] == 1


def test_analyze_search_failures_invalid_regex_falls_back_to_text(analyze_client, analyze_jail):
    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(analyze_jail["runs"])
    store.create_run("r4", "test")
    store.append_events(
        "r4",
        [{"run_id": "r4", "event": "tool_call", "status": "FAIL", "content": "crash"}],
    )

    res = analyze_client.get("/api/failures/search?q=%5B")
    assert res.status_code == 200
    assert res.get_json()["mode"] == "text"


def test_analyze_search_failures_pagination(analyze_client, analyze_jail):
    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(analyze_jail["runs"])
    for i in range(5):
        run_id = f"r{i}"
        store.create_run(run_id, "test")
        store.append_events(
            run_id,
            [{"run_id": run_id, "event": "crash", "status": "FAIL", "content": "crash"}],
        )

    res = analyze_client.get("/api/failures/search?q=crash&page=1&limit=3")
    data = res.get_json()
    assert data["total"] == 5
    assert len(data["matches"]) == 3
    assert data["pages"] == 2


def test_analyze_search_failures_skips_empty_and_bad_json(analyze_client, analyze_jail):
    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(analyze_jail["runs"])
    store.create_run("r1", "test")
    store.append_events(
        "r1",
        [{"run_id": "r1", "event": "err", "status": "x", "content": "crash"}],
    )
    res = analyze_client.get("/api/failures/search?q=crash")
    assert res.status_code == 200
    assert res.get_json()["total"] == 1


def test_analyze_search_failures_io_error(analyze_client, analyze_jail):
    with patch(
        "eval_runner.console.routes.analyze._run_store",
        side_effect=OSError("disk fail"),
    ):
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
    from eval_runner.reference.local_run_store import LocalFileRunStore

    run_id = "triage_run_a"
    store = LocalFileRunStore(analyze_jail["runs"])
    store.create_run(run_id, "test")
    store.append_events(
        run_id,
        [{"run_id": run_id, "event": "tool_call", "task_id": "t1"}],
    )

    mock_result = {"task_id": "t1", "triage_tag": "TOOL_FAILURE", "metrics": []}
    mock_root_cause = {
        "category": "TOOL_FAILURE",
        "confidence": 0.95,
        "reason": "Tool returned error",
        "suggestion": "Check tool config",
        "index": 2,
    }

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


def test_analyze_triage_reports_authoritative_failed_graph_node(analyze_client, analyze_jail):
    """Run-level events must not create an ``unknown`` triage task."""
    from eval_runner.reference.local_run_store import LocalFileRunStore

    run_id = "triage_graph_failure"
    store = LocalFileRunStore(analyze_jail["runs"])
    store.create_run(run_id, "test")
    store.append_events(
        run_id,
        [
            {"event": "run_start", "run_id": run_id},
            {
                "event": "execution_graph_node",
                "scenario_node_id": "reset_authority",
                "status": "completed",
                "_seq": 2,
            },
            {
                "event": "execution_graph_node",
                "scenario_node_id": "verify_provider_notification",
                "status": "failed",
                "failure_class": "VERIFICATION_FAILED",
                "failure_reason": "Provider notification was not delivered",
                "_seq": 3,
            },
        ],
    )

    res = analyze_client.post(f"/api/triage/{run_id}")

    assert res.status_code == 200
    reports = res.get_json()["results"]
    assert [report["task_id"] for report in reports] == [
        "reset_authority",
        "verify_provider_notification",
    ]
    assert reports[1]["triage_tag"] == "VERIFICATION_FAILED"
    assert "unknown" not in {report["task_id"] for report in reports}


def test_analyze_triage_exception(analyze_client, analyze_jail):
    from eval_runner.reference.local_run_store import LocalFileRunStore

    run_id = "triage_err_b"
    store = LocalFileRunStore(analyze_jail["runs"])
    store.create_run(run_id, "test")
    store.append_events(run_id, [{"run_id": run_id, "event": "tool_call"}])

    with patch(
        "eval_runner.console.routes.analyze.reconstruct_results_from_events",
        side_effect=RuntimeError("bad"),
    ):
        res = analyze_client.post(f"/api/triage/{run_id}")

    assert res.status_code == 500


# ---------------------------------------------------------------------------
# Compliance (single run)
# ---------------------------------------------------------------------------


def test_analyze_compliance_single_not_found(analyze_client):
    res = analyze_client.get("/api/compliance/missing-run-xyz")
    assert res.status_code == 404


def test_analyze_compliance_single_success(analyze_client, analyze_jail):
    from eval_runner.reference.local_run_store import LocalFileRunStore

    run_id = "comp_run_c"
    store = LocalFileRunStore(analyze_jail["runs"])
    store.create_run(run_id, "test")
    store.save_run_manifest(run_id, {"run_id": run_id, "algorithm": "ML-DSA-65"})

    res = analyze_client.get(f"/api/compliance/{run_id}")

    assert res.status_code == 200
    data = res.get_json()
    assert data["run_id"] == run_id
    assert data["quantum_safe"] is True


def test_analyze_compliance_single_exception(analyze_client, analyze_jail):
    from eval_runner.reference.local_run_store import LocalFileRunStore

    run_id = "comp_err_d"
    store = LocalFileRunStore(analyze_jail["runs"])
    store.create_run(run_id, "test")

    with patch(
        "eval_runner.console.routes.analyze._run_store",
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
    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(analyze_jail["runs"])
    store.create_run("run-safe-e", "test")
    store.save_run_manifest("run-safe-e", {"run_id": "run-safe-e", "algorithm": "ML-DSA-65"})
    store.create_run("run-classic-f", "test")
    store.save_run_manifest("run-classic-f", {"run_id": "run-classic-f", "algorithm": "ED25519"})

    res = analyze_client.get("/api/compliance/summary")

    assert res.status_code == 200
    data = res.get_json()
    assert data["total_certified"] == 2
    assert data["quantum_safe"] == 1
    assert data["classical_only"] == 1
    assert data["percent_quantum_safe"] == 50.0


def test_analyze_compliance_summary_date_filter(analyze_client, analyze_jail):
    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(analyze_jail["runs"])
    store.create_run("2026-07-run", "test")
    store.save_run_manifest("2026-07-run", {"run_id": "2026-07-run", "algorithm": "ML-DSA-65"})
    store.create_run("2025-12-run", "test")
    store.save_run_manifest("2025-12-run", {"run_id": "2025-12-run", "algorithm": "ML-DSA-65"})

    res = analyze_client.get("/api/compliance/summary?range=2026-07")

    assert res.status_code == 200
    assert res.get_json()["total_certified"] == 1


def test_analyze_compliance_summary_exception_skips_run(analyze_client, analyze_jail):
    active_store = analyze_client.application.extensions["agentv_run_store"]
    active_store.create_run("bad-run-g", "test")
    with patch.object(active_store, "get_manifest", side_effect=RuntimeError("boom")):
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


def test_analyze_cross_context_isolation(analyze_client, analyze_jail, monkeypatch):
    import eval_runner.console.routes.analyze as analyze_mod

    run_id = "cross_ctx_run"
    run_dir = analyze_jail["runs"] / run_id
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text("{}", encoding="utf-8")
    (run_dir / "run.jsonl").write_text("{}", encoding="utf-8")

    # Mock _run_is_in_active_context to return False
    monkeypatch.setattr(analyze_mod, "_run_is_in_active_context", lambda rid: False)

    # 1. Triage 404
    res_triage = analyze_client.post(f"/api/triage/{run_id}")
    assert res_triage.status_code == 404
    assert res_triage.get_json()["error"] == "Run not found"

    # 2. Compliance 404
    res_comp = analyze_client.get(f"/api/compliance/{run_id}")
    assert res_comp.status_code == 404
    assert res_comp.get_json()["error"] == "Run not found"

    # 3. Compliance summary skips run
    res_summary = analyze_client.get("/api/compliance/summary")
    assert res_summary.status_code == 200
    assert res_summary.get_json()["total_certified"] == 0
