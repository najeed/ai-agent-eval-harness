import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from eval_runner import config

# SUT
from eval_runner.console.routes.trust import trust_bp
from eval_runner.utils import rmtree_resilient


@pytest.fixture(scope="module")
def console_jail(request):
    worker_id = getattr(request.config, "workerinput", {}).get("workerid", "master")
    tmp_root = Path(tempfile.gettempdir()) / f"aes_console_trust_jail_{worker_id}"
    root = tmp_root / "root"
    runs = root / "runs"

    if tmp_root.exists():
        rmtree_resilient(tmp_root)

    os.makedirs(runs, exist_ok=True)
    yield {"root": root, "runs": runs}

    if tmp_root.exists():
        rmtree_resilient(tmp_root)


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
        mock_sign.return_value = {"trace_hash": "fake_hash"}
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
    manifest = {
        "compliance_status": "pass",
        "compliance_score": 1.0,
        "trace_hash": "h",
        "hash_algorithm": "sha3_256",
    }
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
    manifest = {
        "compliance": {"status": "pass", "score": 0.5},
        "trace_hash": "h",
        "hash_algorithm": "sha3_256",
    }
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
        "trace_hash": "h",
        "hash_algorithm": "sha3_256",
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


def test_read_run_truth_level_branches(client, console_jail):
    from eval_runner.console.routes.trust import _read_run_truth_level

    # Nonexistent trace
    mode, prov = _read_run_truth_level("nonexistent_run")
    assert mode is None
    assert prov is False

    # Trace with empty line and non-run_start event
    run_id = "truth_level_test"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text(
        "\n"
        + json.dumps({"event": "other_event"})
        + "\n"
        + json.dumps(
            {
                "event": "run_start",
                "data": {"execution_mode": "LIVE_API", "execution_mode_declared": True},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    mode, prov = _read_run_truth_level(run_id)
    assert mode == "LIVE_API"
    assert prov is False


def test_get_identity_public_key_none_and_private_key_none(client):
    from eval_runner.console.routes.trust import _private_key_pem_bytes

    # Public key returns None
    with patch("eval_runner.identity.IdentityService.get_public_key", return_value=None):
        res = client.get("/api/v1/identity/sys_none/public_key")
        assert res.status_code == 404

    # Private key returns None
    with patch("eval_runner.identity.IdentityService.get_private_key", return_value=None):
        with pytest.raises(ValueError, match="No signing identity available"):
            _private_key_pem_bytes("sys_none")


def test_extension_signing_and_verification_endpoints(client, monkeypatch):
    # Sign manifest invalid (non-dict)
    res_sign_invalid = client.post("/api/v1/extensions/sign", json={"manifest": "not-a-dict"})
    assert res_sign_invalid.status_code == 400

    # Sign manifest missing required field raising ExtensionContractError
    res_sign_missing = client.post(
        "/api/v1/extensions/sign", json={"manifest": {"extension_id": "only_id"}}
    )
    assert res_sign_missing.status_code == 400
    assert "Invalid manifest" in res_sign_missing.get_json()["error"]

    # _public_key_pem_bytes returns None
    from eval_runner.console.routes.trust import _public_key_pem_bytes

    with patch("eval_runner.identity.IdentityService.get_public_key", return_value=None):
        assert _public_key_pem_bytes("ghost_identity") is None

    # Sign manifest signing exception (500)
    valid_manifest = {
        "extension_id": "ext-1",
        "display_name": "Extension 1",
        "version": "1.0.0",
        "remote_entry": "http://127.0.0.1:8080/ext.js",
        "sri_hash": "sha3-256-dummy",
        "publisher": "official_org",
        "capabilities": ["routes", "navigation"],
    }
    with patch(
        "eval_runner.console.routes.trust._private_key_pem_bytes",
        side_effect=OSError("Key unreadable"),
    ):
        res_sign_500 = client.post("/api/v1/extensions/sign", json={"manifest": valid_manifest})
        assert res_sign_500.status_code == 500

    # Successful signing
    res_sign = client.post("/api/v1/extensions/sign", json={"manifest": valid_manifest})
    assert res_sign.status_code == 200
    sig_data = res_sign.get_json()
    assert "signature" in sig_data

    # Verify publisher non-dict manifest
    res_ver_nodict = client.post(
        "/api/v1/extensions/verify-publisher", json={"manifest": "not-dict"}
    )
    assert res_ver_nodict.status_code == 400

    # Verify publisher contract violation
    res_ver_viol = client.post(
        "/api/v1/extensions/verify-publisher",
        json={"manifest": {"extension_id": "bad", "display_name": "Bad", "version": "not-semver"}},
    )
    assert res_ver_viol.status_code == 400
    assert res_ver_viol.get_json()["reason"] == "contract-violation"

    # Verify publisher missing signature
    res_ver_nosig = client.post(
        "/api/v1/extensions/verify-publisher",
        json={"manifest": {**valid_manifest, "signature": ""}},
    )
    assert res_ver_nosig.status_code == 200
    assert res_ver_nosig.get_json()["reason"] == "missing-signature"

    # Verify publisher missing publisher name
    res_ver_nopub = client.post(
        "/api/v1/extensions/verify-publisher",
        json={"manifest": {**valid_manifest, "publisher": "", "signature": sig_data["signature"]}},
    )
    assert res_ver_nopub.status_code == 200
    assert res_ver_nopub.get_json()["reason"] == "missing-publisher"

    # Verify publisher unknown publisher
    with patch("eval_runner.console.routes.trust._public_key_pem_bytes", return_value=None):
        res_ver_unknown = client.post(
            "/api/v1/extensions/verify-publisher",
            json={
                "manifest": {**valid_manifest, "signature": sig_data["signature"]},
                "identity_id": "ghost_pub",
            },
        )
        assert res_ver_unknown.status_code == 200
        assert res_ver_unknown.get_json()["reason"] == "unknown-publisher"

    # Verify publisher signature mismatch
    res_ver_bad_sig = client.post(
        "/api/v1/extensions/verify-publisher",
        json={
            "manifest": {**valid_manifest, "signature": "00" * 64},
            "identity_id": "dev_publisher",
        },
    )
    assert res_ver_bad_sig.status_code == 200
    assert res_ver_bad_sig.get_json()["tier"] == "invalid-signature"
    assert res_ver_bad_sig.get_json()["reason"] == "signature-mismatch"

    # Verify publisher community tier
    monkeypatch.setenv("AGENTV_OFFICIAL_PUBLISHERS", "other_corp")
    res_ver_comm = client.post(
        "/api/v1/extensions/verify-publisher",
        json={
            "manifest": {**valid_manifest, "signature": sig_data["signature"]},
            "identity_id": "dev_publisher",
        },
    )
    assert res_ver_comm.status_code == 200
    assert res_ver_comm.get_json()["tier"] == "community"
    assert res_ver_comm.get_json()["valid"] is True

    # Verify publisher official tier
    monkeypatch.setenv("AGENTV_OFFICIAL_PUBLISHERS", "official_org,sec_corp")
    res_ver_official = client.post(
        "/api/v1/extensions/verify-publisher",
        json={
            "manifest": {**valid_manifest, "signature": sig_data["signature"]},
            "identity_id": "dev_publisher",
        },
    )
    assert res_ver_official.status_code == 200
    assert res_ver_official.get_json()["tier"] == "official"
    assert res_ver_official.get_json()["valid"] is True

    assert res_ver_official.status_code == 200
    assert res_ver_official.get_json()["tier"] == "official"
    assert res_ver_official.get_json()["valid"] is True
