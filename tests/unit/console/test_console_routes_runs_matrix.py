"""
Branch coverage matrix for eval_runner/console/routes/runs.py.

Statement and branch coverage for RunsCache,
stream endpoints, authoritative verdicts, polling, tail generators,
and verification endpoints.
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.routes.runs import (
    RunsCache,
    _authoritative_verdict,
    run_bp,
    tail_file_generator,
)


@pytest.fixture
def client(tmp_path):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(run_bp)

    # Set temporary directories
    with (
        patch.object(config, "RUN_LOG_DIR", tmp_path / "runs"),
        patch.object(config, "REPORTS_DIR", tmp_path / "reports"),
    ):
        config.RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
        config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (config.REPORTS_DIR / "certificates").mkdir(parents=True, exist_ok=True)

        with app.test_client() as c:
            yield c


def test_runs_cache_lifecycle_and_edge_branches(tmp_path):
    # 1. autostart=True, start idempotency, and stop when not started
    cache = RunsCache(autostart=True)
    cache.start()  # Idempotent start
    time.sleep(0.05)
    cache.stop()
    cache.stop()  # Idempotent stop

    # 2. RUN_LOG_DIR is None or does not exist
    with patch.object(config, "RUN_LOG_DIR", tmp_path / "non_existent_dir"):
        cache.update_cache()
        assert cache._runs == []

    # 3. Fragment scanning with empty lines and parse exceptions
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    with patch.object(config, "RUN_LOG_DIR", runs_dir):
        frag_file = runs_dir / "frag1.jsonl"
        frag_file.write_text(
            "\n   \n"
            + json.dumps({"event": "run_start", "run_id": "run-f1", "scenario": "sc1"})
            + "\n"
            + "invalid_json_line\n",
            encoding="utf-8",
        )
        cache.update_cache()
        assert any(r["run_id"] == "run-f1" for r in cache.get_runs())

        # 4. Large vault run.jsonl (>= 512KB) and reversed line parsing
        vault_dir = runs_dir / "run-v1"
        vault_dir.mkdir(parents=True, exist_ok=True)
        v_file = vault_dir / "run.jsonl"
        start_ev = json.dumps({"event": "run_start", "run_id": "run-v1"}) + "\n"
        end_ev = json.dumps({"event": "run_end", "data": {"passed": True, "duration": 1.2}}) + "\n"
        padding = " " * (513 * 1024) + "\n"
        v_file.write_text(start_ev + padding + end_ev, encoding="utf-8")

        cache.update_cache()
        assert any(r["run_id"] == "run-v1" for r in cache.get_runs())

        # 5. Vault run without start scenario name fallback for single dash run id
        vault_dash = runs_dir / "run-scenonly"
        vault_dash.mkdir(parents=True, exist_ok=True)
        (vault_dash / "run.jsonl").write_text(
            json.dumps({"event": "run_start", "run_id": "run-scenonly"}) + "\n",
            encoding="utf-8",
        )
        cache.update_cache()


def test_authoritative_verdict_edge_cases(tmp_path):
    # 1. Empty run_id
    assert _authoritative_verdict("") == "NOT_EXECUTED"

    # 2. Corrupt or unparseable manifest -> ERROR
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_vault = runs_dir / "run-corrupt-manifest"
    run_vault.mkdir(parents=True, exist_ok=True)
    (run_vault / "run.jsonl").write_text('{"event":"start"}\n', encoding="utf-8")
    (run_vault / "run_manifest.json").write_text("corrupted_json_content", encoding="utf-8")

    with patch.object(config, "RUN_LOG_DIR", runs_dir):
        assert _authoritative_verdict("run-corrupt-manifest") == "ERROR"


def test_stream_runs_list_branches(client, tmp_path):
    runs_dir = tmp_path / "runs"
    rep_dir = tmp_path / "reports" / "certificates"
    runs_dir.mkdir(parents=True, exist_ok=True)
    rep_dir.mkdir(parents=True, exist_ok=True)

    # 1. Verified run yielding CERTIFIED
    run_cert = runs_dir / "run-cert"
    run_cert.mkdir(parents=True, exist_ok=True)
    trace_file = run_cert / "run.jsonl"
    trace_file.write_text('{"event":"run_end"}\n', encoding="utf-8")

    import eval_runner.utils.crypto as crypto

    real_hash = crypto.file_hash(trace_file)
    (run_cert / "run_manifest.json").write_text(
        json.dumps({"trace_hash": f"sha3_256:{real_hash}"}), encoding="utf-8"
    )

    # 2. Zero-size trace file
    run_zero = runs_dir / "run-zero"
    run_zero.mkdir(parents=True, exist_ok=True)
    (run_zero / "run.jsonl").write_text("", encoding="utf-8")

    # 3. Active running run (<300s without run_end)
    run_active = runs_dir / "run-active"
    run_active.mkdir(parents=True, exist_ok=True)
    (run_active / "run.jsonl").write_text(
        json.dumps({"event": "step", "_ts_iso": "2026-08-30T18:00:00Z"}) + "\n",
        encoding="utf-8",
    )

    # Trigger stream-list endpoint
    res = client.get("/v1/runs/stream-list")
    assert res.status_code == 200
    # Read stream chunks
    data = res.get_data(as_text=True)
    assert "data:" in data


def test_get_run_status_scenario_fallbacks_and_backend(client, tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    # 1. scenario_original.json fallback when scenario_resolved.json is missing
    run_orig = runs_dir / "run-orig"
    run_orig.mkdir(parents=True, exist_ok=True)
    (run_orig / "run.jsonl").write_text('{"event":"run_end"}\n', encoding="utf-8")
    (run_orig / "scenario_original.json").write_text(
        json.dumps({"id": "orig_scenario_data"}), encoding="utf-8"
    )

    res_orig = client.get("/v1/runs/run-orig")
    assert res_orig.status_code == 200
    assert res_orig.get_json()["scenario"] == {"id": "orig_scenario_data"}

    # 2. InProcessExecutionBackend status query exception fallback
    with patch(
        "eval_runner.reference.inprocess_backend.InProcessExecutionBackend.get_instance"
    ) as mock_inst:
        mock_backend = MagicMock()
        mock_backend.status.side_effect = Exception("Backend in-memory query failed")
        mock_inst.return_value = mock_backend

        res_404 = client.get("/v1/runs/non-existent-run-id")
        assert res_404.status_code == 404


def test_tail_file_generator_and_stream_logs(client, tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    run_dir = runs_dir / "run-tail-test"
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "run.jsonl"
    log_file.write_text(
        '{"event": "step1"}\n{"event": "step2"}\n{"event": "run_end"}\n',
        encoding="utf-8",
    )

    # 1. stream endpoint with invalid last_event_id string
    res = client.get("/v1/runs/run-tail-test/stream?last_event_id=not_an_int")
    assert res.status_code == 200
    stream_content = res.get_data(as_text=True)
    assert "data: " in stream_content

    # 2. Direct tail_file_generator test with incomplete line seek rewind
    partial_file = run_dir / "partial.jsonl"
    partial_file.write_text('{"event": "line1"}\nunterminated_line', encoding="utf-8")

    gen = tail_file_generator(partial_file, "run-tail-test")
    # Take first item from generator
    item = next(gen)
    assert "line1" in item


def test_verify_run_endpoint(client, tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    # 1. Non-existent run directory (404)
    res_404 = client.get("/v1/runs/unknown-run-404/verify")
    assert res_404.status_code == 404

    # 2. Existing run directory verified
    run_dir = runs_dir / "run-verify-ok"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text('{"event":"run_end"}\n', encoding="utf-8")

    with patch("eval_runner.verifier.TraceVerifier.verify_run_directory") as mock_v:
        mock_v.return_value = {"verification_status": "VERIFIED", "passed": True}
        res_ok = client.get("/v1/runs/run-verify-ok/verify")
        assert res_ok.status_code == 200
        assert res_ok.get_json()["verification_status"] == "VERIFIED"
