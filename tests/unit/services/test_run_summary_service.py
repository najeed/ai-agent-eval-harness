"""
tests/unit/services/test_run_summary_service.py
Unit tests for RunSummaryService in eval_runner.services.run_summary.
"""

from __future__ import annotations

import time
from datetime import datetime
from unittest.mock import patch

from eval_runner.services.run_summary import RunSummaryService


def test_get_authoritative_verdict_branches(tmp_path, monkeypatch):
    # 1. Empty run_id
    assert RunSummaryService.get_authoritative_verdict("") == "NOT_EXECUTED"

    # 2. Non-existent trace path
    monkeypatch.setattr(
        "eval_runner.services.run_summary.resolve_trace_path",
        lambda *args, **kwargs: None,
    )
    assert RunSummaryService.get_authoritative_verdict("run_no_trace") == "NOT_EXECUTED"

    # 3. Trace exists, but locate_certificate_file returns None
    trace_file = tmp_path / "run.jsonl"
    trace_file.write_text('{"event": "task_completed"}\n', encoding="utf-8")
    monkeypatch.setattr(
        "eval_runner.services.run_summary.resolve_trace_path",
        lambda *args, **kwargs: trace_file,
    )
    with patch("eval_runner.verifier.locate_certificate_file", return_value=None):
        assert RunSummaryService.get_authoritative_verdict("run_no_cert") == "UNKNOWN"

    # 4. Manifest exists, but TraceVerifier returns False
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text('{"provisional": false}\n', encoding="utf-8")
    with (
        patch("eval_runner.verifier.locate_certificate_file", return_value=manifest_file),
        patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=False),
    ):
        assert RunSummaryService.get_authoritative_verdict("run_bad_cert") == "FAILED_VERIFICATION"

    # 5. Manifest exists, TraceVerifier returns True, provisional is True
    manifest_prov = tmp_path / "manifest_prov.json"
    manifest_prov.write_text('{"provisional": true}\n', encoding="utf-8")
    with (
        patch("eval_runner.verifier.locate_certificate_file", return_value=manifest_prov),
        patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=True),
    ):
        assert RunSummaryService.get_authoritative_verdict("run_prov") == "VERIFIED_PROVISIONAL"

    # 6. Manifest exists, TraceVerifier returns True, authoritative (not provisional)
    manifest_auth = tmp_path / "manifest_auth.json"
    manifest_auth.write_text('{"provisional": false, "execution_mode": "live"}\n', encoding="utf-8")
    with (
        patch("eval_runner.verifier.locate_certificate_file", return_value=manifest_auth),
        patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=True),
    ):
        assert RunSummaryService.get_authoritative_verdict("run_auth") == "VERIFIED"

    # 7. TraceVerifier raises Exception -> ERROR
    def failing_verify(*args, **kwargs):
        raise RuntimeError("Ledger cryptographic parsing exploded")

    with (
        patch("eval_runner.verifier.locate_certificate_file", return_value=manifest_auth),
        patch("eval_runner.verifier.TraceVerifier.verify_trace", failing_verify),
    ):
        assert RunSummaryService.get_authoritative_verdict("run_err") == "ERROR"


def test_compute_summary_certified_and_provisional(tmp_path, monkeypatch):
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("eval_runner.config.REPORTS_DIR", tmp_path / "reports")

    # 1. VERIFIED -> CERTIFIED
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="VERIFIED"):
        summary = RunSummaryService.compute_summary("run_1", cached_entry={"scenario": "scen_1"})
        assert summary["status"] == "CERTIFIED"
        assert summary["lifecycle"] == "SEALED"
        assert summary["verification_status"] == "VERIFIED"

    # 2. VERIFIED_PROVISIONAL -> PROVISIONAL
    with patch.object(
        RunSummaryService, "get_authoritative_verdict", return_value="VERIFIED_PROVISIONAL"
    ):
        summary = RunSummaryService.compute_summary("run_2", cached_entry={"scenario": "scen_2"})
        assert summary["status"] == "PROVISIONAL"
        assert summary["lifecycle"] == "SEALED"


def test_compute_summary_artifact_present_and_missing_trace(tmp_path, monkeypatch):
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs")
    reports_dir = tmp_path / "reports"
    monkeypatch.setattr("eval_runner.config.REPORTS_DIR", reports_dir)

    cert_dir = reports_dir / "certificates"
    cert_dir.mkdir(parents=True, exist_ok=True)
    (cert_dir / "run_art_vc.json").write_text("{}", encoding="utf-8")

    # 1. Certificate exists on disk, but verdict is UNKNOWN -> ARTIFACT_PRESENT
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        summary = RunSummaryService.compute_summary("run_art")
        assert summary["status"] == "ARTIFACT_PRESENT"
        assert summary["lifecycle"] == "COMPLETED"

    # 2. No certificate, no trace, recent timestamp -> RUNNING
    with (
        patch.object(RunSummaryService, "get_authoritative_verdict", return_value="NOT_EXECUTED"),
        patch(
            "eval_runner.services.run_summary.resolve_trace_path",
            return_value=None,
        ),
    ):
        recent_ts = datetime.fromtimestamp(time.time() - 10).isoformat()
        summary_recent = RunSummaryService.compute_summary(
            "run_recent", cached_entry={"timestamp": recent_ts}
        )
        assert summary_recent["status"] == "RUNNING"

        # 3. No certificate, no trace, stale timestamp -> STALLED
        old_ts = datetime.fromtimestamp(time.time() - 500).isoformat()
        summary_stale = RunSummaryService.compute_summary(
            "run_stale", cached_entry={"timestamp": old_ts}
        )
        assert summary_stale["status"] == "STALLED"


