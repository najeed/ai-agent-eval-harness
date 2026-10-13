"""
D1: Extension publisher signing & verification (tier enforcement backend).

  POST /api/v1/extensions/sign             ; dev trust-root Ed25519 signing
  POST /api/v1/extensions/verify-publisher ; fail-closed signature verification

Signatures cover RuntimeExtension.canonical_bytes() (canonical JSON excluding
the signature field). Keys live under the configured TRUST_ROOT.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.extension_publisher import (
    publish_extension,
    repair_extension,
    verify_extension,
)
from eval_runner.console.routes.trust import _private_key_pem_bytes, _public_key_pem_bytes, trust_bp
from eval_runner.utils import rmtree_resilient


@pytest.fixture(scope="module")
def trust_jail(request):
    worker_id = getattr(request.config, "workerinput", {}).get("workerid", "master")
    tmp_root = Path(tempfile.gettempdir()) / f"aes_trust_jail_{worker_id}"
    if tmp_root.exists():
        rmtree_resilient(tmp_root)
    keys = tmp_root / "keys"
    keys.mkdir(parents=True, exist_ok=True)
    yield {"root": tmp_root, "keys": keys}
    if tmp_root.exists():
        rmtree_resilient(tmp_root)


@pytest.fixture
def client(trust_jail, monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(trust_bp)

    monkeypatch.setattr(config, "PROJECT_ROOT", trust_jail["root"])
    monkeypatch.setattr(config, "TRUST_ROOT", trust_jail["keys"])
    monkeypatch.setattr(
        config, "EXTENSION_ARTIFACT_DIR", trust_jail["root"] / ".agentv" / "extensions"
    )

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        yield app.test_client()


def _base_manifest() -> dict:
    return {
        "extension_id": "com.acme.fleet",
        "display_name": "Fleet Analytics",
        "version": "1.2.3",
        "api_version": "1.0.0",
        "capabilities": ["routes", "navigation"],
        "required_permissions": [],
        "routes": [{"path": "/fleet", "label": "Fleet"}],
        "nav_group": "extensions",
        "remote_entry": "/static/extensions/fleet.js",
        "sri_hash": "sha3-256-QUJDREVGR0hJSktMTU5PUA==",
        "publisher": "acme_publisher",
        "host_apis": ["runtime.runs.list"],
    }


def test_sign_then_verify_round_trip(client):
    manifest = _base_manifest()

    sign_res = client.post(
        "/api/v1/extensions/sign",
        json={"manifest": manifest, "identity_id": "acme_publisher"},
    )
    assert sign_res.status_code == 200
    signed = sign_res.get_json()
    assert signed["algorithm"] == "ed25519"
    assert signed["signature"]

    manifest["signature"] = signed["signature"]

    verify_res = client.post("/api/v1/extensions/verify-publisher", json={"manifest": manifest})
    body = verify_res.get_json()
    assert verify_res.status_code == 200
    assert body["valid"] is True
    assert body["tier"] in ("official", "community")  # backend-authoritative tier
    assert body["reason"] == "signature-verified"


def test_tampered_manifest_fails_verification(client):
    manifest = _base_manifest()
    sig = client.post(
        "/api/v1/extensions/sign",
        json={"manifest": manifest, "identity_id": "acme_publisher"},
    ).get_json()["signature"]
    manifest["signature"] = sig

    # Tamper AFTER signing.
    manifest["display_name"] = "Evil Fleet"

    body = client.post(
        "/api/v1/extensions/verify-publisher", json={"manifest": manifest}
    ).get_json()
    assert body["valid"] is False
    assert body["tier"] == "invalid-signature"
    assert body["reason"] == "signature-mismatch"


def test_unknown_publisher_is_fail_closed(client):
    manifest = _base_manifest()
    manifest["publisher"] = "nobody_known"
    manifest["signature"] = "a" * 128

    body = client.post(
        "/api/v1/extensions/verify-publisher",
        json={"manifest": manifest},
    ).get_json()
    assert body["valid"] is False
    assert body["tier"] == "unsigned-local"
    assert body["reason"] == "unknown-publisher"


def test_missing_signature_rejected(client):
    body = client.post(
        "/api/v1/extensions/verify-publisher", json={"manifest": _base_manifest()}
    ).get_json()
    assert body["valid"] is False
    assert body["reason"] == "missing-signature"
    assert body["tier"] == "unsigned-local"


def test_contract_violation_rejected_before_crypto(client):
    manifest = _base_manifest()
    manifest["version"] = "not-semver"  # structural violation

    body = client.post("/api/v1/extensions/verify-publisher", json={"manifest": manifest})
    assert body.status_code == 400
    payload = body.get_json()
    assert payload["valid"] is False
    assert payload["reason"] == "contract-violation"
    assert any("SemVer" in v for v in payload["violations"])


def test_sign_rejects_structurally_invalid_manifest(client):
    bad = _base_manifest()
    bad.pop("extension_id")

    res = client.post("/api/v1/extensions/sign", json={"manifest": bad, "identity_id": "x"})
    assert res.status_code == 400
    assert "violations" in res.get_json() or "error" in res.get_json()


def test_sign_is_deterministic_over_canonical_bytes(client):
    m1 = _base_manifest()
    s1 = client.post(
        "/api/v1/extensions/sign", json={"manifest": m1, "identity_id": "det_pub"}
    ).get_json()
    s2 = client.post(
        "/api/v1/extensions/sign", json={"manifest": m1, "identity_id": "det_pub"}
    ).get_json()
    # Ed25519 is deterministic: same key + same canonical bytes => same sig.
    assert s1["signature"] == s2["signature"]
    # Canonical digest excludes the signature field by construction.
    assert len(s1["canonical_sha3_256"]) == 64


def test_signature_covers_all_fields_except_signature_itself(client):
    manifest = _base_manifest()
    sig = client.post(
        "/api/v1/extensions/sign",
        json={"manifest": manifest, "identity_id": "acme_publisher"},
    ).get_json()["signature"]

    # Adding an UNKNOWN extra field changes canonical bytes -> must fail.
    manifest["signature"] = sig
    manifest["_injected"] = "payload"
    body = client.post(
        "/api/v1/extensions/verify-publisher", json={"manifest": manifest}
    ).get_json()
    assert body["valid"] is False


def test_publish_signs_entry_and_relative_chunks_atomically(client, trust_jail):
    source = trust_jail["root"] / "source"
    (source / "chunks").mkdir(parents=True)
    (source / "entry.mjs").write_text(
        "import { label } from './chunks/label.js'; export default label;", encoding="utf-8"
    )
    (source / "chunks" / "label.js").write_text("export const label = 'generic';", encoding="utf-8")

    descriptor = publish_extension(
        entry=source / "entry.mjs",
        extension_id="generic-header",
        publisher="configured-publisher",
        version="1.0.0",
        private_key_pem=_private_key_pem_bytes,
        artifact_root=trust_jail["root"] / ".agentv" / "extensions",
    )

    assert descriptor["remoteEntry"] == "/extensions/generic-header/1.0.0/entry.mjs"
    manifest = descriptor["manifest"]
    assert manifest["slot"] == "header"
    assert manifest["react_peer"] is True
    assert manifest["verified_chunks"]["./chunks/label.js"].startswith("sha3-256-")
    verify = client.post("/api/v1/extensions/verify-publisher", json={"manifest": manifest})
    assert verify.get_json()["valid"] is True


def test_publish_failure_leaves_no_partial_version(trust_jail):
    source = trust_jail["root"] / "invalid-source"
    source.mkdir()
    (source / "entry.mjs").write_text("import './missing.js';", encoding="utf-8")
    artifact_root = trust_jail["root"] / ".agentv" / "extensions"

    with pytest.raises(ValueError, match="publishable chunk"):
        publish_extension(
            entry=source / "entry.mjs",
            extension_id="bad-extension",
            publisher="configured-publisher",
            version="1.0.0",
            private_key_pem=_private_key_pem_bytes,
            artifact_root=artifact_root,
        )
    assert not (artifact_root / "bad-extension" / "1.0.0").exists()


def test_publish_api_returns_origin_relative_descriptor(client, trust_jail):
    source = trust_jail["root"] / "api-source"
    source.mkdir()
    entry = source / "entry.mjs"
    entry.write_text("export default () => null;", encoding="utf-8")
    response = client.post(
        "/api/v1/extensions/publish",
        json={
            "entry": str(entry),
            "extension_id": "api-header",
            "publisher": "configured-publisher",
            "version": "2.0.0",
        },
    )
    assert response.status_code == 201
    assert response.get_json()["remoteEntry"] == "/extensions/api-header/2.0.0/entry.mjs"
    assert response.get_json()["sriHash"].startswith("sha3-256-")


def test_verify_detects_corruption_and_repair_restores_only_identical_bytes(trust_jail):
    source = trust_jail["root"] / "repair-source"
    source.mkdir()
    entry = source / "entry.mjs"
    entry.write_text("export default 'trusted';", encoding="utf-8")
    root = trust_jail["root"] / ".agentv" / "extensions"
    publish_extension(
        entry=entry,
        extension_id="repairable",
        publisher="repair-publisher",
        version="1.0.0",
        private_key_pem=_private_key_pem_bytes,
        artifact_root=root,
    )
    installed = root / "repairable" / "1.0.0" / "entry.mjs"
    installed.write_text("export default 'corrupt';", encoding="utf-8")
    assert (
        verify_extension(
            extension_id="repairable",
            version="1.0.0",
            public_key_pem=_public_key_pem_bytes,
            artifact_root=root,
        )["valid"]
        is False
    )
    repaired = repair_extension(
        entry=entry,
        extension_id="repairable",
        publisher="repair-publisher",
        version="1.0.0",
        public_key_pem=_public_key_pem_bytes,
        artifact_root=root,
    )
    assert repaired["status"] == "repaired"
    assert (
        verify_extension(
            extension_id="repairable",
            version="1.0.0",
            public_key_pem=_public_key_pem_bytes,
            artifact_root=root,
        )["valid"]
        is True
    )
    entry.write_text("export default 'different';", encoding="utf-8")
    with pytest.raises(ValueError, match="do not match retained"):
        repair_extension(
            entry=entry,
            extension_id="repairable",
            publisher="repair-publisher",
            version="1.0.0",
            public_key_pem=_public_key_pem_bytes,
            artifact_root=root,
        )
