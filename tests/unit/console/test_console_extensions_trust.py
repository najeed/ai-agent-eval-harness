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


def test_tampered_signed_navigation_icon_fails_verification(client):
    manifest = {
        **_base_manifest(),
        "navigation": [{"path": "/fleet", "id": "fleet", "icon": "shield"}],
    }
    manifest["signature"] = client.post(
        "/api/v1/extensions/sign",
        json={"manifest": manifest, "identity_id": "acme_publisher"},
    ).get_json()["signature"]
    manifest["navigation"][0]["icon"] = "activity"
    body = client.post(
        "/api/v1/extensions/verify-publisher", json={"manifest": manifest}
    ).get_json()
    assert body["valid"] is False
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


def test_publish_returns_signed_navigation_records_in_descriptor(trust_jail):
    source = trust_jail["root"] / "navigation-source"
    source.mkdir()
    (source / "entry.mjs").write_text("export default null;", encoding="utf-8")
    descriptor = publish_extension(
        entry=source / "entry.mjs",
        extension_id="generic-navigation",
        publisher="configured-publisher",
        version="1.0.0",
        private_key_pem=_private_key_pem_bytes,
        artifact_root=trust_jail["root"] / ".agentv" / "extensions",
        manifest_declaration={
            "display_name": "Generic Navigation",
            "capabilities": ["routes", "navigation"],
            "routes": [{"path": "/generic", "required_permissions": ["runs:read"]}],
            "navigation": [{"path": "/generic", "id": "generic", "badge": "NEW"}],
        },
    )
    assert descriptor["manifest"]["navigation"] == [
        {
            "path": "/generic",
            "id": "generic",
            "title": None,
            "icon": None,
            "group": None,
            "badge": "NEW",
            "provenance": None,
        }
    ]


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


