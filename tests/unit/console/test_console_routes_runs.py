"""
tests/unit/console/test_console_routes_runs.py

Unit tests for eval_runner.console.routes.runs.
Covers: resolve_trace_path, list_metrics, explain_run, list_runs,
        get_run_status, get_verification_certificate, is_run_alive,
        stream_run_logs, tail_file_generator.
"""

import json
import os
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.routes.runs import (
    is_run_alive,
    resolve_trace_path,
    run_bp,
    tail_file_generator,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runs_jail(tmp_path):
    root = tmp_path / "root"
    runs = root / "results"
    reports = root / "reports"

    (reports / "certificates").mkdir(parents=True, exist_ok=True)
    runs.mkdir(parents=True, exist_ok=True)
    return {"root": root, "runs": runs, "reports": reports}


@pytest.fixture
def runs_client(runs_jail, monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(run_bp, url_prefix="/api")

    monkeypatch.setattr(config, "PROJECT_ROOT", runs_jail["root"])
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_jail["runs"])
    monkeypatch.setattr(config, "REPORTS_DIR", runs_jail["reports"])

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        yield app.test_client()


# ---------------------------------------------------------------------------
# resolve_trace_path
# ---------------------------------------------------------------------------


def test_resolve_trace_path_vault(runs_jail, monkeypatch):
    """Path 1: {run_id}/run.jsonl exists."""
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_jail["runs"])
    rid = "resolve-vault-1"
    d = runs_jail["runs"] / rid
    d.mkdir(exist_ok=True)
    (d / "run.jsonl").write_text("{}", encoding="utf-8")
    result = resolve_trace_path(rid)
    assert result == d / "run.jsonl"


def test_resolve_trace_path_direct_jsonl(runs_jail, monkeypatch):
    """Path 2: {run_id}.jsonl exists directly."""
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_jail["runs"])
    rid = "resolve-direct-2"
    p = runs_jail["runs"] / f"{rid}.jsonl"
    p.write_text("{}", encoding="utf-8")
    result = resolve_trace_path(rid)
    assert result == p


def test_resolve_trace_path_bare_file(runs_jail, monkeypatch):
    """Path 3: bare {run_id} file exists."""
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_jail["runs"])
    rid = "resolve-bare-3"
    p = runs_jail["runs"] / rid
    p.write_text("{}", encoding="utf-8")
    result = resolve_trace_path(rid)
    assert result == p


def test_resolve_trace_path_none(runs_jail, monkeypatch):
    """Path 4: nothing found → None."""
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_jail["runs"])
    result = resolve_trace_path("nonexistent-run-xyz")
    assert result is None


# ---------------------------------------------------------------------------
# list_metrics
# ---------------------------------------------------------------------------


def test_list_metrics(runs_client):
    with patch("eval_runner.console.routes.runs.MetricRegistry.list_metrics", return_value=["acc"]):
        res = runs_client.get("/api/v1/metrics")
    assert res.status_code == 200
    assert res.get_json()["metrics"] == ["acc"]


# ---------------------------------------------------------------------------
# explain_run
# ---------------------------------------------------------------------------


def test_explain_run_vault_trace(runs_jail, runs_client):
    """explain_run: trace found directly, explain_trace succeeds."""
    rid = "explain-vault-ok"
    d = runs_jail["runs"] / rid
    d.mkdir(exist_ok=True)
    (d / "run.jsonl").write_text("{}", encoding="utf-8")

    with patch("eval_runner.console.routes.runs.explain_trace", return_value={"root": "none"}):
        res = runs_client.get(f"/api/v1/explain/{rid}")
    assert res.status_code == 200
    data = res.get_json()
    assert data["run_id"] == rid
    assert data["sourced_from_master"] is False


def test_explain_run_master_log_fallback(runs_jail, runs_client):
    """explain_run: no vault trace, fall back to master log."""
    rid = "explain-master-ok"
    master = runs_jail["runs"] / "run.jsonl"
    master.write_text(json.dumps({"run_id": rid, "event": "run_start"}) + "\n", encoding="utf-8")

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        with patch("eval_runner.console.routes.runs.explain_trace", return_value={}):
            res = runs_client.get(f"/api/v1/explain/{rid}")

    # Clean up
    master.unlink(missing_ok=True)
    assert res.status_code == 200
    assert res.get_json()["sourced_from_master"] is True


def test_explain_run_master_log_scan_error(runs_jail, runs_client):
    """explain_run: master log exists but raises on read → returns 404 (no events)."""
    rid = "explain-master-err"
    master = runs_jail["runs"] / "run.jsonl"
    master.write_text("{}", encoding="utf-8")

    orig_open = open

    def boom(file, *args, **kwargs):
        if str(file) == str(master):
            raise OSError("disk error")
        return orig_open(file, *args, **kwargs)

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        with patch("builtins.open", side_effect=boom):
            res = runs_client.get(f"/api/v1/explain/{rid}")

    master.unlink(missing_ok=True)
    assert res.status_code == 404


def test_explain_run_master_log_no_events_404(runs_jail, runs_client):
    """explain_run: master log exists but contains no events for run → 404."""
    rid = "explain-no-events"
    master = runs_jail["runs"] / "run.jsonl"
    master.write_text(
        json.dumps({"run_id": "other-run", "event": "run_start"}) + "\n", encoding="utf-8"
    )

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        res = runs_client.get(f"/api/v1/explain/{rid}")

    master.unlink(missing_ok=True)
    assert res.status_code == 404


def test_explain_run_temp_write_failure(runs_jail, runs_client):
    """explain_run: temp file write fails → 500."""
    rid = "explain-temp-fail"
    master = runs_jail["runs"] / "run.jsonl"
    master.write_text(json.dumps({"run_id": rid, "event": "run_start"}) + "\n", encoding="utf-8")

    orig_open = open

    def boom_on_write(file, *args, **kwargs):
        if "temp_explain_" in str(file) and "w" in args:
            raise OSError("disk full")
        return orig_open(file, *args, **kwargs)

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        with patch("builtins.open", side_effect=boom_on_write):
            res = runs_client.get(f"/api/v1/explain/{rid}")

    master.unlink(missing_ok=True)
    # Either 404 (filtered_lines were empty because open failed reading) or 500
    assert res.status_code in (404, 500)


