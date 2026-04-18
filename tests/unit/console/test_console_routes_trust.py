import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from eval_runner import config

# SUT
from eval_runner.console.routes.trust import trust_bp


@pytest.fixture(scope="module")
def console_jail():
    tmp_root = Path(tempfile.gettempdir()) / "aes_console_trust_jail"
    root = tmp_root / "root"
    runs = root / "runs"

    if tmp_root.exists():
        shutil.rmtree(tmp_root)

    os.makedirs(runs, exist_ok=True)
    yield {"root": root, "runs": runs}

    if tmp_root.exists():
        shutil.rmtree(tmp_root)


@pytest.fixture
def client(console_jail, monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(trust_bp)

    monkeypatch.setattr(config, "PROJECT_ROOT", console_jail["root"])
    monkeypatch.setattr(config, "RUN_LOG_DIR", console_jail["runs"])

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        yield app.test_client()


def test_certify_run_missing_id(client):
    res = client.post("/api/v1/certify", json={})
    assert res.status_code == 400
    assert "run_id is required" in res.get_json()["error"]


def test_certify_run_404(client):
    res = client.post("/api/v1/certify", json={"run_id": "ghost_run"})
    assert res.status_code == 404
    assert "vault not found" in res.get_json()["error"]


def test_certify_run_success(client, console_jail):
    run_id = "test_run_1"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text('{"event": "run_start"}\n', encoding="utf-8")

    with patch("eval_runner.verifier.TraceVerifier.sign_trace") as mock_sign:
        mock_sign.return_value = {"sha256": "fake_hash"}
        res = client.post("/api/v1/certify", json={"run_id": run_id})
        assert res.status_code == 200
        assert res.get_json()["status"] == "certified"
        assert (run_dir / "run_manifest.json").exists()


def test_verify_run_public_404(client):
    res = client.get("/api/v1/verify/none")
    assert res.status_code == 404


def test_verify_run_public_compliant(client, console_jail):
    run_id = "verify_ok"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text("trace", encoding="utf-8")
    manifest = {"compliance_status": "pass", "compliance_score": 1.0, "sha256": "h"}
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=True):
        res = client.get(f"/api/v1/verify/{run_id}")
        assert res.status_code == 200
        assert res.get_json()["verified"] is True


def test_verify_run_public_non_compliant_score(client, console_jail):
    run_id = "verify_fail"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text("trace", encoding="utf-8")
    manifest = {"compliance": {"status": "pass", "score": 0.5}, "sha256": "h"}
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=True):
        res = client.get(f"/api/v1/verify/{run_id}")
        assert res.status_code == 200
        assert res.get_json()["verified"] is False


def test_verify_run_exception(client, console_jail):
    run_id = "verify_error"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text("trace", encoding="utf-8")
    (run_dir / "run_manifest.json").write_text("bad data", encoding="utf-8")

    res = client.get(f"/api/v1/verify/{run_id}")
    assert res.status_code == 500
    assert res.get_json()["verified"] is False


def test_get_identity_public_key_success(client):
    with patch("eval_runner.identity.IdentityService.get_public_key") as mock_get:
        mock_key = MagicMock()
        mock_key.public_bytes.return_value = b"PEM_KEY"
        mock_get.return_value = mock_key

        res = client.get("/api/v1/identity/sys1/public_key")
        assert res.status_code == 200
        assert "PEM_KEY" in res.get_json()["public_key"]


def test_get_identity_public_key_404(client):
    with patch(
        "eval_runner.identity.IdentityService.get_public_key", side_effect=ValueError("not found")
    ):
        res = client.get("/api/v1/identity/ghost/public_key")
        assert res.status_code == 404


def test_verify_run_cryptographic_proof(client, console_jail):
    run_id = "verify_crypto"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text("trace", encoding="utf-8")
    manifest = {
        "compliance": {"status": "pass", "score": 1.0},
        "sha256": "h",
        "provenance_chain": [{"signer": "sys1"}],
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=True):
        res = client.get(f"/api/v1/verify/{run_id}")
        assert res.status_code == 200
        assert res.get_json()["verified"] is True
        assert "ED25519" in res.get_json()["method"]


def test_certify_run_generic_exception(client, console_jail):
    run_id = "crash_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text("data", encoding="utf-8")

    with patch(
        "eval_runner.verifier.TraceVerifier.sign_trace", side_effect=Exception("Critical Failure")
    ):
        res = client.post("/api/v1/certify", json={"run_id": run_id})
        assert res.status_code == 500
        assert "Critical Failure" in res.get_json()["error"]
