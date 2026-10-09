"""
tests/unit/services/test_run_summary_service.py
Unit tests for RunSummaryService in eval_runner.services.run_summary.
"""

from __future__ import annotations

import json
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
    (cert_dir / "run_art_vc.json").write_text(
        json.dumps({"vc_version": "3.0.0", "trace_hash": "sha3_256:test"}),
        encoding="utf-8",
    )

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

        # Cached indexes are not authoritative execution truth.
        summary_pass = RunSummaryService.compute_summary(
            "run_states", cached_entry={"result_status": "PASS"}
        )
        assert summary_pass["status"] == "RUNNING"
        assert summary_pass["lifecycle"] == "RUNNING"

        # Nor may cached FAIL override the parsed trace.
        summary_fail = RunSummaryService.compute_summary(
            "run_states", cached_entry={"result_status": "FAIL"}
        )
        assert summary_fail["status"] == "RUNNING"
        assert summary_fail["lifecycle"] == "RUNNING"

        # A non-terminal error is not a final verdict.
        trace_path.write_text('{"event": "error", "message": "boom"}\n', encoding="utf-8")
        summary_err = RunSummaryService.compute_summary("run_states")
        assert summary_err["status"] == "RUNNING"

        # Terminal outcome is typed and parsed, not inferred from a marker.
        trace_path.write_text('{"event": "run_end", "data": {"passed": true}}\n', encoding="utf-8")
        summary_end = RunSummaryService.compute_summary("run_states")
        assert summary_end["status"] == "PASSED"

        # 6. Trace reading error
        def failing_open(*args, **kwargs):
            raise OSError("I/O failure reading trace")

        with patch("builtins.open", failing_open):
            summary_io = RunSummaryService.compute_summary("run_states")
            assert summary_io["status"] == "INVALID"
            assert summary_io["trace_integrity"] == "INVALID"

        # 7. Large traces are parsed in full; a prior failed retry does not
        # override the terminal PASS.
        large_bytes = (
            b'{"event":"assertion_evaluated","data":{"passed":false}}\n'
            + b" " * (33 * 1024)
            + b'{"event":"run_end","data":{"passed":true}}\n'
        )
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

        # 10. A failed terminal outcome remains failed.
        trace_path.write_text(
            '{"event": "error", "message": "fail"}\n'
            '{"event": "run_end", "data": {"passed": false}}\n',
            encoding="utf-8",
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


def test_parsed_terminal_state_framed_log_and_edge_outcomes(tmp_path, monkeypatch):
    run_dir = tmp_path / "runs" / "framed_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_file = run_dir / "run.jsonl"

    # Mock json.loads so that a line parses to a non-dict list, covering 95->90
    import json as json_mod

    orig_loads = json_mod.loads

    def mock_loads(s):
        if "non_dict_candidate" in s:
            return ["not", "a", "dict"]
        return orig_loads(s)

    monkeypatch.setattr(json_mod, "loads", mock_loads)

    # 1. Framed log with non-dict candidate and certification_failed terminal event
    trace_file.write_text(
        "Framed log prefix without json\n"
        '[DEBUG] {"non_dict_candidate": 1}\n'
        '[INFO] {"event": "certification_failed", "error": "Signature rejected"}\n',
        encoding="utf-8",
    )
    st, lc, integ = RunSummaryService._parsed_terminal_state(trace_file, "framed_run")
    assert st == "FAILED"
    assert lc == "FAILED"
    assert integ == "COMPLETE"

    # 2. Framed log with unrecognized outcome on non-run_end terminal event
    trace_file.write_text(
        "Framed log prefix\n"
        '[WARN] {"event": "workflow_verdict", "data": {"verdict": "INDECISIVE"}}\n',
        encoding="utf-8",
    )
    st2, lc2, integ2 = RunSummaryService._parsed_terminal_state(trace_file, "framed_run")
    assert st2 == "INVALID"
    assert lc2 == "INVALID"
    assert integ2 == "INVALID"


def test_compute_summary_path_and_timestamp_edge_cases(tmp_path, monkeypatch):
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("eval_runner.config.REPORTS_DIR", tmp_path / "reports")

    # 1. cached path does not exist on disk (falls back to resolve_trace_path)
    with (
        patch.object(RunSummaryService, "get_authoritative_verdict", return_value="NOT_EXECUTED"),
        patch("eval_runner.services.run_summary.resolve_trace_path", return_value=None),
    ):
        s_no_path = RunSummaryService.compute_summary(
            "run_missing_cand",
            cached_entry={"path": "does_not_exist/run.jsonl"},
        )
        assert s_no_path["status"] == "NOT_EXECUTED"

    # 2. Trace exists: identifier absent -> extracted; timestamp provided
    run_dir = tmp_path / "runs" / "run_hydrate"
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_file = run_dir / "run.jsonl"
    trace_file.write_text(
        '{"timestamp": "2026-10-09T01:00:00Z", "metadata": {"identifier": "RunIdentifier-01"}}\n'
        '{"event": "run_end", "data": {"passed": true}}\n',
        encoding="utf-8",
    )
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        s_hydrate_id = RunSummaryService.compute_summary(
            "run_hydrate",
            cached_entry={"timestamp": "2026-10-09T01:00:00Z", "path": "run_hydrate/run.jsonl"},
        )
        assert s_hydrate_id["identifier"] == "RunIdentifier-01"

        # 3. Trace exists: timestamp absent -> extracted; identifier provided
        s_hydrate_ts = RunSummaryService.compute_summary(
            "run_hydrate",
            cached_entry={"identifier": "CustomID", "path": "run_hydrate/run.jsonl"},
        )
        assert s_hydrate_ts["timestamp"] == "2026-10-09T01:00:00Z"

        # 4. Exception opening trace for first line extraction
        with patch("builtins.open", side_effect=OSError("Disk read failure")):
            s_open_err = RunSummaryService.compute_summary(
                "run_hydrate",
                cached_entry={"path": "run_hydrate/run.jsonl"},
            )
            assert s_open_err["status"] == "INVALID"


def test_compute_summary_score_extraction_hierarchy(tmp_path, monkeypatch):
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs")
    reports_dir = tmp_path / "reports"
    monkeypatch.setattr("eval_runner.config.REPORTS_DIR", reports_dir)

    cert_dir = reports_dir / "certificates"
    cert_dir.mkdir(parents=True, exist_ok=True)
    run_dir = tmp_path / "runs" / "run_score"
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_file = run_dir / "run.jsonl"
    trace_file.write_text('{"event": "run_end", "data": {"passed": true}}\n', encoding="utf-8")

    # 1. Score in certificate root
    cert_file = cert_dir / "run_score_vc.json"
    cert_file.write_text(json.dumps({"score": 0.88, "vc_version": "3.0.0"}), encoding="utf-8")
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        s1 = RunSummaryService.compute_summary(
            "run_score", cached_entry={"path": "run_score/run.jsonl"}
        )
        assert s1["score"] == 0.88

    # 2. Score in certificate decision block
    cert_file.write_text(
        json.dumps({"decision": {"score": 0.77}, "vc_version": "3.0.0"}), encoding="utf-8"
    )
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        s2 = RunSummaryService.compute_summary(
            "run_score", cached_entry={"path": "run_score/run.jsonl"}
        )
        assert s2["score"] == 0.77

    # 2b. Certificate decision block without score (covers branch 273->279)
    cert_file.write_text(
        json.dumps({"decision": {"other_key": "val"}, "vc_version": "3.0.0"}), encoding="utf-8"
    )
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        s2b = RunSummaryService.compute_summary(
            "run_score", cached_entry={"path": "run_score/run.jsonl"}
        )
        assert s2b["score"] == 1.0  # Derived from passed status

    # 3. Corrupt certificate JSON triggers exception log
    cert_file.write_text("corrupted certificate {", encoding="utf-8")
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        s3 = RunSummaryService.compute_summary(
            "run_score", cached_entry={"path": "run_score/run.jsonl"}
        )
        assert s3["score"] == 1.0  # Derived from passed status

    cert_file.unlink()

    # 4. Package manifest root score via verification_package.json
    pkg_file = run_dir / "verification_package.json"
    pkg_file.write_text(json.dumps({"score": 0.92}), encoding="utf-8")
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        s4 = RunSummaryService.compute_summary(
            "run_score", cached_entry={"path": "run_score/run.jsonl"}
        )
        assert s4["score"] == 0.92

    # 5. Package manifest decision block score via verification_package.json
    pkg_file.write_text(json.dumps({"decision": {"score": 0.65}}), encoding="utf-8")
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        s5 = RunSummaryService.compute_summary(
            "run_score", cached_entry={"path": "run_score/run.jsonl"}
        )
        assert s5["score"] == 0.65

    # 5b. Package manifest decision without score (covers branch 291->297)
    pkg_file.write_text(json.dumps({"decision": {"other": 1}}), encoding="utf-8")
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        s5b = RunSummaryService.compute_summary(
            "run_score", cached_entry={"path": "run_score/run.jsonl"}
        )
        assert s5b["score"] == 1.0

    # 5c. Package manifest without score and without decision dict (covers branch 289->297)
    pkg_file.write_text(json.dumps({"other": 2}), encoding="utf-8")
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        s5c = RunSummaryService.compute_summary(
            "run_score", cached_entry={"path": "run_score/run.jsonl"}
        )
        assert s5c["score"] == 1.0

    # 6. Corrupt package manifest triggers exception log
    pkg_file.write_text("corrupt manifest {", encoding="utf-8")
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        s6 = RunSummaryService.compute_summary(
            "run_score", cached_entry={"path": "run_score/run.jsonl"}
        )
        assert s6["score"] == 1.0

    pkg_file.unlink()

    # 7. Fallback to run_manifest.json when verification_package.json does not exist
    run_man_file = run_dir / "run_manifest.json"
    run_man_file.write_text(
        json.dumps({"manifest_id": "man_run_score", "score": 0.85, "agent_config": {}}),
        encoding="utf-8",
    )
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        s7 = RunSummaryService.compute_summary(
            "run_score", cached_entry={"path": "run_score/run.jsonl"}
        )
        assert s7["score"] == 0.85

    run_man_file.unlink()

    # 7. Score derivation when status is unmapped
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        s_fail = RunSummaryService.compute_summary(
            "run_score_fail", cached_entry={"result_status": "FAIL"}
        )
        assert s_fail["score"] == 0.0


def test_compute_summary_duration_edge_cases(tmp_path, monkeypatch):
    run_dir = tmp_path / "runs" / "run_dur"
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_file = run_dir / "run.jsonl"
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("eval_runner.config.REPORTS_DIR", tmp_path / "reports")

    # 1. run_end carrying explicit duration with blank lines in trace
    trace_file.write_text(
        "\n\n"
        '{"timestamp": "2026-10-09T00:00:00Z", "event": "start"}\n'
        "Not a JSON line\n"
        '{"timestamp": "2026-10-09T00:00:15Z", "event": "run_end", '
        '"data": {"passed": true, "duration": 14.5}}\n',
        encoding="utf-8",
    )
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        s_dur = RunSummaryService.compute_summary(
            "run_dur", cached_entry={"path": "run_dur/run.jsonl"}
        )
        assert s_dur["duration_seconds"] == 14.5

    # 2. Trace without explicit duration derives from timestamps
    trace_file.write_text(
        '{"timestamp": "2026-10-09T00:00:00Z", "event": "start"}\n'
        '{"timestamp": "2026-10-09T00:00:10Z", "event": "run_end", "data": {"passed": true}}\n',
        encoding="utf-8",
    )
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        s_dur2 = RunSummaryService.compute_summary(
            "run_dur", cached_entry={"path": "run_dur/run.jsonl"}
        )
        assert s_dur2["duration_seconds"] == 10.0

    # 3. Inverted timestamps (dt1 < dt0) leaves duration_seconds None
    trace_file.write_text(
        '{"timestamp": "2026-10-09T00:00:20Z", "event": "start"}\n'
        '{"timestamp": "2026-10-09T00:00:10Z", "event": "run_end", "data": {"passed": true}}\n',
        encoding="utf-8",
    )
    with patch.object(RunSummaryService, "get_authoritative_verdict", return_value="UNKNOWN"):
        s_dur_inv = RunSummaryService.compute_summary(
            "run_dur", cached_entry={"path": "run_dur/run.jsonl"}
        )
        assert s_dur_inv["duration_seconds"] is None