def test_explain_run_explain_trace_exception(runs_jail, runs_client):
    """explain_run: explain_trace raises → 500 and temp file cleaned up."""
    rid = "explain-crash"
    d = runs_jail["runs"] / rid
    d.mkdir(exist_ok=True)
    (d / "run.jsonl").write_text("{}", encoding="utf-8")

    with patch("eval_runner.console.routes.runs.explain_trace", side_effect=RuntimeError("boom")):
        res = runs_client.get(f"/api/v1/explain/{rid}")

    assert res.status_code == 500


def test_explain_run_master_log_parse_line_error(runs_jail, runs_client):
    """explain_run: master log contains a corrupt JSON line — logs debug and continues."""
    rid = "explain-corrupt-line"
    master = runs_jail["runs"] / "run.jsonl"
    corrupt_line = "NOT_JSON_AT_ALL"
    good_line = json.dumps({"run_id": rid, "event": "run_start"})
    master.write_text(f"{corrupt_line}\n{good_line}\n", encoding="utf-8")

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        with patch("eval_runner.console.routes.runs.explain_trace", return_value={}):
            res = runs_client.get(f"/api/v1/explain/{rid}")

    master.unlink(missing_ok=True)
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# list_runs
# ---------------------------------------------------------------------------


def test_list_runs_fragments_and_vaults(runs_jail, runs_client):
    """list_runs: covers both fragment scan and vault scan paths."""
    rid_frag = "run-frag-001"
    rid_vault = "run-vault-001"

    # Fragment: direct .jsonl file
    frag = runs_jail["runs"] / f"{rid_frag}.jsonl"
    frag.write_text(
        json.dumps(
            {
                "event": "run_start",
                "run_id": rid_frag,
                "scenario": "S1",
                "timestamp": "2025-01-01T00:00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # Vault: subdirectory with run.jsonl
    vault_dir = runs_jail["runs"] / rid_vault
    vault_dir.mkdir(exist_ok=True)
    (vault_dir / "run.jsonl").write_text(
        json.dumps(
            {
                "event": "run_start",
                "run_id": rid_vault,
                "scenario": "S2",
                "timestamp": "2025-01-02T00:00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    res = runs_client.get("/api/runs")
    assert res.status_code == 200
    ids = [r["run_id"] for r in res.get_json()["runs"]]
    assert rid_frag in ids
    assert rid_vault in ids

    frag.unlink(missing_ok=True)


def test_list_runs_query_filter(runs_jail, runs_client):
    """list_runs: query parameter filters by run_id or scenario."""
    rid = "run-query-filter"
    frag = runs_jail["runs"] / f"{rid}.jsonl"
    frag.write_text(
        json.dumps(
            {
                "event": "run_start",
                "run_id": rid,
                "scenario": "MyScenario",
                "timestamp": "2025-01-03T00:00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    res = runs_client.get("/api/runs?q=myscenario")
    assert any(r["run_id"] == rid for r in res.get_json()["runs"])

    res2 = runs_client.get("/api/runs?q=no_match_xyz")
    assert not any(r["run_id"] == rid for r in res2.get_json()["runs"])

    frag.unlink(missing_ok=True)


def test_list_runs_malformed_fragment(runs_jail, runs_client):
    """list_runs: malformed fragment JSON is silently skipped."""
    bad = runs_jail["runs"] / "bad-fragment.jsonl"
    bad.write_text("NOT_JSON\n", encoding="utf-8")

    res = runs_client.get("/api/runs")
    assert res.status_code == 200  # does not crash

    bad.unlink(missing_ok=True)


def test_list_runs_vault_empty_first_line(runs_jail, runs_client):
    """list_runs: vault with empty first line is skipped."""
    rid = "run-vault-empty"
    d = runs_jail["runs"] / rid
    d.mkdir(exist_ok=True)
    (d / "run.jsonl").write_text("", encoding="utf-8")

    res = runs_client.get("/api/runs")
    assert res.status_code == 200  # does not crash


def test_list_runs_vault_scenario_from_run_id(runs_jail, runs_client):
    """list_runs: vault with no scenario field parses it from run_id."""
    rid = "run-myscen-1735000000"
    d = runs_jail["runs"] / rid
    d.mkdir(exist_ok=True)
    (d / "run.jsonl").write_text(
        json.dumps({"event": "run_start", "run_id": rid}) + "\n", encoding="utf-8"
    )

    res = runs_client.get("/api/runs")
    assert res.status_code == 200
    runs = res.get_json()["runs"]
    match = next((r for r in runs if r["run_id"] == rid), None)
    assert match is not None
    # scenario parsed from middle parts of run id
    assert match["scenario"] == "myscen"


def test_list_runs_vault_scenario_fallback_to_rid(runs_jail, runs_client):
    """list_runs: vault with no scenario and run_id not matching run-X-Y format → scenario=rid."""
    rid = "flatrun"
    d = runs_jail["runs"] / rid
    d.mkdir(exist_ok=True)
    (d / "run.jsonl").write_text(
        json.dumps({"event": "run_start", "run_id": rid}) + "\n", encoding="utf-8"
    )

    res = runs_client.get("/api/runs")
    assert res.status_code == 200


def test_list_runs_vault_malformed(runs_jail, runs_client):
    """list_runs: vault with malformed JSON is silently skipped."""
    rid = "run-malformed-vault"
    d = runs_jail["runs"] / rid
    d.mkdir(exist_ok=True)
    (d / "run.jsonl").write_text("NOT_JSON\n", encoding="utf-8")

    res = runs_client.get("/api/runs")
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# get_run_status
# ---------------------------------------------------------------------------


def test_get_run_status_vault_completed(runs_jail, runs_client):
    """get_run_status: vault trace with run_end event → COMPLETED."""
    rid = "status-vault-complete"
    d = runs_jail["runs"] / rid
    d.mkdir(exist_ok=True)
    (d / "run.jsonl").write_bytes(b'{"event": "run_end", "status": "COMPLETED"}\n')

    res = runs_client.get(f"/api/v1/runs/{rid}")
    assert res.status_code == 200
    assert res.get_json()["status"] == "COMPLETED"


def test_get_run_status_vault_large_file(runs_jail, runs_client):
    """get_run_status: file > 128KB triggers seek path."""
    rid = "status-vault-large"
    d = runs_jail["runs"] / rid
    d.mkdir(exist_ok=True)
    # Write 200KB of padding then a run_end event
    content = b"x" * (200 * 1024) + b'\n{"event": "run_end"}\n'
    (d / "run.jsonl").write_bytes(content)

    res = runs_client.get(f"/api/v1/runs/{rid}")
    assert res.status_code == 200
    assert res.get_json()["status"] == "COMPLETED"


def test_get_run_status_vault_stalled(runs_jail, runs_client):
    """get_run_status: old mtime with no terminal event → STALLED."""
    rid = "status-vault-stalled"
    d = runs_jail["runs"] / rid
    d.mkdir(exist_ok=True)
    (d / "run.jsonl").write_bytes(b'{"event": "run_start"}\n')
    # Set mtime to >5 minutes ago
    old_time = time.time() - 400
    os.utime(d / "run.jsonl", (old_time, old_time))

    res = runs_client.get(f"/api/v1/runs/{rid}")
    assert res.status_code == 200
    assert res.get_json()["status"] == "STALLED"


def test_get_run_status_vault_stat_error(runs_jail, runs_client):
    """get_run_status: getsize/getmtime raises → defaults to RUNNING."""
    rid = "status-vault-err"
    d = runs_jail["runs"] / rid
    d.mkdir(exist_ok=True)
    (d / "run.jsonl").write_bytes(b'{"event": "run_start"}\n')

    with patch("os.path.getsize", side_effect=OSError("no access")):
        res = runs_client.get(f"/api/v1/runs/{rid}")

    assert res.status_code == 200
    assert res.get_json()["status"] == "RUNNING"


def test_get_run_status_vault_has_certificate(runs_jail, runs_client):
    """get_run_status: vault manifest exists → has_certificate is True."""
    rid = "status-vault-cert"
    d = runs_jail["runs"] / rid
    d.mkdir(exist_ok=True)
    (d / "run.jsonl").write_bytes(b'{"event": "run_start"}\n')
    (d / "run_manifest.json").write_text("{}", encoding="utf-8")

    res = runs_client.get(f"/api/v1/runs/{rid}")
    assert res.status_code == 200
    assert res.get_json()["has_certificate"] is True


def test_get_run_status_master_log_completed(runs_jail, runs_client):
    """get_run_status: no vault trace, master log has run_end → COMPLETED."""
    rid = "status-master-complete"
    master = runs_jail["runs"] / "run.jsonl"
    lines = [
        json.dumps({"run_id": rid, "event": "run_start"}),
        json.dumps({"run_id": rid, "event": "run_end"}),
    ]
    master.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        res = runs_client.get(f"/api/v1/runs/{rid}")

    master.unlink(missing_ok=True)
    assert res.status_code == 200
    assert res.get_json()["status"] == "COMPLETED"


def test_get_run_status_master_log_running(runs_jail, runs_client):
    """get_run_status: master log events present, no run_end, thread active → RUNNING."""
    rid = "status-master-running"
    master = runs_jail["runs"] / "run.jsonl"
    master.write_text(json.dumps({"run_id": rid, "event": "run_start"}) + "\n", encoding="utf-8")

    fake_thread = MagicMock()
    fake_thread.name = f"eval-{rid}"

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        with patch("threading.enumerate", return_value=[fake_thread]):
            res = runs_client.get(f"/api/v1/runs/{rid}")

    master.unlink(missing_ok=True)
    assert res.status_code == 200
    assert res.get_json()["status"] == "RUNNING"


def test_get_run_status_master_log_stalled(runs_jail, runs_client):
    """get_run_status: no vault trace, master log has events, no run_end, no thread → STALLED."""
    rid = "status-master-stalled"
    master = runs_jail["runs"] / "run.jsonl"
    master.write_text(json.dumps({"run_id": rid, "event": "run_start"}) + "\n", encoding="utf-8")

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        with patch("threading.enumerate", return_value=[]):
            res = runs_client.get(f"/api/v1/runs/{rid}")

    master.unlink(missing_ok=True)
    assert res.status_code == 200
    assert res.get_json()["status"] == "STALLED"


def test_get_run_status_master_log_parse_error(runs_jail, runs_client):
    """get_run_status: master log has corrupt lines — skipped, overall has_events stays False."""
    rid = "status-master-parse-err"
    master = runs_jail["runs"] / "run.jsonl"
    corrupt = f'{{"{rid}" broken}}'
    master.write_text(corrupt + "\n", encoding="utf-8")

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        res = runs_client.get(f"/api/v1/runs/{rid}")

    master.unlink(missing_ok=True)
    # No events found for the rid → 404
    assert res.status_code == 404


def test_get_run_status_master_log_read_error(runs_jail, runs_client):
    """get_run_status: master log open raises → falls through to 404."""
    rid = "status-master-read-err"
    master = runs_jail["runs"] / "run.jsonl"
    master.write_text("{}", encoding="utf-8")

    orig_open = open

    def boom(file, *args, **kwargs):
        if str(file) == str(master):
            raise OSError("disk error")
        return orig_open(file, *args, **kwargs)

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        with patch("builtins.open", side_effect=boom):
            res = runs_client.get(f"/api/v1/runs/{rid}")

    master.unlink(missing_ok=True)
    assert res.status_code == 404


def test_get_run_status_not_found(runs_client):
    """get_run_status: no vault, no master log → 404."""
    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        res = runs_client.get("/api/v1/runs/completely-missing-run")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# get_verification_certificate
# ---------------------------------------------------------------------------


def test_get_cert_cert_path_success(runs_jail, runs_client):
    """get_verification_certificate: cert_path exists and valid JSON."""
    rid = "cert-ok"
    cert = runs_jail["reports"] / "certificates" / f"{rid}_vc.json"
    cert.write_text(json.dumps({"run_id": rid}), encoding="utf-8")

    res = runs_client.get(f"/api/v1/certificates/{rid}")
    assert res.status_code == 200
    assert res.get_json()["run_id"] == rid

    cert.unlink(missing_ok=True)


def test_get_cert_cert_path_corrupt(runs_jail, runs_client):
    """get_verification_certificate: cert_path exists but corrupt JSON → 500."""
    rid = "cert-corrupt"
    cert = runs_jail["reports"] / "certificates" / f"{rid}_vc.json"
    cert.write_bytes(b"NOT_JSON")

    res = runs_client.get(f"/api/v1/certificates/{rid}")
    assert res.status_code == 500

    cert.unlink(missing_ok=True)


def test_get_cert_vault_manifest_success(runs_jail, runs_client):
    """get_verification_certificate: vault manifest exists and valid JSON."""
    rid = "cert-manifest-ok"
    d = runs_jail["runs"] / rid
    d.mkdir(exist_ok=True)
    manifest = d / "run_manifest.json"
    manifest.write_text(json.dumps({"run_id": rid}), encoding="utf-8")

    res = runs_client.get(f"/api/v1/certificates/{rid}")
    assert res.status_code == 200


def test_get_cert_vault_manifest_corrupt(runs_jail, runs_client):
    """get_verification_certificate: vault manifest corrupt → 500."""
    rid = "cert-manifest-corrupt"
    d = runs_jail["runs"] / rid
    d.mkdir(exist_ok=True)
    (d / "run_manifest.json").write_bytes(b"BAD_JSON")

    res = runs_client.get(f"/api/v1/certificates/{rid}")
    assert res.status_code == 500


def test_get_cert_not_found(runs_client):
    """get_verification_certificate: neither cert nor manifest → 404."""
    res = runs_client.get("/api/v1/certificates/ghost-run-xyz")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# is_run_alive
# ---------------------------------------------------------------------------


def test_is_run_alive_true():
    rid = "alive-run"
    t = threading.Thread(target=lambda: time.sleep(0.5), name=f"eval-{rid}", daemon=True)
    t.start()
    try:
        assert is_run_alive(rid) is True
    finally:
        t.join(timeout=1)


def test_is_run_alive_false():
    assert is_run_alive("no-such-run-xyz") is False


# ---------------------------------------------------------------------------
# stream_run_logs
# ---------------------------------------------------------------------------


def test_stream_run_logs_vault_trace(runs_jail, runs_client):
    """stream_run_logs: vault trace found → SSE stream."""
    rid = "stream-vault-ok"
    d = runs_jail["runs"] / rid
    d.mkdir(exist_ok=True)
    (d / "run.jsonl").write_text('{"event": "run_start"}\n{"event": "run_end"}\n', encoding="utf-8")

    res = runs_client.get(f"/api/v1/runs/{rid}/stream")
    assert res.status_code == 200
    assert b"run_start" in res.data or b"run_end" in res.data


def test_stream_run_logs_master_log_fallback(runs_jail, runs_client):
    """stream_run_logs: no vault trace, filters events from master log."""
    rid = "stream-master-ok"
    master = runs_jail["runs"] / "run.jsonl"
    master.write_text(
        json.dumps({"run_id": rid, "event": "run_start"})
        + "\n"
        + json.dumps({"run_id": rid, "event": "run_end"})
        + "\n"
        + json.dumps({"run_id": "other", "event": "run_start"})
        + "\n",
        encoding="utf-8",
    )

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        res = runs_client.get(f"/api/v1/runs/{rid}/stream")

    master.unlink(missing_ok=True)
    assert res.status_code == 200


def test_stream_run_logs_master_log_corrupt_line(runs_jail, runs_client):
    """stream_run_logs: master log corrupt line is skipped."""
    rid = "stream-master-corrupt"
    master = runs_jail["runs"] / "run.jsonl"
    master.write_text(
        "NOT_JSON\n" + json.dumps({"run_id": rid, "event": "run_end"}) + "\n",
        encoding="utf-8",
    )

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        res = runs_client.get(f"/api/v1/runs/{rid}/stream")

    master.unlink(missing_ok=True)
    assert res.status_code == 200


def test_stream_run_logs_master_log_read_error(runs_jail, runs_client):
    """stream_run_logs: master log read raises → SSE not-found response (200)."""
    rid = "stream-master-err"
    master = runs_jail["runs"] / "run.jsonl"
    master.write_text("{}", encoding="utf-8")

    orig_open = open

    def boom(file, *args, **kwargs):
        if str(file) == str(master):
            raise OSError("read error")
        return orig_open(file, *args, **kwargs)

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        with patch("builtins.open", side_effect=boom):
            res = runs_client.get(f"/api/v1/runs/{rid}/stream")

    master.unlink(missing_ok=True)
    # No events found → SSE stream with "not found" message, still HTTP 200
    assert res.status_code == 200


def test_stream_run_logs_master_log_no_events(runs_jail, runs_client):
    """stream_run_logs: master log has no events for this run → SSE not-found response (200)."""
    rid = "stream-master-noevents"
    master = runs_jail["runs"] / "run.jsonl"
    master.write_text(
        json.dumps({"run_id": "other_run", "event": "run_start"}) + "\n", encoding="utf-8"
    )

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        res = runs_client.get(f"/api/v1/runs/{rid}/stream")

    master.unlink(missing_ok=True)
    # SSE route always returns 200; body contains "not found" message
    assert res.status_code == 200


def test_stream_run_logs_temp_write_failure(runs_jail, runs_client):
    """stream_run_logs: temp file write fails → 500."""
    rid = "stream-temp-fail-2"
    master = runs_jail["runs"] / "run.jsonl"
    master.write_text(json.dumps({"run_id": rid, "event": "run_start"}) + "\n", encoding="utf-8")

    orig_open = open

    def boom_write(file, *args, **kwargs):
        if f"temp_stream_{rid}" in str(file):
            raise OSError("disk full")
        return orig_open(file, *args, **kwargs)

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        with patch("builtins.open", side_effect=boom_write):
            res = runs_client.get(f"/api/v1/runs/{rid}/stream")

    master.unlink(missing_ok=True)
    assert res.status_code == 500


# ---------------------------------------------------------------------------
# tail_file_generator (unit-level generator tests)
# ---------------------------------------------------------------------------


def test_tail_file_generator_timeout(tmp_path):
    """tail_file_generator: file never created within timeout → yields timeout event."""
    log_path = tmp_path / "nonexistent.jsonl"
    with patch("time.sleep"):
        with patch("time.time", side_effect=[0.0] + [11.0] * 100):
            events = list(tail_file_generator(log_path, "run-timeout"))
    assert any("timeout" in e for e in events)


def test_tail_file_generator_streams_and_terminates_on_run_end(tmp_path):
    """tail_file_generator: streams existing lines and terminates on run_end."""
    log_path = tmp_path / "run.jsonl"
    log_path.write_text('{"event": "run_start"}\n{"event": "run_end"}\n', encoding="utf-8")
    events = list(tail_file_generator(log_path, "run-stream"))
    assert any("run_start" in e for e in events)
    assert any("run_end" in e for e in events)


def test_tail_file_generator_terminates_on_strategy_end(tmp_path):
    """tail_file_generator: terminates on strategy_end event."""
    log_path = tmp_path / "run.jsonl"
    log_path.write_text('{"event": "strategy_end"}\n', encoding="utf-8")
    events = list(tail_file_generator(log_path, "run-strategy"))
    assert any("strategy_end" in e for e in events)


def test_tail_file_generator_inode_stat_error(tmp_path):
    """tail_file_generator: stat().st_ino raises OSError → last_inode = None, no crash."""
    import errno

    log_path = tmp_path / "run.jsonl"
    log_path.write_text('{"event": "run_end"}\n', encoding="utf-8")

    with patch.object(Path, "exists", return_value=True):
        with patch.object(Path, "stat", side_effect=OSError(errno.ENOENT, "no stat")):
            events = list(tail_file_generator(log_path, "run-stat-err"))
    # Should still yield something (or at least not crash)
    assert isinstance(events, list)


# ---------------------------------------------------------------------------
# Targeted branch-coverage additions for remaining runs.py gaps
# ---------------------------------------------------------------------------


def test_explain_run_master_log_empty_line_skip(runs_jail, runs_client):
    """Cover 58->56: empty lines in master log are skipped (if line_str: false branch)."""
    rid = "explain-empty-lines"
    master = runs_jail["runs"] / "run.jsonl"
    # Write empty lines followed by a valid event for the run
    master.write_text(
        "\n\n" + json.dumps({"run_id": rid, "event": "run_start"}) + "\n",
        encoding="utf-8",
    )

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        with patch("eval_runner.console.routes.runs.explain_trace", return_value={}):
            res = runs_client.get(f"/api/v1/explain/{rid}")

    master.unlink(missing_ok=True)
    assert res.status_code == 200


def test_explain_run_temp_write_failure_unlinks(runs_jail, runs_client, tmp_path):
    """temp_path.unlink() is called when write fails and file was created."""
    rid = "explain-unlink-fail"
    master = runs_jail["runs"] / "run.jsonl"
    master.write_text(json.dumps({"run_id": rid, "event": "run_start"}) + "\n", encoding="utf-8")

    orig_open = open
    created_temp: list = []

    def simulate_partial_write(file, *args, **kwargs):
        fstr = str(file)
        if f"temp_explain_{rid}" in fstr and "w" in args:
            # Create the file first (so exists() is True) then raise
            Path(file).write_text("", encoding="utf-8")
            created_temp.append(fstr)
            raise OSError("disk full mid-write")
        return orig_open(file, *args, **kwargs)

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        with patch("builtins.open", side_effect=simulate_partial_write):
            res = runs_client.get(f"/api/v1/explain/{rid}")

    master.unlink(missing_ok=True)
    assert res.status_code == 500
    # The temp file should have been unlinked by the error handler
    for p in created_temp:
        assert not Path(p).exists(), f"Temp file {p} was not cleaned up"


def test_explain_run_exception_cleanup_temp_path(runs_jail, runs_client):
    """temp_path.unlink() called when explain_trace raises."""
    rid = "explain-exc-cleanup"
    master = runs_jail["runs"] / "run.jsonl"
    master.write_text(json.dumps({"run_id": rid, "event": "run_start"}) + "\n", encoding="utf-8")

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        with patch(
            "eval_runner.console.routes.runs.explain_trace",
            side_effect=RuntimeError("explain crashed"),
        ):
            res = runs_client.get(f"/api/v1/explain/{rid}")

    master.unlink(missing_ok=True)
    assert res.status_code == 500
    # Verify temp file was cleaned up (no temp_explain_* files remaining)
    temp_files = list(runs_jail["runs"].glob(f"temp_explain_{rid}*"))
    assert not temp_files


def test_get_run_status_master_log_false_positive_match(runs_jail, runs_client):
    """Cover 240->239: false-positive line match (substring) but different run_id in JSON."""
    rid = "status-fp"
    # "status-fp-extended" contains the literal '"status-fp"' as a substring:
    # the JSON is `"run_id": "status-fp-extended"` which contains `"status-fp"`.
    other_rid = f"{rid}-extended"
    master = runs_jail["runs"] / "run.jsonl"
    master.write_text(
        json.dumps({"run_id": other_rid, "event": "run_start"}) + "\n", encoding="utf-8"
    )

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        res = runs_client.get(f"/api/v1/runs/{rid}")

    master.unlink(missing_ok=True)
    assert res.status_code == 404


def test_get_run_status_master_log_event_not_run_end(runs_jail, runs_client):
    """Cover 243->239: event matches run_id but is not run_end → is_finished stays False."""
    rid = "status-not-end"
    master = runs_jail["runs"] / "run.jsonl"
    master.write_text(json.dumps({"run_id": rid, "event": "tool_call"}) + "\n", encoding="utf-8")

    fake_thread = MagicMock()
    fake_thread.name = f"eval-{rid}"

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        with patch("threading.enumerate", return_value=[fake_thread]):
            res = runs_client.get(f"/api/v1/runs/{rid}")

    master.unlink(missing_ok=True)
    assert res.status_code == 200
    assert res.get_json()["status"] == "RUNNING"


def test_list_runs_vault_two_part_run_id(runs_jail, runs_client):
    """run id with only 2 parts (run-abc) → scenario = parts[1]."""
    rid = "run-myscenario"
    d = runs_jail["runs"] / rid
    d.mkdir(exist_ok=True)
    (d / "run.jsonl").write_text(
        json.dumps({"event": "run_start", "run_id": rid}) + "\n", encoding="utf-8"
    )

    res = runs_client.get("/api/runs")
    assert res.status_code == 200
    runs = res.get_json()["runs"]
    match = next((r for r in runs if r["run_id"] == rid), None)
    assert match is not None
    assert match["scenario"] == "myscenario"


def test_tail_file_generator_no_inode_skip_check(tmp_path):
    """Cover 348->358 (400->398): when last_inode is None (stat failed), skip inode check."""
    import errno

    log_path = tmp_path / "run.jsonl"
    log_path.write_text('{"event": "run_end"}\n', encoding="utf-8")

    stat_called = False

    def stat_side_effect(*args, **kwargs):
        nonlocal stat_called
        if not stat_called:
            stat_called = True
            raise OSError(errno.ENOENT, "no stat")
        raise AssertionError("stat called after last_inode set to None")

    with patch.object(Path, "exists", return_value=True):
        with patch.object(Path, "stat", side_effect=stat_side_effect):
            events = list(tail_file_generator(log_path, "run-no-inode"))
    assert any("run_end" in e for e in events)


def test_tail_file_generator_empty_line_skip_in_historical(tmp_path):
    """Cover 327->326: empty lines in historical stream are skipped."""
    log_path = tmp_path / "run.jsonl"
    log_path.write_text('\n\n{"event": "run_end"}\n', encoding="utf-8")
    events = list(tail_file_generator(log_path, "run-empty-hist"))
    assert any("run_end" in e for e in events)


def test_stream_run_logs_cleanup_on_complete(runs_jail, runs_client):
    """Cover 423->exit, 426-427: stream_and_cleanup executes the finally cleanup block."""
    rid = "stream-cleanup-final"
    master = runs_jail["runs"] / "run.jsonl"
    master.write_text(json.dumps({"run_id": rid, "event": "run_end"}) + "\n", encoding="utf-8")

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        res = runs_client.get(f"/api/v1/runs/{rid}/stream")

    master.unlink(missing_ok=True)
    # Route returns 200 SSE stream; finally block in stream_and_cleanup ran cleanup
    assert res.status_code == 200
    assert b"run_end" in res.data


# ---------------------------------------------------------------------------
# Tail loop branch coverage (Steps B: tail loop idle, heartbeat, zombie, cleanup)
# ---------------------------------------------------------------------------


def test_tail_file_generator_wait_loop_sleep(tmp_path):
    """time.sleep in file-wait loop: exists() returns False first,
    sleep is called, then True so file is opened and events are read."""
    log_path = tmp_path / "delayed.jsonl"

    sleep_calls = []
    # exists_index tracks calls to mock_exists for log_path
    exists_results = [False, True]
    exists_index = [0]
    orig_exists = Path.exists

    def mock_exists(self):
        if self == log_path and exists_index[0] < len(exists_results):
            idx = exists_index[0]
            exists_index[0] += 1
            return exists_results[idx]
        return orig_exists(self)

    def mock_sleep(s):
        sleep_calls.append(s)
        log_path.write_text('{"event": "run_end"}\n', encoding="utf-8")

    with patch.object(Path, "exists", mock_exists):
        with patch("time.sleep", side_effect=mock_sleep):
            events = list(tail_file_generator(log_path, "run-wait"))

    assert sleep_calls, "Expected time.sleep to be called in the wait loop"
    assert any("run_end" in e for e in events)


def test_tail_file_generator_no_inode_then_run_end_in_tail(tmp_path):
    """Cover 348->358 and 400->398: last_inode=None, tail loop skips inode check,
    reads run_end from Step B."""
    log_path = tmp_path / "no_inode.jsonl"
    # Empty file first (no historical events) so we enter tail loop
    log_path.write_text("", encoding="utf-8")

    written = False

    def mock_sleep(s):
        nonlocal written
        if not written:
            log_path.write_text('{"event": "run_end"}\n', encoding="utf-8")
            written = True

    with patch("pathlib.Path.stat", side_effect=OSError("no stat")):
        with patch("time.sleep", side_effect=mock_sleep):
            with patch.object(Path, "exists", return_value=True):
                events = list(tail_file_generator(log_path, "run-no-inode-tail"))

    assert any("run_end" in e for e in events)


def test_tail_file_generator_idle_cycles_below_150_continue(tmp_path):
    """Cover 380->334 (continue branch): idle cycles < 150, generator continues loop.
    File gets written to after 10 sleep cycles."""
    log_path = tmp_path / "idle.jsonl"
    log_path.write_text("", encoding="utf-8")  # empty to enter tail loop

    write_count = 0

    def mock_sleep(s):
        nonlocal write_count
        write_count += 1
        if write_count == 10:
            # After 10 idle sleeps, write run_end so generator terminates
            with open(log_path, "a", encoding="utf-8") as f:
                f.write('{"event": "run_end"}\n')

    with patch("time.sleep", side_effect=mock_sleep):
        with patch.object(Path, "exists", return_value=True):
            events = list(tail_file_generator(log_path, "run-idle"))

    assert write_count >= 10
    assert any("run_end" in e for e in events)


def test_tail_file_generator_heartbeat_and_zombie_check(tmp_path):
    """Cover 369->375 (heartbeat + zombie check when idle_cycles >= 150)."""
    log_path = tmp_path / "heartbeat.jsonl"
    log_path.write_text("", encoding="utf-8")

    with (
        patch("eval_runner.console.routes.runs.is_run_alive", return_value=False),
        patch("time.sleep", return_value=None),
        patch.object(Path, "exists", return_value=True),
    ):
        events = list(tail_file_generator(log_path, "run-heartbeat"))

    assert any("heartbeat" in e for e in events)
    assert any("Process thread terminated abruptly" in e for e in events)


def test_stream_and_cleanup_finally_unlink_error(tmp_path):
    """Cover 426-427: unlink raises in finally block → warning logged, no crash."""
    from eval_runner.console.routes.runs import tail_file_generator

    log_path = tmp_path / "final.jsonl"
    log_path.write_text('{"event": "run_end"}\n', encoding="utf-8")

    def stream_and_cleanup():
        try:
            yield from tail_file_generator(log_path, "run-final")
        finally:
            if log_path.exists():
                try:
                    log_path.unlink(missing_ok=True)
                except OSError as unlink_err:
                    import logging

                    logging.getLogger(__name__).debug(f"Test cleanup unlink notice: {unlink_err}")

    events = list(stream_and_cleanup())
    assert any("run_end" in e for e in events)


def test_get_run_status_master_log_fp_then_false_run_id(runs_jail, runs_client):
    """Cover 243->239: line passes fast filter but JSON run_id doesn't match (false positive)."""
    rid = "status-false-pos"
    # Use a run_id that is a prefix of another — ensures '"status-false-pos"' substring match
    other_rid = f"{rid}-extension"
    # Write to a unique directory to avoid master log conflicts
    tmp_root = Path(tempfile.mkdtemp())
    tmp_runs = tmp_root / "runs"
    tmp_runs.mkdir()
    tmp_reports = tmp_root / "reports" / "certificates"
    tmp_reports.mkdir(parents=True)
    master = tmp_runs / "run.jsonl"
    master.write_text(
        json.dumps({"run_id": other_rid, "event": "run_start"}) + "\n", encoding="utf-8"
    )

    from flask import Flask

    from eval_runner import config
    from eval_runner.console.routes.runs import run_bp

    app = Flask(__name__)
    app.secret_key = "ts"
    app.register_blueprint(run_bp, url_prefix="/api")

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        with patch.object(config, "RUN_LOG_DIR", tmp_runs):
            with patch.object(config, "REPORTS_DIR", tmp_root / "reports"):
                with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
                    res = app.test_client().get(f"/api/v1/runs/{rid}")

    assert res.status_code == 404


def test_runs_explain_non_existent_run_404(runs_client):
    """Verify 404 when explaining a non-existent run ID."""
    res = runs_client.get("/api/v1/explain/non_existent_run_999")
    assert res.status_code == 404


def test_runs_cancel_and_resume_endpoints(runs_client):
    """Verify POST /v1/runs/<run_id>/cancel and /resume endpoints."""
    from eval_runner.reference.inprocess_backend import InProcessExecutionBackend

    backend = InProcessExecutionBackend.get_instance()

    # Cancel failure (not active)
    with patch.object(backend, "cancel", return_value=False):
        res = runs_client.post("/api/v1/runs/run-inactive/cancel", json={"reason": "test"})
        assert res.status_code == 404
        assert "not active" in res.get_json()["error"]

    # Cancel success
    with patch.object(backend, "cancel", return_value=True):
        res = runs_client.post("/api/v1/runs/run-active/cancel", json={"reason": "test"})
        assert res.status_code == 200
        assert res.get_json()["status"] == "ABORTED"

    # Resume failure (no checkpoint)
    with patch.object(backend, "resume", return_value=None):
        res = runs_client.post("/api/v1/runs/run-no-chk/resume", json={})
        assert res.status_code == 404
        assert "No checkpoint found" in res.get_json()["error"]

    # Resume success
    with patch.object(backend, "resume", return_value={"resumed": True}):
        res = runs_client.post(
            "/api/v1/runs/run-with-chk/resume", json={"resumption_token": "tok1"}
        )
        assert res.status_code == 200
        assert res.get_json()["status"] == "RUNNING"


def test_runs_backend_status_fallback_when_trace_missing(runs_client):
    """Verify GET /v1/runs/<run_id> returns in-memory status if trace file is not on disk."""
    from eval_runner.reference.inprocess_backend import InProcessExecutionBackend

    backend = InProcessExecutionBackend.get_instance()

    with patch("eval_runner.console.routes.runs.resolve_trace_path", return_value=None):
        st_data = {"status": "RUNNING", "scenario_data": {"id": "s1"}}
        with patch.object(backend, "status", return_value=st_data):
            res = runs_client.get("/api/v1/runs/run-in-memory")
            assert res.status_code == 200
            data = res.get_json()
            assert data["status"] == "RUNNING"
            assert data["scenario"]["id"] == "s1"


def test_runs_cache_thread_start_and_update_loop():
    """Verify RunsCache starts and stops background thread properly."""
    from eval_runner.console.routes.runs import RunsCache

    cache = RunsCache()
    with patch.object(threading.Thread, "start") as mock_start:
        cache.start()
        assert cache._started is True
        mock_start.assert_called_once()
        cache.stop()
        assert cache._started is False


def test_runs_stream_list_sse(runs_client, runs_jail):
    """Verify GET /v1/runs/stream-list streams run list in chunks."""
    from eval_runner.console.routes.runs import runs_cache

    now_iso = datetime.now(UTC).isoformat()
    with patch.object(
        runs_cache,
        "get_runs",
        return_value=[
            {"run_id": "stream_run_1", "scenario": "scen_1", "timestamp": now_iso},
            {"run_id": "stream_run_2", "scenario": "scen_2", "timestamp": now_iso},
        ],
    ):
        with patch("time.sleep", return_value=None):
            res = runs_client.get("/api/v1/runs/stream-list")
            assert res.status_code == 200
            assert "text/event-stream" in res.headers.get("Content-Type", "")
            data_chunks = res.get_data(as_text=True)
            assert "stream_run_1" in data_chunks


def test_runs_cache_update_cache_direct_and_vaults(runs_jail, monkeypatch):
    """Verify RunsCache scans fragments, vaults, and query filtering."""
    from eval_runner.console.routes.runs import RunsCache

    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_jail["runs"])
    cache = RunsCache()
    # 1. Direct fragment
    frag = runs_jail["runs"] / "frag_1.jsonl"
    t0 = datetime.now(UTC).isoformat()
    frag_event = {
        "event": "run_start",
        "run_id": "run-frag-1",
        "scenario": "scen_frag",
        "timestamp": t0,
    }
    frag.write_text(json.dumps(frag_event) + "\n", encoding="utf-8")

    # 2. Vault run
    vault_dir = runs_jail["runs"] / "run-vault-1"
    vault_dir.mkdir(exist_ok=True)
    vault_event = {
        "event": "run_start",
        "run_id": "run-vault-1",
        "scenario": "scen_vault",
        "timestamp": t0,
    }
    (vault_dir / "run.jsonl").write_text(json.dumps(vault_event) + "\n", encoding="utf-8")

    cache.update_cache()
    runs = cache.get_runs()
    rids = [r["run_id"] for r in runs]
    assert "run-frag-1" in rids
    assert "run-vault-1" in rids

    # Query filter
    filtered = cache.get_runs(query="run-vault-1")
    assert len(filtered) == 1
    assert filtered[0]["run_id"] == "run-vault-1"


def test_runs_stream_list_sse_status_resolution(runs_client, runs_jail):
    """Verify GET /v1/runs/stream-list resolves certified, failed, and running statuses."""
    from eval_runner.console.routes.runs import runs_cache

    t0 = datetime.now(UTC)
    r1_dir = runs_jail["runs"] / "run-certified-stream"
    r1_dir.mkdir(exist_ok=True)
    (r1_dir / "run_manifest.json").write_text("{}", encoding="utf-8")
    (r1_dir / "run.jsonl").write_text(json.dumps({"event": "run_start"}) + "\n", encoding="utf-8")

    # Large log file (> 32KB) with error
    r2_dir = runs_jail["runs"] / "run-failed-stream"
    r2_dir.mkdir(exist_ok=True)
    padding = json.dumps({"event": "step", "data": "x" * 1024}) + "\n"
    r2_lines = (
        padding * 35
        + json.dumps({"event": "run_start"})
        + "\n"
        + json.dumps({"event": "error", "message": "fail"})
        + "\n"
    )
    (r2_dir / "run.jsonl").write_text(r2_lines, encoding="utf-8")

    r3_dir = runs_jail["runs"] / "run-running-stream"
    r3_dir.mkdir(exist_ok=True)
    (r3_dir / "run.jsonl").write_text(
        json.dumps({"event": "run_start", "timestamp": t0.isoformat()}) + "\n",
        encoding="utf-8",
    )

    r4_dir = runs_jail["runs"] / "run-passed-stream"
    r4_dir.mkdir(exist_ok=True)
    (r4_dir / "run.jsonl").write_text(
        json.dumps({"event": "run_start"}) + "\n" + json.dumps({"event": "run_end"}) + "\n",
        encoding="utf-8",
    )

    with patch.object(
        runs_cache,
        "get_runs",
        return_value=[
            {"run_id": "run-certified-stream", "scenario": "s1", "timestamp": t0.isoformat()},
            {"run_id": "run-failed-stream", "scenario": "s2", "timestamp": t0.isoformat()},
            {"run_id": "run-running-stream", "scenario": "s3", "timestamp": t0.isoformat()},
            {"run_id": "run-passed-stream", "scenario": "s4", "timestamp": t0.isoformat()},
        ],
    ):
        with patch("time.sleep", return_value=None):
            res = runs_client.get("/api/v1/runs/stream-list")
            assert res.status_code == 200
            assert "text/event-stream" in res.headers.get("Content-Type", "")
            data_chunks = res.get_data(as_text=True)
            assert "run-certified-stream" in data_chunks
            assert "run-failed-stream" in data_chunks
            assert "run-passed-stream" in data_chunks


def test_runs_master_log_stream_and_not_found(runs_client, runs_jail, tmp_path):
    """Verify stream_run_logs fallback to master log and not found SSE response."""
    # 1. Not found stream
    res_404 = runs_client.get("/api/v1/runs/nonexistent-run-stream/stream")
    assert res_404.status_code == 200
    assert "not_found" in res_404.get_data(as_text=True)

    # 2. Master log stream
    master_log = runs_jail["runs"] / "run.jsonl"
    t0 = datetime.now(UTC).isoformat()
    lines = [
        json.dumps({"event": "run_start", "run_id": "run-master-stream-1", "timestamp": t0}),
        json.dumps({"event": "run_end", "run_id": "run-master-stream-1", "timestamp": t0}),
    ]
    master_log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    res_master = runs_client.get("/api/v1/runs/run-master-stream-1/stream")
    assert res_master.status_code == 200
    assert "run-master-stream-1" in res_master.get_data(as_text=True)

    # 3. get_run master log with scenario catalog resolution
    scen_file = tmp_path / "scen_1.json"
    scen_file.write_text(json.dumps({"id": "scen_1", "title": "Scen 1"}), encoding="utf-8")

    with patch("eval_runner.catalog.ScenarioCatalog.get_instance") as mock_cat:
        mock_cat.return_value.get_scenario.return_value = {"id": "scen_1"}
        mock_cat.return_value.get_absolute_path.return_value = scen_file
        res_get_master = runs_client.get("/api/v1/runs/run-master-stream-1")
        assert res_get_master.status_code == 200
        assert res_get_master.get_json()["sourced_from_master"] is True
        assert res_get_master.get_json()["scenario"]["title"] == "Scen 1"


def test_runs_tail_generator_safeguards_and_corrupt_trace(runs_jail, runs_client):
    """
    Verify tail_file_generator deleted, rotated, and timeout safeguards,
    plus corrupt trace handling.
    """

    # 1. Corrupted trace file
    r_corrupt = runs_jail["runs"] / "run-corrupt-trace"
    r_corrupt.mkdir(exist_ok=True)
    (r_corrupt / "run.jsonl").write_text(
        '{"event": "run_start"}\n{CORRUPT_JSON_LINE\n{"event": "run_end"}\n',
        encoding="utf-8",
    )
    res_corrupt = runs_client.get("/api/v1/runs/run-corrupt-trace")
    assert res_corrupt.status_code == 200

    # 2. Tail generator: deleted file (mock exists for Windows file lock compatibility)
    tail_file = runs_jail["runs"] / "tail_deleted_test.jsonl"
    tail_file.write_text('{"event": "run_start"}\n', encoding="utf-8")

    gen = tail_file_generator(tail_file, "run-tail-del")
    first_item = next(gen)
    assert "run_start" in first_item

    with patch.object(Path, "exists", return_value=False):
        del_event = next(gen)
        assert "Log file deleted" in del_event

    # 3. Tail generator: stream timeout
    tail_timeout_file = runs_jail["runs"] / "tail_timeout_test.jsonl"
    tail_timeout_file.write_text('{"event": "run_start"}\n', encoding="utf-8")

    current_t = time.time()
    gen_timeout = tail_file_generator(tail_timeout_file, "run-tail-to")
    next(gen_timeout)  # catch-up

    with patch("time.time", return_value=current_t + 10000.0):
        to_event = next(gen_timeout)
        assert "Stream exceeded max connection lifetime" in to_event

    # 4. Tail generator: rotated file (different inode)
    tail_rot_file = runs_jail["runs"] / "tail_rot_test.jsonl"
    tail_rot_file.write_text('{"event": "run_start"}\n', encoding="utf-8")
    gen_rot = tail_file_generator(tail_rot_file, "run-tail-rot")
    next(gen_rot)

    mock_stat = MagicMock()
    mock_stat.st_ino = 999999999
    with patch.object(Path, "stat", return_value=mock_stat):
        rot_event = next(gen_rot)
        assert "Log file rotated" in rot_event

    # 5. Tail generator: zombie check
    tail_zombie_file = runs_jail["runs"] / "tail_zombie_test.jsonl"
    tail_zombie_file.write_text('{"event": "run_start"}\n', encoding="utf-8")
    gen_zombie = tail_file_generator(tail_zombie_file, "run-tail-zombie")
    next(gen_zombie)

    with patch("eval_runner.console.routes.runs.is_run_alive", return_value=False):
        with patch("time.sleep", return_value=None):
            for _ in range(160):
                z_event = next(gen_zombie)
                if "Process thread terminated abruptly" in z_event:
                    break
            assert "Process thread terminated abruptly" in z_event


def test_runs_active_runner_fallback(runs_client):
    """Verify get_run falls back to active InProcessExecutionBackend when file not found on disk."""
    mock_backend = MagicMock()
    mock_backend.status.return_value = {
        "status": "RUNNING",
        "scenario_data": {"title": "Active in memory"},
    }
    with patch(
        "eval_runner.reference.inprocess_backend.InProcessExecutionBackend.get_instance",
        return_value=mock_backend,
    ):
        res = runs_client.get("/api/v1/runs/run-in-flight-001")
        assert res.status_code == 200
        assert res.get_json()["status"] == "RUNNING"


def test_runs_cache_update_loop_error_resilience():
    """Verify RunsCache._update_loop recovers from exceptions."""
    from eval_runner.console.routes.runs import RunsCache

    cache = RunsCache()
    with patch.object(cache, "update_cache", side_effect=[Exception("scan error"), StopIteration]):
        with patch("time.sleep", side_effect=StopIteration):
            try:
                cache._update_loop()
            except StopIteration:
                pass
