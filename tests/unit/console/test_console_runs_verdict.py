"""
C1a: /api/runs returns a server-authoritative verification verdict per run.

  VERIFIED              — certificate/manifest trace_hash == SHA3-256(current trace)
  FAILED_VERIFICATION   — hash mismatch (trace mutated after certification)
  UNKNOWN               — no certificate, unreadable manifest, or absent hash

The server never infers verdicts from certificate PRESENCE or execution
status alone.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.routes.runs import run_bp
from eval_runner.utils import crypto, rmtree_resilient


@pytest.fixture(scope="module")
def verdict_jail(request):
    worker_id = getattr(request.config, "workerinput", {}).get("workerid", "master")
    tmp_root = Path(tempfile.gettempdir()) / f"aes_runs_verdict_jail_{worker_id}"
    root = tmp_root / "root"
    runs = root / "runs"
    reports = root / "reports"

    if tmp_root.exists():
        rmtree_resilient(tmp_root)

    (reports / "certificates").mkdir(parents=True)
    runs.mkdir(parents=True)
    yield {"root": root, "runs": runs, "reports": reports}

    if tmp_root.exists():
        rmtree_resilient(tmp_root)


@pytest.fixture
def client(verdict_jail, monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(run_bp, url_prefix="/api")

    monkeypatch.setattr(config, "PROJECT_ROOT", verdict_jail["root"])
    monkeypatch.setattr(config, "RUN_LOG_DIR", verdict_jail["runs"])
    monkeypatch.setattr(config, "REPORTS_DIR", verdict_jail["reports"])

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        yield app.test_client()


def _make_vault(runs_dir: Path, run_id: str, trace_text: str = '{"event": "run_start"}\n'):
    vault = runs_dir / run_id
    vault.mkdir(parents=True, exist_ok=True)
    trace = vault / "run.jsonl"
    trace.write_text(trace_text, encoding="utf-8")
    return vault, trace


def _write_manifest(trace_path: Path, trace_hash: str):
    manifest = {
        "vc_version": "3.0.0",
        "trace_hash": trace_hash,
        "provenance_chain": [{"identity": "test_signer", "algorithm": "ED25519"}],
    }
    (trace_path.parent / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_list_runs_reports_verified_for_matching_hash(verdict_jail, client):
    _, trace = _make_vault(verdict_jail["runs"], "run-verdict-ok")
    _write_manifest(trace, crypto.file_hash(trace))

    res = client.get("/api/runs")
    assert res.status_code == 200
    row = next(r for r in res.get_json()["runs"] if r["run_id"] == "run-verdict-ok")
    assert row["verification_status"] == "VERIFIED"


def test_list_runs_reports_failed_verification_on_tamper(verdict_jail, client):
    vault, trace = _make_vault(verdict_jail["runs"], "run-verdict-tampered")
    _write_manifest(trace, crypto.file_hash(trace))
    # Mutate the trace AFTER certification.
    with open(trace, "a", encoding="utf-8") as f:
        f.write('{"event": "injected"}\n')

    res = client.get("/api/runs")
    row = next(r for r in res.get_json()["runs"] if r["run_id"] == "run-verdict-tampered")
    assert row["verification_status"] == "FAILED_VERIFICATION"


def test_list_runs_reports_unknown_without_certificate(verdict_jail, client):
    _make_vault(verdict_jail["runs"], "run-verdict-nocert")

    res = client.get("/api/runs")
    row = next(r for r in res.get_json()["runs"] if r["run_id"] == "run-verdict-nocert")
    assert row["verification_status"] == "UNKNOWN"


def test_list_runs_unknown_when_manifest_lacks_trace_hash(verdict_jail, client):
    _, trace = _make_vault(verdict_jail["runs"], "run-verdict-emptyhash")
    (trace.parent / "run_manifest.json").write_text(
        json.dumps({"vc_version": "3.0.0"}), encoding="utf-8"
    )

    res = client.get("/api/runs")
    row = next(r for r in res.get_json()["runs"] if r["run_id"] == "run-verdict-emptyhash")
    assert row["verification_status"] == "UNKNOWN"


def test_verdict_accepts_prefixed_hash_form(verdict_jail, client):
    _, trace = _make_vault(verdict_jail["runs"], "run-verdict-prefixed")
    prefixed = f"sha3_256:{crypto.file_hash(trace)}"
    _write_manifest(trace, prefixed)

    res = client.get("/api/runs")
    row = next(r for r in res.get_json()["runs"] if r["run_id"] == "run-verdict-prefixed")
    assert row["verification_status"] == "VERIFIED"


def test_missing_trace_is_unknown_even_with_certificate(verdict_jail, client):
    # Manifest exists but the trace file was deleted -> cannot verify.
    vault, trace = _make_vault(verdict_jail["runs"], "run-verdict-gone")
    _write_manifest(trace, crypto.file_hash(trace))
    trace.unlink()

    res = client.get("/api/runs")
    rows = {r["run_id"]: r for r in res.get_json()["runs"]}
    if "run-verdict-gone" in rows:
        assert rows["run-verdict-gone"]["verification_status"] == "UNKNOWN"
