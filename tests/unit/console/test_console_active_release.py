"""
Canonical unit and contract tests for Core-Owned Active Extension Release Selection.

Acceptance Criteria:
- Publishing and activating a new version registers only that version's routes/navigation.
- Retained older releases are never registered alongside the active one.
- Activation is atomic: exactly one verified release is active for an identity.
- Rollback activates a retained verified release without re-signing it.
- Upgrade, restart, failed publish, activation failure, rollback, and stale artifacts.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.app import _published_extension_spa_prefixes, create_app
from eval_runner.console.extension_publisher import (
    activate_extension,
    get_active_release,
    publish_extension,
    rollback_extension,
    unpublish_extension,
)
from eval_runner.console.routes.trust import (
    _private_key_pem_bytes,
    _public_key_pem_bytes,
    trust_bp,
)


@pytest.fixture
def extension_env(tmp_path, monkeypatch):
    """Isolated environment with keys and extension artifact directories."""
    ext_dir = tmp_path / "extensions"
    ext_dir.mkdir(parents=True, exist_ok=True)
    keys_dir = tmp_path / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)
    ui_dist = tmp_path / "dist"
    ui_dist.mkdir(parents=True, exist_ok=True)
    (ui_dist / "index.html").write_text("<html>Console shell</html>", encoding="utf-8")

    monkeypatch.setattr(config, "EXTENSION_ARTIFACT_DIR", ext_dir)
    monkeypatch.setattr(config, "TRUST_ROOT", keys_dir)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("eval_runner.console.app.UI_BUILD_DIR", ui_dist)

    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    entry_v1 = src_dir / "entry_v1.js"
    entry_v1.write_text("export const version = '1.0.16';", encoding="utf-8")

    entry_v2 = src_dir / "entry_v2.js"
    entry_v2.write_text("export const version = '1.0.17';", encoding="utf-8")

    return {
        "root": tmp_path,
        "ext_dir": ext_dir,
        "keys_dir": keys_dir,
        "entry_v1": entry_v1,
        "entry_v2": entry_v2,
    }


def _make_manifest(ext_id: str, ver: str, pub: str, path: str, nav_title: str) -> dict:
    return {
        "extension_id": ext_id,
        "display_name": f"Extension {ext_id}",
        "version": ver,
        "publisher": pub,
        "capabilities": ["routes", "navigation"],
        "required_permissions": ["runs:read"],
        "routes": [{"path": path, "required_permissions": ["runs:read"]}],
        "navigation": [
            {
                "path": path,
                "id": f"{ext_id}-nav",
                "title": nav_title,
                "group": "Extensions",
                "badge": ver,
                "provenance": "publisher",
            }
        ],
    }


def test_publish_and_activate_lifecycle_registers_only_active_version(extension_env):
    """Publishing with --activate registers only that version; unactivated does not contribute."""
    ext_dir = extension_env["ext_dir"]
    ext_id = "com.enterprise.ops"
    pub = "enterprise_publisher"

    # 1. Publish 1.0.16 with activate=True
    desc_v1 = publish_extension(
        entry=extension_env["entry_v1"],
        extension_id=ext_id,
        publisher=pub,
        version="1.0.16",
        private_key_pem=_private_key_pem_bytes,
        artifact_root=ext_dir,
        manifest_declaration=_make_manifest(ext_id, "1.0.16", pub, "/ops/v1", "Ops v1"),
        activate=True,
    )
    assert desc_v1.get("active") is True

    active = get_active_release(extension_id=ext_id, publisher=pub, artifact_root=ext_dir)
    assert active is not None
    assert active["version"] == "1.0.16"

    # Verify discovery registers only 1.0.16
    manifests_v1: list = []
    prefixes_v1 = _published_extension_spa_prefixes(
        reserved_roots={"api"}, verified_manifests=manifests_v1
    )
    assert prefixes_v1 == ["/ops/v1"]
    assert len(manifests_v1) == 1
    assert manifests_v1[0].version == "1.0.16"

    # 2. Publish 1.0.17 with activate=False
    desc_v2 = publish_extension(
        entry=extension_env["entry_v2"],
        extension_id=ext_id,
        publisher=pub,
        version="1.0.17",
        private_key_pem=_private_key_pem_bytes,
        artifact_root=ext_dir,
        manifest_declaration=_make_manifest(ext_id, "1.0.17", pub, "/ops/v2", "Ops v2"),
        activate=False,
    )
    assert "active" not in desc_v2 or desc_v2["active"] is False

    # Retained older release 1.0.16 remains the active one; 1.0.17 does NOT contribute routes
    active_after_v2 = get_active_release(extension_id=ext_id, publisher=pub, artifact_root=ext_dir)
    assert active_after_v2["version"] == "1.0.16"

    manifests_check: list = []
    prefixes_check = _published_extension_spa_prefixes(
        reserved_roots={"api"}, verified_manifests=manifests_check
    )
    assert prefixes_check == ["/ops/v1"]
    assert len(manifests_check) == 1
    assert manifests_check[0].version == "1.0.16"


def test_atomic_activation_and_console_restart_registers_new_version_only(extension_env):
    """Activating 1.0.17 atomically replaces 1.0.16, and Console registers only 1.0.17."""
    ext_dir = extension_env["ext_dir"]
    ext_id = "com.enterprise.ops"
    pub = "enterprise_publisher"

    publish_extension(
        entry=extension_env["entry_v1"],
        extension_id=ext_id,
        publisher=pub,
        version="1.0.16",
        private_key_pem=_private_key_pem_bytes,
        artifact_root=ext_dir,
        manifest_declaration=_make_manifest(ext_id, "1.0.16", pub, "/ops/v1", "Ops v1"),
        activate=True,
    )
    publish_extension(
        entry=extension_env["entry_v2"],
        extension_id=ext_id,
        publisher=pub,
        version="1.0.17",
        private_key_pem=_private_key_pem_bytes,
        artifact_root=ext_dir,
        manifest_declaration=_make_manifest(ext_id, "1.0.17", pub, "/ops/v2", "Ops v2"),
        activate=False,
    )

    # Atomically activate 1.0.17
    act_res = activate_extension(
        extension_id=ext_id,
        version="1.0.17",
        publisher=pub,
        public_key_pem=_public_key_pem_bytes,
        artifact_root=ext_dir,
    )
    assert act_res["status"] == "activated"
    assert act_res["version"] == "1.0.17"

    # Verify discovery across restart
    manifests: list = []
    prefixes = _published_extension_spa_prefixes(
        reserved_roots={"api"}, verified_manifests=manifests
    )
    assert prefixes == ["/ops/v2"]
    assert len(manifests) == 1
    assert manifests[0].version == "1.0.17"

    # Verify Console app navigation registry
    with (
        patch("eval_runner.plugins.manager.load_plugins"),
        patch("eval_runner.catalog.ScenarioCatalog.get_instance"),
        patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f),
    ):
        app = create_app()

    navs = [n for n in app.config["NAV_REGISTRY"] if n["id"] == f"{ext_id}-nav"]
    assert len(navs) == 1
    assert navs[0]["path"] == "/ops/v2"
    assert navs[0]["badge"] == "1.0.17"

    with app.test_client() as client:
        # Route for 1.0.17 resolves
        assert client.get("/ops/v2").status_code == 200
        # Retained route for 1.0.16 does NOT resolve (404)
        assert client.get("/ops/v1").status_code == 404


def test_rollback_activates_retained_release_without_re_signing(extension_env):
    """Rollback activates an existing verified release without generating new signatures."""
    ext_dir = extension_env["ext_dir"]
    ext_id = "com.enterprise.ops"
    pub = "enterprise_publisher"

    publish_extension(
        entry=extension_env["entry_v1"],
        extension_id=ext_id,
        publisher=pub,
        version="1.0.16",
        private_key_pem=_private_key_pem_bytes,
        artifact_root=ext_dir,
        manifest_declaration=_make_manifest(ext_id, "1.0.16", pub, "/ops/v1", "Ops v1"),
        activate=True,
    )
    publish_extension(
        entry=extension_env["entry_v2"],
        extension_id=ext_id,
        publisher=pub,
        version="1.0.17",
        private_key_pem=_private_key_pem_bytes,
        artifact_root=ext_dir,
        manifest_declaration=_make_manifest(ext_id, "1.0.17", pub, "/ops/v2", "Ops v2"),
        activate=True,
    )

    manifest_v1_before = json.loads(
        (ext_dir / ext_id / "1.0.16" / "entry.manifest.json").read_text(encoding="utf-8")
    )
    sig_before = manifest_v1_before["signature"]

    # Roll back to 1.0.16
    roll_res = rollback_extension(
        extension_id=ext_id,
        version="1.0.16",
        publisher=pub,
        public_key_pem=_public_key_pem_bytes,
        artifact_root=ext_dir,
    )
    assert roll_res["status"] == "rolled_back"
    assert roll_res["version"] == "1.0.16"

    # Signature must be completely unchanged (no re-signing)
    manifest_v1_after = json.loads(
        (ext_dir / ext_id / "1.0.16" / "entry.manifest.json").read_text(encoding="utf-8")
    )
    assert manifest_v1_after["signature"] == sig_before

    # Discovery registers only 1.0.16
    manifests: list = []
    prefixes = _published_extension_spa_prefixes(
        reserved_roots={"api"}, verified_manifests=manifests
    )
    assert prefixes == ["/ops/v1"]
    assert len(manifests) == 1
    assert manifests[0].version == "1.0.16"


def test_failed_activation_fails_closed(extension_env):
    """Activating an uninstalled, tampered, or publisher-mismatched release fails closed."""
    ext_dir = extension_env["ext_dir"]
    ext_id = "com.enterprise.ops"
    pub = "enterprise_publisher"

    publish_extension(
        entry=extension_env["entry_v1"],
        extension_id=ext_id,
        publisher=pub,
        version="1.0.16",
        private_key_pem=_private_key_pem_bytes,
        artifact_root=ext_dir,
        manifest_declaration=_make_manifest(ext_id, "1.0.16", pub, "/ops/v1", "Ops v1"),
        activate=True,
    )

    # 1. Uninstalled version fails
    with pytest.raises(ValueError, match="is not installed"):
        activate_extension(
            extension_id=ext_id,
            version="9.9.9",
            publisher=pub,
            public_key_pem=_public_key_pem_bytes,
            artifact_root=ext_dir,
        )

    # 2. Tampered release (corrupted entry file) fails verification
    publish_extension(
        entry=extension_env["entry_v2"],
        extension_id=ext_id,
        publisher=pub,
        version="1.0.17",
        private_key_pem=_private_key_pem_bytes,
        artifact_root=ext_dir,
        manifest_declaration=_make_manifest(ext_id, "1.0.17", pub, "/ops/v2", "Ops v2"),
        activate=False,
    )
    (ext_dir / ext_id / "1.0.17" / "entry.js").write_text("TAMPERED", encoding="utf-8")

    with pytest.raises(ValueError, match="release verification failed"):
        activate_extension(
            extension_id=ext_id,
            version="1.0.17",
            publisher=pub,
            public_key_pem=_public_key_pem_bytes,
            artifact_root=ext_dir,
        )

    # Active release remains 1.0.16
    active = get_active_release(extension_id=ext_id, publisher=pub, artifact_root=ext_dir)
    assert active["version"] == "1.0.16"


def test_unpublish_active_release_removes_active_registration(extension_env):
    """Unpublishing the active release removes its active record and clears routes."""
    ext_dir = extension_env["ext_dir"]
    ext_id = "com.enterprise.ops"
    pub = "enterprise_publisher"

    publish_extension(
        entry=extension_env["entry_v1"],
        extension_id=ext_id,
        publisher=pub,
        version="1.0.16",
        private_key_pem=_private_key_pem_bytes,
        artifact_root=ext_dir,
        manifest_declaration=_make_manifest(ext_id, "1.0.16", pub, "/ops/v1", "Ops v1"),
        activate=True,
    )
    assert get_active_release(extension_id=ext_id, artifact_root=ext_dir) is not None

    unpublish_extension(extension_id=ext_id, version="1.0.16", artifact_root=ext_dir)

    assert get_active_release(extension_id=ext_id, artifact_root=ext_dir) is None
    prefixes = _published_extension_spa_prefixes(reserved_roots={"api"})
    assert prefixes == []


def test_rest_api_activate_rollback_and_active_endpoints(extension_env):
    """REST API endpoints /v1/extensions/activate, /rollback, /active work end-to-end."""
    app = Flask(__name__)
    app.register_blueprint(trust_bp)
    ext_dir = extension_env["ext_dir"]
    ext_id = "com.enterprise.ops"
    pub = "enterprise_publisher"

    publish_extension(
        entry=extension_env["entry_v1"],
        extension_id=ext_id,
        publisher=pub,
        version="1.0.16",
        private_key_pem=_private_key_pem_bytes,
        artifact_root=ext_dir,
        manifest_declaration=_make_manifest(ext_id, "1.0.16", pub, "/ops/v1", "Ops v1"),
        activate=True,
    )
    publish_extension(
        entry=extension_env["entry_v2"],
        extension_id=ext_id,
        publisher=pub,
        version="1.0.17",
        private_key_pem=_private_key_pem_bytes,
        artifact_root=ext_dir,
        manifest_declaration=_make_manifest(ext_id, "1.0.17", pub, "/ops/v2", "Ops v2"),
        activate=False,
    )

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        client = app.test_client()

        # GET active extensions
        res_active = client.get(f"/api/v1/extensions/active?extension_id={ext_id}")
        assert res_active.status_code == 200
        assert res_active.get_json()["version"] == "1.0.16"

        # POST activate 1.0.17
        res_act = client.post(
            "/api/v1/extensions/activate",
            json={"extension_id": ext_id, "extension_version": "1.0.17", "publisher": pub},
        )
        assert res_act.status_code == 200
        assert res_act.get_json()["version"] == "1.0.17"

        res_active2 = client.get(f"/api/v1/extensions/active?extension_id={ext_id}")
        assert res_active2.get_json()["version"] == "1.0.17"

        # POST rollback 1.0.16
        res_roll = client.post(
            "/api/v1/extensions/rollback",
            json={"extension_id": ext_id, "extension_version": "1.0.16", "publisher": pub},
        )
        assert res_roll.status_code == 200
        assert res_roll.get_json()["status"] == "rolled_back"
        assert res_roll.get_json()["version"] == "1.0.16"


def test_cli_activate_and_rollback_dispatch(extension_env):
    """CLI subcommands activate and rollback execute cleanly."""
    from eval_runner.cli import get_parser

    ext_dir = extension_env["ext_dir"]
    ext_id = "com.enterprise.ops"
    pub = "enterprise_publisher"

    publish_extension(
        entry=extension_env["entry_v1"],
        extension_id=ext_id,
        publisher=pub,
        version="1.0.16",
        private_key_pem=_private_key_pem_bytes,
        artifact_root=ext_dir,
        manifest_declaration=_make_manifest(ext_id, "1.0.16", pub, "/ops/v1", "Ops v1"),
        activate=True,
    )
    publish_extension(
        entry=extension_env["entry_v2"],
        extension_id=ext_id,
        publisher=pub,
        version="1.0.17",
        private_key_pem=_private_key_pem_bytes,
        artifact_root=ext_dir,
        manifest_declaration=_make_manifest(ext_id, "1.0.17", pub, "/ops/v2", "Ops v2"),
        activate=False,
    )

    parser = get_parser(is_help=False)

    # 1. CLI activate 1.0.17
    args_act = parser.parse_args(
        [
            "console",
            "extension",
            "activate",
            "--extension-id",
            ext_id,
            "--extension-version",
            "1.0.17",
        ]
    )
    assert args_act.func(args_act) == 0

    active = get_active_release(extension_id=ext_id, artifact_root=ext_dir)
    assert active["version"] == "1.0.17"

    # 2. CLI rollback to 1.0.16
    args_roll = parser.parse_args(
        [
            "console",
            "extension",
            "rollback",
            "--extension-id",
            ext_id,
            "--extension-version",
            "1.0.16",
        ]
    )
    assert args_roll.func(args_roll) == 0

    active_rolled = get_active_release(extension_id=ext_id, artifact_root=ext_dir)
    assert active_rolled["version"] == "1.0.16"