def test_compute_summary_trace_states(tmp_path, monkeypatch):
    run_dir = tmp_path / "runs" / "run_states"
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_path = run_dir / "run.jsonl"
    trace_path.write_text('{"event": "task"}\n', encoding="utf-8")
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("eval_runner.config.REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(
        "eval_runner.services.run_summary.resolve_trace_path",
        lambda *args, **kwargs: trace_path,
    )
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        # 1. Sealed file indicator
        (run_dir / ".sealed").write_text("sealed", encoding="utf-8")
        with patch("eval_runner.verifier.locate_certificate_file", return_value=trace_path):
            summary_sealed = RunSummaryService.compute_summary("run_states")
            assert summary_sealed["status"] == "SEALED"
            assert summary_sealed["lifecycle"] == "SEALED"

        (run_dir / ".sealed").unlink()

        # 2. Cached result_status PASS
        summary_pass = RunSummaryService.compute_summary(
            "run_states", cached_entry={"result_status": "PASS"}
        )
        assert summary_pass["status"] == "PASSED"
        assert summary_pass["lifecycle"] == "COMPLETED"

        # 3. Cached result_status FAIL
        summary_fail = RunSummaryService.compute_summary(
            "run_states", cached_entry={"result_status": "FAIL"}
        )
        assert summary_fail["status"] == "FAILED"
        assert summary_fail["lifecycle"] == "FAILED"

        # 4. Trace tail with error event
        trace_path.write_text('{"event": "error", "message": "boom"}\n', encoding="utf-8")
        summary_err = RunSummaryService.compute_summary("run_states")
        assert summary_err["status"] == "FAILED"

        # 5. Trace tail with run_end (clean)
        trace_path.write_text('{"event": "run_end", "data": {}}\n', encoding="utf-8")
        summary_end = RunSummaryService.compute_summary("run_states")
        assert summary_end["status"] == "PASSED"

        # 6. Trace reading error
        def failing_open(*args, **kwargs):
            raise OSError("I/O failure reading trace")

        with patch("builtins.open", failing_open):
            summary_io = RunSummaryService.compute_summary("run_states")
            assert summary_io["status"] == "RUNNING"

        # 7. Trace file > 32KB
        large_bytes = b" " * (33 * 1024) + b'{"event": "run_end"}\n'
        trace_path.write_bytes(large_bytes)
        summary_large = RunSummaryService.compute_summary("run_states")
        assert summary_large["status"] == "PASSED"

        # 8. Trace empty (size == 0)
        trace_path.write_bytes(b"")
        summary_empty = RunSummaryService.compute_summary("run_states")
        assert summary_empty["status"] == "RUNNING"

        # 9. Trace active, no end, mtime recent vs stalled
        trace_path.write_text('{"event": "step_1"}\n', encoding="utf-8")
        summary_active = RunSummaryService.compute_summary("run_states")
        assert summary_active["status"] == "RUNNING"

        # 9b. Stalled active trace (mtime > 300s ago)
        with patch("os.path.getmtime", return_value=time.time() - 400):
            summary_stalled = RunSummaryService.compute_summary("run_states")
            assert summary_stalled["status"] == "STALLED"

        # 10. Trace with both run_end and error event
        trace_path.write_text(
            '{"event": "error", "message": "fail"}\n{"event": "run_end"}\n', encoding="utf-8"
        )
        summary_end_err = RunSummaryService.compute_summary("run_states")
        assert summary_end_err["status"] == "FAILED"


def test_run_summary_additional_branches(tmp_path, monkeypatch):
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("eval_runner.config.REPORTS_DIR", tmp_path / "reports")

    # 1. Provisional check exception in get_authoritative_verdict
    manifest_bad = tmp_path / "manifest_bad.json"
    manifest_bad.write_text("invalid json {", encoding="utf-8")
    with (
        patch("eval_runner.verifier.locate_certificate_file", return_value=manifest_bad),
        patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=True),
        patch(
            "eval_runner.services.run_summary.resolve_trace_path",
            return_value=manifest_bad,
        ),
    ):
        verdict = RunSummaryService.get_authoritative_verdict("run_bad_json_man")
        assert verdict == "VERIFIED"

    # 2. cached_exec_mode present and path/fragment_path present
    rel_path = tmp_path / "runs" / "custom" / "run.jsonl"
    rel_path.parent.mkdir(parents=True, exist_ok=True)
    rel_path.write_text('{"event": "run_end"}\n', encoding="utf-8")

    cached_entry = {
        "execution_mode": "simulated",
        "path": "custom/run.jsonl",
        "_fragment_path": "frag.jsonl",
    }
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        s = RunSummaryService.compute_summary("run_custom", cached_entry=cached_entry)
        assert s["execution_mode"] == "simulated"
        assert s["provisional"] is True
        assert s["_fragment_path"] == "frag.jsonl"
        assert s["path"] == "custom/run.jsonl"

    # 3. Invalid timestamp parsing with no trace
    with (
        patch.object(RunSummaryService, "get_authoritative_verdict", return_value="NOT_EXECUTED"),
        patch("eval_runner.services.run_summary.resolve_trace_path", return_value=None),
    ):
        s_bad_ts = RunSummaryService.compute_summary(
            "run_bad_ts", cached_entry={"timestamp": "not-a-timestamp"}
        )
        assert s_bad_ts["status"] == "STALLED"