class TestExtensionPublisherExhaustiveCoverage:
    """Exhaustive tests for edge cases across extension_publisher."""

    def test_relative_chunks_edge_cases(self, tmp_path):
        from eval_runner.console.extension_publisher import _relative_chunks

        # External import and extension-less import and diamond seen check
        entry = tmp_path / "entry.js"
        helper = tmp_path / "helper.js"
        helper.write_text("export const val = 42;", encoding="utf-8")
        entry.write_text(
            'import React from "react";\n'
            'import "./helper";\n'
            'import "./helper.js";\n'
            "export default null;",
            encoding="utf-8",
        )
        chunks = _relative_chunks(entry)
        assert len(chunks) == 1
        assert chunks[0].name == "helper.js"

        # Traversal escape raises ValueError
        bad_entry = tmp_path / "sub" / "bad.js"
        bad_entry.parent.mkdir(parents=True, exist_ok=True)
        bad_entry.write_text('import "../../outside.js";', encoding="utf-8")
        with pytest.raises(ValueError, match="not a local publishable chunk"):
            _relative_chunks(bad_entry)

    def test_publish_extension_validation_and_idempotency(self, trust_jail, tmp_path):
        from eval_runner.console.extension_publisher import publish_extension

        root = trust_jail["root"] / ".agentv" / "extensions"
        entry = tmp_path / "src" / "entry.js"
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text("export default 1;", encoding="utf-8")

        # Non-existent entry
        with pytest.raises(ValueError, match="entry must name a readable ESM file"):
            publish_extension(
                entry=tmp_path / "nonexistent.js",
                extension_id="valid-id",
                publisher="configured-publisher",
                version="1.0.0",
                private_key_pem=_private_key_pem_bytes,
                artifact_root=root,
            )

        # Unsafe extension_id
        for bad_id in ("", "bad/id", "bad\\id", ".."):
            with pytest.raises(ValueError, match="single safe identifier"):
                publish_extension(
                    entry=entry,
                    extension_id=bad_id,
                    publisher="configured-publisher",
                    version="1.0.0",
                    private_key_pem=_private_key_pem_bytes,
                    artifact_root=root,
                )

        # Mismatch manifest argument
        with pytest.raises(ValueError, match="manifest publisher must match"):
            publish_extension(
                entry=entry,
                extension_id="test-id",
                publisher="configured-publisher",
                version="1.0.0",
                private_key_pem=_private_key_pem_bytes,
                artifact_root=root,
                manifest_declaration={"publisher": "different-pub"},
            )

        # Manifest validation failure (e.g. unknown capabilities)
        with pytest.raises(ValueError):
            publish_extension(
                entry=entry,
                extension_id="test-id",
                publisher="configured-publisher",
                version="1.0.0",
                private_key_pem=_private_key_pem_bytes,
                artifact_root=root,
                manifest_declaration={"capabilities": ["unsupported_capability_xyz"]},
            )

        # Successful publish with activate=True
        desc1 = publish_extension(
            entry=entry,
            extension_id="idempotent-test",
            publisher="configured-publisher",
            version="1.0.0",
            private_key_pem=_private_key_pem_bytes,
            artifact_root=root,
            activate=True,
        )
        assert desc1["active"] is True

        # Re-publish identical bytes (idempotent success with activate=True)
        desc2 = publish_extension(
            entry=entry,
            extension_id="idempotent-test",
            publisher="configured-publisher",
            version="1.0.0",
            private_key_pem=_private_key_pem_bytes,
            artifact_root=root,
            activate=True,
        )
        assert desc2["sriHash"] == desc1["sriHash"]

        # Re-publish identical bytes with activate=False
        desc3 = publish_extension(
            entry=entry,
            extension_id="idempotent-test",
            publisher="configured-publisher",
            version="1.0.0",
            private_key_pem=_private_key_pem_bytes,
            artifact_root=root,
            activate=False,
        )
        assert desc3["sriHash"] == desc1["sriHash"]

        # Manifest validation failure
        with pytest.raises(ValueError):
            publish_extension(
                entry=entry,
                extension_id="test-val-fail",
                publisher="configured-publisher",
                version="1.0.0",
                private_key_pem=_private_key_pem_bytes,
                artifact_root=root,
                manifest_declaration={
                    "display_name": "",
                    "routes": [{"path": "relative-path"}],
                },
            )

        # Re-publish differing bytes to same version raises ValueError
        differing_entry = tmp_path / "src" / "differing.js"
        differing_entry.write_text("export default 999999;", encoding="utf-8")
        with pytest.raises(ValueError, match="already published with different bytes"):
            publish_extension(
                entry=differing_entry,
                extension_id="idempotent-test",
                publisher="configured-publisher",
                version="1.0.0",
                private_key_pem=_private_key_pem_bytes,
                artifact_root=root,
            )

    def test_unpublish_extension_branches(self, trust_jail, tmp_path):
        import json

        from eval_runner.console.extension_publisher import (
            publish_extension,
            unpublish_extension,
        )

        root = trust_jail["root"] / ".agentv" / "extensions"
        # Non-existent target
        res_nf = unpublish_extension(
            extension_id="nonexistent-ext",
            version="9.9.9",
            artifact_root=root,
        )
        assert res_nf["status"] == "not_found"

        # Publish and unpublish with corrupt active release handling
        entry = tmp_path / "unpub_entry.js"
        entry.write_text("export default true;", encoding="utf-8")
        publish_extension(
            entry=entry,
            extension_id="unpub-ext",
            publisher="configured-publisher",
            version="1.0.0",
            private_key_pem=_private_key_pem_bytes,
            artifact_root=root,
            activate=True,
        )
        # Write corrupt active record to trigger decode catch
        corrupt_rec = root / ".active-releases" / "configured-publisher" / "unpub-ext.json"
        corrupt_rec.write_text("not json", encoding="utf-8")

        res_unpub = unpublish_extension(
            extension_id="unpub-ext",
            version="1.0.0",
            artifact_root=root,
        )
        assert res_unpub["status"] == "unpublished"

        # Differing active version remains untouched during unpublish
        (root / "unpub-ext" / "1.0.0").mkdir(parents=True, exist_ok=True)
        diff_active_rec = root / ".active-releases" / "configured-publisher" / "unpub-ext.json"
        diff_active_rec.parent.mkdir(parents=True, exist_ok=True)
        diff_active_rec.write_text(json.dumps({"version": "9.9.9"}), encoding="utf-8")
        unpublish_extension(
            extension_id="unpub-ext",
            version="1.0.0",
            artifact_root=root,
        )

        # Unpublish when .active-releases directory does not exist
        no_active_root = tmp_path / "no_act_root"
        (no_active_root / "ext-standalone" / "1.0.0").mkdir(parents=True)
        res_no_act = unpublish_extension(
            extension_id="ext-standalone",
            version="1.0.0",
            artifact_root=no_active_root,
        )
        assert res_no_act["status"] == "unpublished"

    def test_activate_and_rollback_validation(self, trust_jail, tmp_path):
        from eval_runner.console.extension_publisher import (
            activate_extension,
            publish_extension,
        )

        root = trust_jail["root"] / ".agentv" / "extensions"

        # Unsafe identifiers
        with pytest.raises(ValueError, match="single safe identifier"):
            activate_extension(
                extension_id="bad/id",
                version="1.0.0",
                artifact_root=root,
            )
        with pytest.raises(ValueError, match="single safe identifier"):
            activate_extension(
                extension_id="valid-id",
                version="bad/version",
                artifact_root=root,
            )

        # Create local extension for activation test
        entry = tmp_path / "act_entry.js"
        entry.write_text("export default null;", encoding="utf-8")
        publish_extension(
            entry=entry,
            extension_id="act-pub-mismatch",
            publisher="configured-publisher",
            version="1.0.0",
            private_key_pem=_private_key_pem_bytes,
            artifact_root=root,
        )

        # Publisher mismatch with valid verification mock
        with patch(
            "eval_runner.console.extension_publisher.verify_extension",
            return_value={"valid": True},
        ):
            with pytest.raises(ValueError, match="publisher mismatch"):
                activate_extension(
                    extension_id="act-pub-mismatch",
                    version="1.0.0",
                    publisher="wrong-publisher",
                    artifact_root=root,
                )

    def test_active_release_discovery_and_corrupt_files(self, tmp_path):
        import json

        from eval_runner.console.extension_publisher import (
            get_active_release,
            list_active_releases,
        )

        empty_root = tmp_path / "empty_root"
        empty_root.mkdir()

        # Non-existent active directory
        assert get_active_release(extension_id="ext-1", artifact_root=empty_root) is None
        assert list_active_releases(artifact_root=empty_root) == []

        # Corrupt active records
        active_dir = empty_root / ".active-releases" / "pub1"
        active_dir.mkdir(parents=True, exist_ok=True)
        corrupt_file = active_dir / "ext-1.json"
        corrupt_file.write_text("invalid json", encoding="utf-8")

        # By publisher
        assert (
            get_active_release(
                extension_id="ext-1",
                publisher="pub1",
                artifact_root=empty_root,
            )
            is None
        )
        # Publisher specified but record file not found
        assert (
            get_active_release(
                extension_id="missing-ext",
                publisher="pub-missing",
                artifact_root=empty_root,
            )
            is None
        )
        # Without publisher
        assert get_active_release(extension_id="ext-1", artifact_root=empty_root) is None

        # Multiple records with deduplication and error tolerance
        good_file = active_dir / "ext-good.json"
        good_file.write_text(
            json.dumps({"extension_id": "ext-good", "version": "1.0.0"}),
            encoding="utf-8",
        )
        active_dir2 = empty_root / ".active-releases" / "pub2"
        active_dir2.mkdir(parents=True, exist_ok=True)
        dup_file = active_dir2 / "ext-good.json"
        dup_file.write_text(
            json.dumps({"extension_id": "ext-good", "version": "1.0.0"}),
            encoding="utf-8",
        )

        releases = list_active_releases(artifact_root=empty_root)
        assert len(releases) == 1
        assert releases[0]["extension_id"] == "ext-good"

    def test_verify_extension_failure_branches(self, trust_jail, tmp_path):
        from eval_runner.console.extension_publisher import (
            publish_extension,
            verify_extension,
        )

        root = trust_jail["root"] / ".agentv" / "extensions"
        entry = tmp_path / "chunk_entry.js"
        chunk = tmp_path / "chunk.js"
        chunk.write_text("export const c = 1;", encoding="utf-8")
        entry.write_text('import "./chunk.js";\nexport default c;', encoding="utf-8")

        publish_extension(
            entry=entry,
            extension_id="chunk-ext",
            publisher="configured-publisher",
            version="1.0.0",
            private_key_pem=_private_key_pem_bytes,
            artifact_root=root,
        )

        # Verified extension returns valid=True and loops through chunks
        assert (
            verify_extension(
                extension_id="chunk-ext",
                version="1.0.0",
                public_key_pem=_public_key_pem_bytes,
                artifact_root=root,
            )["valid"]
            is True
        )

        # Missing manifest
        assert (
            verify_extension(
                extension_id="chunk-ext",
                version="9.9.9",
                public_key_pem=_public_key_pem_bytes,
                artifact_root=root,
            )["reason"]
            == "missing-manifest"
        )

        # Corrupt manifest
        manifest_file = root / "chunk-ext" / "1.0.0" / "entry.manifest.json"
        orig_manifest = manifest_file.read_text(encoding="utf-8")
        manifest_file.write_text("corrupt-json", encoding="utf-8")
        res_corrupt = verify_extension(
            extension_id="chunk-ext",
            version="1.0.0",
            public_key_pem=_public_key_pem_bytes,
            artifact_root=root,
        )
        assert "invalid-manifest" in res_corrupt["reason"]
        manifest_file.write_text(orig_manifest, encoding="utf-8")

        # Missing public key
        assert (
            verify_extension(
                extension_id="chunk-ext",
                version="1.0.0",
                public_key_pem=lambda _: None,
                artifact_root=root,
            )["reason"]
            == "publisher-verification-failed"
        )

        # Missing or corrupt chunk
        chunk_target = root / "chunk-ext" / "1.0.0" / "chunk.js"
        chunk_target.write_text("tampered chunk", encoding="utf-8")
        res_chunk = verify_extension(
            extension_id="chunk-ext",
            version="1.0.0",
            public_key_pem=_public_key_pem_bytes,
            artifact_root=root,
        )
        assert "chunk-sri-mismatch" in res_chunk["reason"]

    def test_repair_extension_failure_branches(self, trust_jail, tmp_path):

        from eval_runner.console.extension_publisher import (
            publish_extension,
            repair_extension,
        )

        root = trust_jail["root"] / ".agentv" / "extensions"
        entry = tmp_path / "rep_entry.js"
        chunk = tmp_path / "rep_chunk.js"
        chunk.write_text("export const c = 10;", encoding="utf-8")
        entry.write_text('import "./rep_chunk.js";\nexport default c;', encoding="utf-8")

        publish_extension(
            entry=entry,
            extension_id="rep-branch-ext",
            publisher="configured-publisher",
            version="1.0.0",
            private_key_pem=_private_key_pem_bytes,
            artifact_root=root,
        )

        # 1. No retained release record
        with pytest.raises(ValueError, match="no retained trusted release record"):
            repair_extension(
                entry=entry,
                extension_id="rep-branch-ext",
                publisher="configured-publisher",
                version="9.9.9",
                public_key_pem=_public_key_pem_bytes,
                artifact_root=root,
            )

        # 2. Corrupt release record
        rec_file = root / ".release-records" / "rep-branch-ext" / "1.0.0.manifest.json"
        orig_rec = rec_file.read_text(encoding="utf-8")
        rec_file.write_text("bad-json", encoding="utf-8")
        with pytest.raises(ValueError, match="retained release record is invalid"):
            repair_extension(
                entry=entry,
                extension_id="rep-branch-ext",
                publisher="configured-publisher",
                version="1.0.0",
                public_key_pem=_public_key_pem_bytes,
                artifact_root=root,
            )
        rec_file.write_text(orig_rec, encoding="utf-8")

        # 3. Publisher mismatch
        with pytest.raises(ValueError, match="repair publisher does not match"):
            repair_extension(
                entry=entry,
                extension_id="rep-branch-ext",
                publisher="wrong-publisher",
                version="1.0.0",
                public_key_pem=_public_key_pem_bytes,
                artifact_root=root,
            )

        # 4. Key verification failure
        with pytest.raises(ValueError, match="publisher verification failed"):
            repair_extension(
                entry=entry,
                extension_id="rep-branch-ext",
                publisher="configured-publisher",
                version="1.0.0",
                public_key_pem=lambda _: None,
                artifact_root=root,
            )

        # 5. Chunk graph mismatch (entry SRI matches, but chunk bytes differ)
        chunk.write_text("export const c = 99999;", encoding="utf-8")
        with pytest.raises(ValueError, match="do not match retained"):
            repair_extension(
                entry=entry,
                extension_id="rep-branch-ext",
                publisher="configured-publisher",
                version="1.0.0",
                public_key_pem=_public_key_pem_bytes,
                artifact_root=root,
            )
        chunk.write_text("export const c = 10;", encoding="utf-8")

        # 6. Successful repair with chunks graph and backup quarantine restoration
        installed_entry = root / "rep-branch-ext" / "1.0.0" / "entry.js"
        installed_entry.write_text("tampered entry", encoding="utf-8")
        rep_res = repair_extension(
            entry=entry,
            extension_id="rep-branch-ext",
            publisher="configured-publisher",
            version="1.0.0",
            public_key_pem=_public_key_pem_bytes,
            artifact_root=root,
        )
        assert rep_res["status"] == "repaired"

        # 7. Repair when target does not exist (prior does not exist)
        import shutil

        target_dir = root / "rep-branch-ext" / "1.0.0"
        shutil.rmtree(target_dir)
        rep_notarget = repair_extension(
            entry=entry,
            extension_id="rep-branch-ext",
            publisher="configured-publisher",
            version="1.0.0",
            public_key_pem=_public_key_pem_bytes,
            artifact_root=root,
        )
        assert rep_notarget["status"] == "repaired"

        # 8. Repair rollback when os.replace fails
        import os

        real_os_replace = os.replace
        replace_calls = 0

        def flaky_replace(src, dst):
            nonlocal replace_calls
            replace_calls += 1
            if replace_calls == 2:
                raise OSError("simulated disk error during staging replace")
            return real_os_replace(src, dst)

        with patch("os.replace", side_effect=flaky_replace):
            with pytest.raises(OSError, match="simulated disk error"):
                repair_extension(
                    entry=entry,
                    extension_id="rep-branch-ext",
                    publisher="configured-publisher",
                    version="1.0.0",
                    public_key_pem=_public_key_pem_bytes,
                    artifact_root=root,
                )

        # 9. Repair rollback when target does not exist and os.replace fails
        shutil.rmtree(target_dir, ignore_errors=True)
        with patch("os.replace", side_effect=OSError("replace error")):
            with pytest.raises(OSError, match="replace error"):
                repair_extension(
                    entry=entry,
                    extension_id="rep-branch-ext",
                    publisher="configured-publisher",
                    version="1.0.0",
                    public_key_pem=_public_key_pem_bytes,
                    artifact_root=root,
                )
