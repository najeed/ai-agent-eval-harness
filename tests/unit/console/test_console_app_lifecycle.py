import json
import os
from unittest.mock import MagicMock, patch

import psutil
import pytest

from eval_runner.console.app import (
    _published_extension_spa_prefixes,
    create_app,
    manage_pid_file,
    run_server,
)


@pytest.fixture
def app():
    """Create a test instance of the Flask app."""
    # Mocking manager.load_plugins to avoid loading real plugins in test
    with patch("eval_runner.plugins.manager.load_plugins"):
        # Mocking ScenarioCatalog to avoid heavy indexing
        with patch("eval_runner.catalog.ScenarioCatalog.get_instance"):
            with patch(
                "eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f
            ):
                app = create_app()
                app.config["TESTING"] = True
                return app


# ---------------------------------------------------------------------------
# Route and Handler Tests
# ---------------------------------------------------------------------------


def test_console_app_405_handler(app):
    """Verify the 405 Method Not Allowed handler returns JSON (not HTML)."""
    with app.test_client() as client:
        # POST to a GET-only route like /api/ping
        response = client.post("/api/ping")
        assert response.status_code == 405
        data = response.get_json()
        assert "error" in data
        assert "Method Not Allowed" in data["error"]


def test_console_app_secret_key_fallback(monkeypatch):
    """Verify strict zero-config bootstrap generates a persistent 64-char SHA3-256 secret key."""
    from eval_runner import config

    monkeypatch.setattr(config, "DASHBOARD_API_KEY", None)
    monkeypatch.setattr(config, "SERVICE_API_KEY", None)
    monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
    monkeypatch.delenv("SERVICE_API_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)

    with patch("eval_runner.plugins.manager.load_plugins"):
        with patch("eval_runner.catalog.ScenarioCatalog.get_instance"):
            app = create_app()
            assert app.secret_key is not None
            assert len(app.secret_key) == 64  # Strictly 64-char SHA3-256 bootstrap checksum


def test_console_app_production_missing_keys_fails(monkeypatch, tmp_path):
    """In production, missing keys must raise RuntimeError without ephemeral fallback."""
    from eval_runner import config

    monkeypatch.setattr(config, "DASHBOARD_API_KEY", None)
    monkeypatch.setattr(config, "SERVICE_API_KEY", None)
    monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
    monkeypatch.delenv("SERVICE_API_KEY", raising=False)
    monkeypatch.setenv("AGENTV_ENV", "production")

    fake_ui = tmp_path / "ui_dist"
    fake_ui.mkdir(parents=True, exist_ok=True)
    (fake_ui / "index.html").write_text("<!DOCTYPE html><html></html>", encoding="utf-8")
    monkeypatch.setattr("eval_runner.console.app.UI_BUILD_DIR", fake_ui)

    with patch("eval_runner.plugins.manager.load_plugins"):
        with patch("eval_runner.catalog.ScenarioCatalog.get_instance"):
            with pytest.raises(RuntimeError, match="AGENTV_ENV=production requires"):
                create_app()


def test_create_app_api_key_present(monkeypatch):
    """When DASHBOARD_API_KEY is set, secret_key is sha3_256 checksum of the key."""
    from eval_runner import config

    monkeypatch.setattr(config, "DASHBOARD_API_KEY", "mysecretapikey")

    with patch("eval_runner.plugins.manager.load_plugins"):
        with patch("eval_runner.catalog.ScenarioCatalog.get_instance"):
            app = create_app()
            from eval_runner.utils import crypto

            expected = crypto.checksum("mysecretapikey")
            assert app.secret_key == expected


def test_create_app_demo_disabled():
    """When ENABLE_DEMO is False, ScenarioCatalog.load_index() is called."""
    from eval_runner import config

    with patch.object(config, "ENABLE_DEMO", False):
        mock_catalog = MagicMock()
        mock_instance = MagicMock()
        mock_catalog.get_instance.return_value = mock_instance

        with patch("eval_runner.catalog.ScenarioCatalog", mock_catalog):
            with patch("eval_runner.plugins.manager.load_plugins"):
                create_app()
                mock_instance.load_index.assert_called_once()


def test_create_app_demo_enabled():
    """When ENABLE_DEMO is True, lazy catalog is used (load_index NOT called)."""
    from eval_runner import config

    with patch.object(config, "ENABLE_DEMO", True):
        mock_catalog = MagicMock()
        mock_instance = MagicMock()
        mock_catalog.get_instance.return_value = mock_instance

        with patch("eval_runner.catalog.ScenarioCatalog", mock_catalog):
            with patch("eval_runner.plugins.manager.load_plugins"):
                create_app()
                mock_instance.load_index.assert_not_called()


def test_create_app_skips_external_plugins_by_default(monkeypatch):
    """Console startup must not import optional distributed plugin runtimes."""
    monkeypatch.delenv("AGENTV_ENABLE_EXTERNAL_CONSOLE_PLUGINS", raising=False)

    with (
        patch("eval_runner.plugins.manager.load_plugins") as load_plugins,
        patch("eval_runner.catalog.ScenarioCatalog.get_instance"),
    ):
        create_app()

    load_plugins.assert_called_once_with(load_external=False)


def test_create_app_can_opt_in_external_console_plugins(monkeypatch):
    """External console extensions remain an explicit operator opt-in."""
    monkeypatch.setenv("AGENTV_ENABLE_EXTERNAL_CONSOLE_PLUGINS", "true")

    with (
        patch("eval_runner.plugins.manager.load_plugins") as load_plugins,
        patch("eval_runner.catalog.ScenarioCatalog.get_instance"),
    ):
        create_app()

    load_plugins.assert_called_once_with(load_external=True)


def test_create_app_plugin_route_failure_graceful(capsys):
    """If a plugin's on_register_console_routes raises, it is caught, recorded, and surfaced."""
    from eval_runner import config

    bad_plugin = MagicMock()
    bad_plugin.on_register_console_routes.side_effect = RuntimeError("Route crash")
    bad_plugin.__class__.__name__ = "BadPlugin"

    with (
        patch.object(config, "ENABLE_DEMO", False),
        patch("eval_runner.plugins.manager.load_plugins"),
        patch("eval_runner.plugins.manager.plugins", [bad_plugin]),
        patch("eval_runner.catalog.ScenarioCatalog.get_instance"),
    ):
        app = create_app()
        assert app is not None
        assert app.config["PLUGIN_REGISTRATION_ERRORS"] == [
            {"plugin": "BadPlugin", "error": "Route crash"}
        ]

        with app.test_client() as c:
            resp = c.get("/api/status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["dependencies"]["plugins"] == "FAILED"
            assert data["status"] == "UNREACHABLE"
            assert any("BadPlugin" in detail for detail in data["details"])


def test_create_app_nav_registry_overrides():
    """Core overrides update nav_registry items that have matching IDs."""
    from eval_runner import config

    nav_with_community = [{"id": "community", "path": "/old_path"}]

    def fake_register_core_routes(app, nav):
        nav.extend(nav_with_community)

    with (
        patch(
            "eval_runner.console.app.register_core_routes", side_effect=fake_register_core_routes
        ),
        patch.object(config, "ENABLE_DEMO", False),
        patch("eval_runner.plugins.manager.load_plugins"),
        patch("eval_runner.catalog.ScenarioCatalog.get_instance"),
    ):
        app = create_app()

    nav = app.config["NAV_REGISTRY"]
    community_item = next((i for i in nav if i.get("id") == "community"), None)
    assert community_item is not None
    assert community_item["path"] == "https://github.com/najeed/ai-agent-eval-harness"


def test_console_app_hooks_and_spa_routing(tmp_path, monkeypatch):
    """[P1.6] SPA routing serves the built Visual Suite when present and
    fails HONESTLY (404) when ui/visual-console/dist is absent -- the legacy
    CDN-loaded fallback was removed; no silent degradation in either state."""
    from eval_runner import config as app_config

    def make_app():
        with patch("eval_runner.plugins.manager.load_plugins"):
            with patch("eval_runner.catalog.ScenarioCatalog.get_instance"):
                with patch(
                    "eval_runner.console.auth_manager.require_permission",
                    lambda _: lambda f: f,
                ):
                    application = create_app()
                    application.config["TESTING"] = True
                    return application

    # State 1: production bundle built -> SPA index is served.
    dist = tmp_path / "ui" / "visual-console" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!DOCTYPE html><html><body>AgentV Visual Console</body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(app_config, "PROJECT_ROOT", tmp_path)
    app_built = make_app()
    with app_built.test_client() as client:
        response = client.get("/")
        assert response.status_code == 200
        assert b"AgentV Visual Console" in response.data

    # State 2: bundle missing -> honest 404, never fabricated content.
    bare_root = tmp_path / "bare"
    (bare_root / "ui" / "visual-console" / "dist").mkdir(parents=True)
    monkeypatch.setattr(app_config, "PROJECT_ROOT", bare_root)
    app_bare = make_app()
    with app_bare.test_client() as client:
        response = client.get("/")
        assert response.status_code == 404


def test_signed_extension_spa_prefix_serves_deep_links_only(tmp_path, monkeypatch):
    """A registered generic extension prefix gets the shell; unknown paths do not."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>Console shell</html>", encoding="utf-8")
    monkeypatch.setattr("eval_runner.console.app.UI_BUILD_DIR", dist)

    with (
        patch("eval_runner.plugins.manager.load_plugins"),
        patch("eval_runner.catalog.ScenarioCatalog.get_instance"),
        patch(
            "eval_runner.console.app._published_extension_spa_prefixes",
            return_value=["/generic-extension"],
        ),
    ):
        application = create_app()

    with application.test_client() as client:
        assert client.get("/generic-extension/admin/licensing").status_code == 200
        assert client.get("/unregistered-extension/admin/licensing").status_code == 404


def test_extension_spa_registry_requires_enabled_verified_manifest_and_rejects_shadows(
    tmp_path, monkeypatch
):
    """Disabled/uninstalled releases and Core-shadowing routes never register."""
    from eval_runner import config

    release = tmp_path / "generic-extension" / "1.0.0"
    release.mkdir(parents=True)
    manifest = {
        "extension_id": "generic-extension",
        "display_name": "Generic Extension",
        "version": "1.0.0",
        "capabilities": ["routes", "navigation"],
        "routes": [
            {
                "path": "/generic-extension",
                "required_permissions": ["runs:read"],
            }
        ],
        "navigation": [
            {
                "path": "/generic-extension",
                "id": "generic-nav",
                "title": "Generic",
                "icon": "shield",
                "group": "Extensions",
                "badge": "NEW",
                "provenance": "publisher",
            }
        ],
        "remote_entry": "/extensions/generic-extension/1.0.0/entry.mjs",
        "sri_hash": "sha3-256-test",
        "publisher": "configured-publisher",
        "signature": "signed",
    }

    (release / "entry.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(config, "EXTENSION_ARTIFACT_DIR", tmp_path)
    empty_store = tmp_path / "no-installed-releases"
    empty_store.mkdir()
    monkeypatch.setattr(config, "EXTENSION_ARTIFACT_DIR", empty_store)
    assert _published_extension_spa_prefixes(reserved_roots={"api"}) == []
    monkeypatch.setattr(config, "EXTENSION_ARTIFACT_DIR", tmp_path)
    monkeypatch.setenv("AGENTV_ENABLED_EXTENSION_IDS", "another-extension")
    with patch(
        "eval_runner.console.extension_publisher.verify_extension", return_value={"valid": True}
    ):
        assert _published_extension_spa_prefixes(reserved_roots={"api"}) == []

    monkeypatch.setenv("AGENTV_ENABLED_EXTENSION_IDS", "generic-extension")
    with patch(
        "eval_runner.console.extension_publisher.verify_extension", return_value={"valid": True}
    ):
        assert _published_extension_spa_prefixes(reserved_roots={"api"}) == ["/generic-extension"]

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>Console shell</html>", encoding="utf-8")
    monkeypatch.setattr("eval_runner.console.app.UI_BUILD_DIR", dist)
    with (
        patch("eval_runner.plugins.manager.load_plugins"),
        patch("eval_runner.catalog.ScenarioCatalog.get_instance"),
        patch(
            "eval_runner.console.extension_publisher.verify_extension",
            return_value={"valid": True},
        ),
    ):
        application = create_app()
    extension_nav = next(
        item for item in application.config["NAV_REGISTRY"] if item["id"] == "generic-nav"
    )
    assert extension_nav == {
        "id": "generic-nav",
        "name": "Generic",
        "path": "/generic-extension",
        "group": "Extensions",
        "badge": "NEW",
        "provenance": "publisher",
        "remoteEntry": "/extensions/generic-extension/1.0.0/entry.mjs",
        "sriHash": "sha3-256-test",
        "required_permissions": ["runs:read"],
        "icon": "shield",
    }
    with application.test_client() as client:
        assert client.get("/generic-extension/admin/licensing").status_code == 200
        assert client.get("/unregistered-extension/admin/licensing").status_code == 404

    manifest["routes"] = [{"path": "/api", "label": "Cannot shadow Core"}]
    (release / "entry.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with patch(
        "eval_runner.console.extension_publisher.verify_extension", return_value={"valid": True}
    ):
        assert _published_extension_spa_prefixes(reserved_roots={"api"}) == []


def test_core_route_map_has_no_enterprise_handler_by_default(tmp_path, monkeypatch):
    """With no Enterprise extension installed, Core route map has no /enterprise handler."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>Console shell</html>", encoding="utf-8")
    monkeypatch.setattr("eval_runner.console.app.UI_BUILD_DIR", dist)

    with (
        patch("eval_runner.plugins.manager.load_plugins"),
        patch("eval_runner.catalog.ScenarioCatalog.get_instance"),
        patch("eval_runner.console.app._published_extension_spa_prefixes", return_value=[]),
    ):
        app = create_app()

    enterprise_rules = [
        rule.rule for rule in app.url_map.iter_rules() if rule.rule.startswith("/enterprise")
    ]
    assert enterprise_rules == []


def test_extension_spa_deep_links_matrix(tmp_path, monkeypatch):
    """
    Verify declared non-colliding paths, Core collisions,
    multiple extensions, and removal/restart.
    """
    import shutil

    from eval_runner import config

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>Console shell</html>", encoding="utf-8")
    monkeypatch.setattr("eval_runner.console.app.UI_BUILD_DIR", dist)

    extensions_dir = tmp_path / "extensions"
    extensions_dir.mkdir()
    monkeypatch.setattr(config, "EXTENSION_ARTIFACT_DIR", extensions_dir)

    # 1. Extension A: Enterprise Operations (multi-segment route tree)
    ext_a = extensions_dir / "enterprise-ops" / "1.0.0"
    ext_a.mkdir(parents=True)
    (ext_a / "entry.mjs").write_text("export default { name: 'enterprise-ops' };", encoding="utf-8")
    manifest_a = {
        "extension_id": "enterprise-ops",
        "display_name": "Enterprise Operations",
        "version": "1.0.0",
        "capabilities": ["routes", "navigation"],
        "routes": [
            {"path": "/enterprise/registry", "required_permissions": ["runs:read"]},
            {"path": "/enterprise/shims", "required_permissions": ["runs:read"]},
        ],
        "navigation": [
            {
                "path": "/enterprise/registry",
                "id": "enterprise-registry-nav",
                "title": "Agent Registry",
                "icon": "shield",
                "group": "Enterprise Operations",
                "badge": "NEW",
                "provenance": "publisher",
            }
        ],
        "remote_entry": "/extensions/enterprise-ops/1.0.0/entry.mjs",
        "sri_hash": "sha3-256-a",
        "publisher": "acme_corp",
        "signature": "sig-a",
    }
    (ext_a / "entry.manifest.json").write_text(json.dumps(manifest_a), encoding="utf-8")

    # 2. Extension B: Partner Analytics (multi-segment tree)
    ext_b = extensions_dir / "partner-analytics" / "2.1.0"
    ext_b.mkdir(parents=True)
    (ext_b / "entry.mjs").write_text("export default { name: 'analytics' };", encoding="utf-8")
    manifest_b = {
        "extension_id": "partner-analytics",
        "display_name": "Partner Analytics",
        "version": "2.1.0",
        "capabilities": ["routes", "navigation"],
        "routes": [{"path": "/partner/analytics/dashboard", "required_permissions": ["runs:read"]}],
        "navigation": [
            {
                "path": "/partner/analytics/dashboard",
                "id": "partner-analytics-nav",
                "title": "Partner Analytics",
                "icon": "activity",
                "group": "Analytics",
                "badge": None,
                "provenance": "publisher",
            }
        ],
        "remote_entry": "/extensions/partner-analytics/2.1.0/entry.mjs",
        "sri_hash": "sha3-256-b",
        "publisher": "partner_corp",
        "signature": "sig-b",
    }
    (ext_b / "entry.manifest.json").write_text(json.dumps(manifest_b), encoding="utf-8")

    # 3. Extension C: Unverified / Tampered extension
    ext_c = extensions_dir / "unverified-ext" / "0.1.0"
    ext_c.mkdir(parents=True)
    manifest_c = {
        "extension_id": "unverified-ext",
        "display_name": "Unverified Extension",
        "version": "0.1.0",
        "capabilities": ["routes"],
        "routes": [{"path": "/enterprise/unverified", "required_permissions": ["runs:read"]}],
        "navigation": [],
        "remote_entry": "/extensions/unverified-ext/0.1.0/entry.mjs",
        "sri_hash": "sha3-256-c",
        "publisher": "bad_actor",
        "signature": "invalid-sig",
    }
    (ext_c / "entry.manifest.json").write_text(json.dumps(manifest_c), encoding="utf-8")

    def mock_verify_extension(extension_id, **_kwargs):
        if extension_id in {"enterprise-ops", "partner-analytics"}:
            return {"valid": True, "reason": None}
        return {"valid": False, "reason": "signature-mismatch"}

    with (
        patch("eval_runner.plugins.manager.load_plugins"),
        patch("eval_runner.catalog.ScenarioCatalog.get_instance"),
        patch(
            "eval_runner.console.extension_publisher.verify_extension",
            side_effect=mock_verify_extension,
        ),
    ):
        app = create_app()

    with app.test_client() as client:
        # A verified signed extension declaring /enterprise/registry receives SPA fallback
        res_registry = client.get("/enterprise/registry")
        assert res_registry.status_code == 200
        assert "Console shell" in res_registry.get_data(as_text=True)

        # Deep links under declared prefix also receive SPA fallback
        res_deep = client.get("/enterprise/registry/agents/agent-123")
        assert res_deep.status_code == 200
        assert "Console shell" in res_deep.get_data(as_text=True)

        res_shims = client.get("/enterprise/shims")
        assert res_shims.status_code == 200

        # Remote entry asset loads directly
        res_entry = client.get("/extensions/enterprise-ops/1.0.0/entry.mjs")
        assert res_entry.status_code == 200
        assert "enterprise-ops" in res_entry.get_data(as_text=True)
        res_entry.close()
        del res_entry

        # Multi-segment partner analytics extension works
        res_partner = client.get("/partner/analytics/dashboard")
        assert res_partner.status_code == 200
        assert "Console shell" in res_partner.get_data(as_text=True)

        # Unverified extension does NOT receive an SPA fallback
        res_unverified = client.get("/enterprise/unverified")
        assert res_unverified.status_code == 404

        # Undeclared enterprise route returns 404
        res_undeclared = client.get("/enterprise/other")
        assert res_undeclared.status_code == 404

    # 4. Route collision: Declaring route colliding with Core /api or /scenarios fails closed
    manifest_a["routes"].append({"path": "/api/custom", "required_permissions": []})
    manifest_a["routes"].append({"path": "/scenarios/shadow", "required_permissions": []})
    (ext_a / "entry.manifest.json").write_text(json.dumps(manifest_a), encoding="utf-8")

    from eval_runner.console.app import _published_extension_spa_prefixes

    with patch(
        "eval_runner.console.extension_publisher.verify_extension",
        side_effect=mock_verify_extension,
    ):
        prefixes = _published_extension_spa_prefixes(
            reserved_roots={"api", "auth", "scenarios", "reports", "assets", "extensions", "v2"}
        )
    assert "/api/custom" not in prefixes
    assert "/scenarios/shadow" not in prefixes
    assert "/enterprise/registry" in prefixes
    assert "/partner/analytics/dashboard" in prefixes

    # 5. Removal / unpublish followed by Console restart clears the routes
    import gc

    gc.collect()
    shutil.rmtree(ext_a)
    with (
        patch("eval_runner.plugins.manager.load_plugins"),
        patch("eval_runner.catalog.ScenarioCatalog.get_instance"),
        patch(
            "eval_runner.console.extension_publisher.verify_extension",
            side_effect=mock_verify_extension,
        ),
    ):
        restarted_app = create_app()

    with restarted_app.test_client() as client:
        # After removal, /enterprise/registry returns 404
        assert client.get("/enterprise/registry").status_code == 404
        # But partner-analytics is still installed and returns 200
        assert client.get("/partner/analytics/dashboard").status_code == 200


# ---------------------------------------------------------------------------
# PID Management Tests
# ---------------------------------------------------------------------------


def test_manage_pid_file_werkzeug_skip(monkeypatch):
    """When WERKZEUG_RUN_MAIN='true', function returns immediately."""
    monkeypatch.setenv("WERKZEUG_RUN_MAIN", "true")
    manage_pid_file()  # no error = pass


def test_manage_pid_file_stale_pid(tmp_path, monkeypatch):
    """Verify process guard terminates stale instances."""
    from eval_runner import config

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    pid_dir = tmp_path / ".aes"
    pid_dir.mkdir()
    pid_file = pid_dir / "server.pid"

    stale_pid = 12345
    pid_file.write_text(str(stale_pid))

    mock_proc = MagicMock()
    mock_proc.name.return_value = "python"

    with patch("psutil.pid_exists", return_value=True):
        with patch("psutil.Process", return_value=mock_proc):
            with patch("os.getpid", return_value=54321):
                manage_pid_file()
                mock_proc.terminate.assert_called_once()
                assert pid_file.read_text().strip() == "54321"


def test_manage_pid_file_no_existing_pid(tmp_path, monkeypatch):
    """When pid_path doesn't exist yet, a fresh PID is written."""
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    from eval_runner import config

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    with patch("os.getpid", return_value=42), patch("atexit.register"):
        manage_pid_file()

    pid_file = tmp_path / ".aes" / "server.pid"
    assert pid_file.read_text().strip() == "42"


def test_manage_pid_file_stale_non_python_pid(tmp_path, monkeypatch):
    """Stale PID for a non-python process is NOT terminated."""
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    from eval_runner import config

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    pid_dir = tmp_path / ".aes"
    pid_dir.mkdir()
    pid_file = pid_dir / "server.pid"
    pid_file.write_text("99999")

    mock_proc = MagicMock()
    mock_proc.name.return_value = "nginx"

    with (
        patch("psutil.pid_exists", return_value=True),
        patch("psutil.Process", return_value=mock_proc),
        patch("os.getpid", return_value=12345),
        patch("atexit.register"),
    ):
        manage_pid_file()

    mock_proc.terminate.assert_not_called()
    assert pid_file.read_text().strip() == "12345"


def test_manage_pid_file_stale_pid_timeout_kills(tmp_path, monkeypatch):
    """When terminate() times out, kill() is called."""
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    from eval_runner import config

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    pid_dir = tmp_path / ".aes"
    pid_dir.mkdir()
    pid_file = pid_dir / "server.pid"
    pid_file.write_text("88888")

    mock_proc = MagicMock()
    mock_proc.name.return_value = "python"
    mock_proc.wait.side_effect = psutil.TimeoutExpired(pid=88888, seconds=5)

    with (
        patch("psutil.pid_exists", return_value=True),
        patch("psutil.Process", return_value=mock_proc),
        patch("os.getpid", return_value=77777),
        patch("atexit.register"),
    ):
        manage_pid_file()

    mock_proc.terminate.assert_called_once()
    mock_proc.kill.assert_called_once()


def test_manage_pid_file_pid_read_exception(tmp_path, monkeypatch):
    """Exception reading the stale PID is caught gracefully."""
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    from eval_runner import config

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    pid_dir = tmp_path / ".aes"
    pid_dir.mkdir()
    pid_file = pid_dir / "server.pid"
    pid_file.write_text("not_a_number")

    with patch("os.getpid", return_value=55555), patch("atexit.register"):
        manage_pid_file()

    assert pid_file.read_text().strip() == "55555"


def test_manage_pid_file_cleanup_on_exit(tmp_path, monkeypatch):
    """Verify PID file cleanup logic."""
    from eval_runner import config

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    pid_file = tmp_path / ".aes" / "server.pid"

    with patch("atexit.register") as mock_atexit:
        with patch("os.getpid", return_value=999):
            manage_pid_file()
            cleanup_func = mock_atexit.call_args[0][0]

            assert pid_file.exists()
            cleanup_func()
            assert not pid_file.exists()

            pid_file.parent.mkdir(parents=True, exist_ok=True)
            pid_file.write_text("888")
            cleanup_func()
            assert pid_file.exists()


def test_manage_pid_file_cleanup_exception(tmp_path, monkeypatch):
    """Exception during cleanup_pid is caught gracefully."""
    monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)
    from eval_runner import config

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    with patch("os.getpid", return_value=333):
        cleanup_func_holder = []

        def capture_atexit(func):
            cleanup_func_holder.append(func)

        with patch("atexit.register", side_effect=capture_atexit):
            manage_pid_file()

        pid_file = tmp_path / ".aes" / "server.pid"
        assert pid_file.exists()

        with patch("builtins.open", side_effect=OSError("permission denied")):
            cleanup_func_holder[0]()


# ---------------------------------------------------------------------------
# Server Run Tests
# ---------------------------------------------------------------------------


def test_run_server_delegates_correctly():
    """run_server calls manage_pid_file, create_app, and app.run with correct args."""
    mock_app = MagicMock()

    with (
        patch("eval_runner.console.app.manage_pid_file") as mock_pid,
        patch("eval_runner.console.app.create_app", return_value=mock_app) as mock_create,
    ):
        test_host = "0.0.0.0"  # nosec B104
        run_server(host=test_host, port=8080, debug=True)
        mock_pid.assert_called_once()
        mock_create.assert_called_once()

        call_kwargs = mock_app.run.call_args[1]
        assert call_kwargs["host"] == test_host
        assert call_kwargs["port"] == 8080
        assert call_kwargs["debug"] is True
        assert call_kwargs["use_reloader"] is True
        assert call_kwargs["extra_files"] == []


def test_run_server_no_debug():
    """run_server with debug=False passes extra_files=None and use_reloader=False."""
    mock_app = MagicMock()

    with (
        patch("eval_runner.console.app.manage_pid_file"),
        patch("eval_runner.console.app.create_app", return_value=mock_app),
    ):
        run_server(host="127.0.0.1", port=5000, debug=False)
        call_kwargs = mock_app.run.call_args[1]
        assert call_kwargs["use_reloader"] is False
        assert call_kwargs["extra_files"] is None


def test_console_app_static_folder_resolution():
    """Verify create_app resolves static folder correctly."""
    from eval_runner.console.app import create_app

    app = create_app()
    assert app.static_folder is not None


class TestConsoleAppExhaustiveCoverage:
    """Exhaustive tests for app.py lifecycle, origins, CSP, and routes."""

    def test_configured_extension_origins_and_safe_route_prefix(self, monkeypatch):
        from eval_runner.console.app import (
            _configured_extension_origins,
            _safe_extension_route_prefix,
        )

        monkeypatch.setenv(
            "AGENTV_EXTENSION_ORIGINS",
            "https://cdn.example.com, http://localhost:8080, http://127.0.0.1:9000, ftp://bad.com, http://remote.com",
        )
        origins = _configured_extension_origins()
        assert "https://cdn.example.com" in origins
        assert "http://localhost:8080" in origins
        assert "http://127.0.0.1:9000" in origins
        assert "ftp://bad.com" not in origins
        assert "http://remote.com" not in origins

        reserved = {"api", "static", "v2"}
        assert _safe_extension_route_prefix("/", reserved) is None
        assert _safe_extension_route_prefix("no-slash", reserved) is None
        assert _safe_extension_route_prefix("/path/with/..", reserved) is None
        assert _safe_extension_route_prefix("/path/with/.", reserved) is None
        assert _safe_extension_route_prefix("/path/with/<param>", reserved) is None
        assert _safe_extension_route_prefix("/path/with/>bad<", reserved) is None
        assert _safe_extension_route_prefix("/api/subpath", reserved) is None
        assert _safe_extension_route_prefix("/custom/ext", reserved) == "/custom/ext"

    def test_published_extension_spa_prefixes_edge_cases(self, tmp_path, monkeypatch):

        from eval_runner import config
        from eval_runner.console.app import _published_extension_spa_prefixes

        ext_root = tmp_path / "ext_root"
        ext_root.mkdir()
        monkeypatch.setattr(config, "EXTENSION_ARTIFACT_DIR", ext_root)

        # 1. Non-existent active directory returns empty
        assert _published_extension_spa_prefixes(reserved_roots={"api"}) == []

        # 2. Active directory with valid, corrupt, and missing records
        active_dir = ext_root / ".active-releases" / "pub1"
        active_dir.mkdir(parents=True)

        # Empty ext_id / ver in active record
        empty_rec = active_dir / "empty-id.json"
        empty_rec.write_text(json.dumps({"extension_id": "", "version": "1.0.0"}), encoding="utf-8")

        # Corrupt JSON active record
        corrupt_rec = active_dir / "bad.json"
        corrupt_rec.write_text("invalid json", encoding="utf-8")

        # Missing manifest file active record
        missing_rec = active_dir / "missing.json"
        missing_rec.write_text(
            json.dumps({"extension_id": "missing-ext", "version": "1.0.0", "publisher": "pub1"}),
            encoding="utf-8",
        )

        # Manifest with invalid JSON
        (ext_root / "corrupt-ext" / "1.0.0").mkdir(parents=True)
        corrupt_manifest = ext_root / "corrupt-ext" / "1.0.0" / "entry.manifest.json"
        corrupt_manifest.write_text("not json", encoding="utf-8")
        corrupt_man_rec = active_dir / "corrupt-ext.json"
        corrupt_man_rec.write_text(
            json.dumps({"extension_id": "corrupt-ext", "version": "1.0.0", "publisher": "pub1"}),
            encoding="utf-8",
        )

        # Manifest with publisher mismatch (manifest itself is contract-valid)
        (ext_root / "pub-mismatch" / "1.0.0").mkdir(parents=True)
        mismatch_manifest = ext_root / "pub-mismatch" / "1.0.0" / "entry.manifest.json"
        mismatch_manifest.write_text(
            json.dumps(
                {
                    "extension_id": "pub-mismatch",
                    "display_name": "Pub Mismatch",
                    "version": "1.0.0",
                    "publisher": "actual-pub",
                    "remote_entry": "/extensions/pub-mismatch/1.0.0/entry.js",
                    "sri_hash": "sha3-256-abc",
                    "signature": "valid-sig",
                    "capabilities": ["routes"],
                    "routes": [{"path": "/mismatch/route"}],
                }
            ),
            encoding="utf-8",
        )
        mismatch_rec = active_dir / "pub-mismatch.json"
        mismatch_rec.write_text(
            json.dumps(
                {"extension_id": "pub-mismatch", "version": "1.0.0", "publisher": "expected-pub"}
            ),
            encoding="utf-8",
        )

        # Duplicate extension ID across candidates
        (ext_root / "dup-ext" / "1.0.0").mkdir(parents=True)
        dup_manifest = ext_root / "dup-ext" / "1.0.0" / "entry.manifest.json"
        dup_manifest.write_text(
            json.dumps(
                {
                    "extension_id": "dup-ext",
                    "display_name": "Dup Ext",
                    "version": "1.0.0",
                    "publisher": "pub1",
                    "remote_entry": "/extensions/dup-ext/1.0.0/entry.js",
                    "sri_hash": "sha3-256-abc",
                    "signature": "valid-sig",
                    "capabilities": ["routes"],
                    "routes": [{"path": "/dup/route"}],
                }
            ),
            encoding="utf-8",
        )
        dup_rec1 = active_dir / "dup-ext1.json"
        dup_rec1.write_text(
            json.dumps({"extension_id": "dup-ext", "version": "1.0.0", "publisher": "pub1"}),
            encoding="utf-8",
        )
        active_dir2 = ext_root / ".active-releases" / "pub2"
        active_dir2.mkdir(parents=True)
        dup_rec2 = active_dir2 / "dup-ext2.json"
        dup_rec2.write_text(
            json.dumps({"extension_id": "dup-ext", "version": "1.0.0", "publisher": "pub1"}),
            encoding="utf-8",
        )

        mock_verification = {"valid": True}
        with patch(
            "eval_runner.console.extension_publisher.verify_extension",
            return_value=mock_verification,
        ):
            prefixes = _published_extension_spa_prefixes(reserved_roots={"api"})
            assert "/dup/route" in prefixes

    def test_create_app_production_and_bootstrap_and_security(self, tmp_path, monkeypatch):
        import eval_runner.console.app as console_app
        from eval_runner import config
        from eval_runner.console.app import create_app

        # 1. Production missing visual-console dist raises RuntimeError
        monkeypatch.setattr(config, "is_production", lambda: True)
        monkeypatch.setattr(console_app, "UI_BUILD_DIR", str(tmp_path / "nonexistent_ui_dist"))
        with pytest.raises(
            RuntimeError, match="Production environment .* requires built visual-console artifact"
        ):
            create_app()
        monkeypatch.setattr(config, "is_production", lambda: False)

        # 2. Zero-config bootstrap key generation and chmod handling
        dummy_project_root = tmp_path / "project_root"
        dummy_project_root.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(config, "PROJECT_ROOT", dummy_project_root)
        monkeypatch.setattr(config, "SERVICE_API_KEY", None)
        monkeypatch.setattr(config, "DASHBOARD_API_KEY", None)
        monkeypatch.delenv("SERVICE_API_KEY", raising=False)
        monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)

        # Mock os.chmod to trigger OSError branch
        def mock_chmod(path, mode):
            raise OSError("simulated chmod error")

        with patch("os.chmod", side_effect=mock_chmod):
            app1 = create_app()
            assert app1 is not None
            assert config.SERVICE_API_KEY is not None

        # Existing bootstrap key file read branch
        app_existing_boot = create_app()
        assert app_existing_boot is not None

        # Bootstrap key writing exception handling
        dummy_project_root_ro = tmp_path / "ro_root"
        dummy_project_root_ro.mkdir()
        monkeypatch.setattr(config, "PROJECT_ROOT", dummy_project_root_ro)
        monkeypatch.setattr(config, "SERVICE_API_KEY", None)
        monkeypatch.setattr(config, "DASHBOARD_API_KEY", None)

        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            app_ro = create_app()
            assert app_ro is not None

        # 3. Dashboard API key fallback when only SERVICE_API_KEY is configured
        monkeypatch.setattr(config, "SERVICE_API_KEY", "srv-key-only")
        monkeypatch.setattr(config, "DASHBOARD_API_KEY", None)
        monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
        create_app()
        assert config.DASHBOARD_API_KEY == "srv-key-only"

        # 4. Missing API keys and secret keys raises RuntimeError
        monkeypatch.delenv("SERVICE_API_KEY", raising=False)
        monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)

        real_getattr = getattr

        def mock_console_getattr(obj, name, default=None):
            if obj is config and name in ("SERVICE_API_KEY", "DASHBOARD_API_KEY"):
                if mock_console_getattr.calls < 2:
                    mock_console_getattr.calls += 1
                    return "initial_bootstrap_key"
                return default
            return real_getattr(obj, name, default)

        mock_console_getattr.calls = 0
        monkeypatch.setattr(console_app, "getattr", mock_console_getattr, raising=False)
        with pytest.raises(RuntimeError, match="Missing API key or secret key"):
            create_app()
        monkeypatch.delattr(console_app, "getattr", raising=False)

        # 4b. Pre-set DASHBOARD_API_KEY during bootstrap keygen (branch 238->241)
        def mock_dash_preset(obj, name, default=None):
            if obj is config and name == "DASHBOARD_API_KEY":
                if mock_dash_preset.calls == 0:
                    mock_dash_preset.calls += 1
                    return None
                return "preset_dash_key"
            return real_getattr(obj, name, default)

        mock_dash_preset.calls = 0
        monkeypatch.setattr(console_app, "getattr", mock_dash_preset, raising=False)
        monkeypatch.setattr(config, "SERVICE_API_KEY", None)
        monkeypatch.delenv("SERVICE_API_KEY", raising=False)
        monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
        app_preset = create_app()
        assert app_preset is not None
        monkeypatch.delattr(console_app, "getattr", raising=False)

        # 5. CORS initialization when ALLOWED_ORIGINS is configured
        monkeypatch.setattr(config, "SERVICE_API_KEY", "test-key")
        monkeypatch.setattr(config, "DASHBOARD_API_KEY", "test-key")
        monkeypatch.setattr(config, "ALLOWED_ORIGINS", ["https://console.example.com"])
        app_cors = create_app()
        assert app_cors is not None

    def test_create_app_csp_airgap_and_custom_sources(self, tmp_path, monkeypatch):
        import eval_runner.console.app as console_app
        from eval_runner import config
        from eval_runner.console.app import create_app

        ui_dir = tmp_path / "ui_csp"
        ui_dir.mkdir()
        (ui_dir / "index.html").write_text(
            "<!DOCTYPE html><html><body>Console</body></html>", encoding="utf-8"
        )
        monkeypatch.setattr(console_app, "UI_BUILD_DIR", str(ui_dir))
        monkeypatch.setattr(config, "SERVICE_API_KEY", "test-key")
        monkeypatch.setattr(config, "DASHBOARD_API_KEY", "test-key")

        # Non-airgapped mode includes jsdelivr
        monkeypatch.setattr(config, "is_airgapped", lambda: False)
        app_non_air = create_app()
        client_non_air = app_non_air.test_client()
        resp_non_air = client_non_air.get("/")
        assert resp_non_air.status_code == 200
        csp_non_air = resp_non_air.headers.get("Content-Security-Policy", "")
        assert "https://cdn.jsdelivr.net" in csp_non_air

        # Airgapped mode with custom script/connect sources and extension origins
        # Including duplicate 'self' to exercise deduplication branches
        monkeypatch.setattr(config, "is_airgapped", lambda: True)
        monkeypatch.setattr(config, "CONSOLE_CSP_SCRIPT_SRC", "'self' https://custom.script.com")
        monkeypatch.setattr(config, "CONSOLE_CSP_CONNECT_SRC", "'self' https://custom.connect.com")
        monkeypatch.setenv("AGENTV_EXTENSION_ORIGINS", "https://ext.example.com")

        app = create_app()
        client = app.test_client()
        resp = client.get("/")
        assert resp.status_code == 200
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "https://cdn.jsdelivr.net" not in csp
        assert "https://custom.script.com" in csp
        assert "https://custom.connect.com" in csp
        assert "https://ext.example.com" in csp
        assert resp.headers.get("X-AgentV-Extension-Origins") == "https://ext.example.com"

    def test_static_assets_and_demo_routes(self, tmp_path, monkeypatch):
        import shutil

        import eval_runner.console.app as console_app
        from eval_runner import config
        from eval_runner.console.app import create_app

        ui_dir = tmp_path / "ui_assets"
        assets_dir = ui_dir / "assets"
        assets_dir.mkdir(parents=True)
        (assets_dir / "main.css").write_text("body { color: black; }", encoding="utf-8")
        (ui_dir / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
        (ui_dir / "index.html").write_text("<html>Console</html>", encoding="utf-8")

        monkeypatch.setattr(console_app, "UI_BUILD_DIR", str(ui_dir))
        monkeypatch.setattr(config, "SERVICE_API_KEY", "test-key")
        monkeypatch.setattr(config, "DASHBOARD_API_KEY", "test-key")
        monkeypatch.setattr(config, "ENABLE_DEMO", True)

        ext_dir = tmp_path / "ext_artifacts"
        (ext_dir / "pkg" / "1.0.0").mkdir(parents=True)
        (ext_dir / "pkg" / "1.0.0" / "file.js").write_text("console.log('ext');", encoding="utf-8")
        monkeypatch.setattr(config, "EXTENSION_ARTIFACT_DIR", ext_dir)

        app = create_app()
        client = app.test_client()

        # Assets route
        assert client.get("/assets/main.css").status_code == 200
        assert client.get("/assets/nonexistent.css").status_code == 404

        # Extension route - existing file
        assert client.get("/extensions/pkg/1.0.0/file.js").status_code == 200

        # Extensions route when EXTENSION_ARTIFACT_DIR does not exist
        monkeypatch.setattr(config, "EXTENSION_ARTIFACT_DIR", tmp_path / "nonexistent_ext_dir")
        assert client.get("/extensions/some/file.js").status_code == 404

        # V2 assets route
        assert client.get("/v2/assets/main.css").status_code == 200
        assert client.get("/v2/assets/missing.css").status_code == 404

        # Root icons route
        assert client.get("/favicon.svg").status_code == 200
        assert client.get("/logo-premium.png").status_code == 404

        # V2 compatibility route
        assert client.get("/v2").status_code == 200
        assert client.get("/v2/").status_code == 200
        (ui_dir / "test_file.txt").write_text("hello", encoding="utf-8")
        assert client.get("/v2/test_file.txt").status_code == 200
        # V2 SPA fallback for nonexistent subpath
        assert client.get("/v2/nonexistent_subpath").status_code == 200

        # Demo routes
        assert client.get("/demo").status_code == 200
        assert client.get("/demo/loan").status_code == 200

        # Missing assets directory on ui_path
        shutil.rmtree(assets_dir)
        assert client.get("/assets/any.css").status_code == 404
        assert client.get("/v2/assets/any.css").status_code == 404

    def test_manage_pid_file_edge_cases(self, tmp_path, monkeypatch):
        from eval_runner import config
        from eval_runner.console.app import manage_pid_file, run_server

        # Skip when WERKZEUG_RUN_MAIN is true
        monkeypatch.setenv("WERKZEUG_RUN_MAIN", "true")
        manage_pid_file()
        monkeypatch.delenv("WERKZEUG_RUN_MAIN", raising=False)

        aes_dir = tmp_path / ".aes"
        aes_dir.mkdir(parents=True)
        pid_file = aes_dir / "server.pid"
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

        # Empty pid file
        pid_file.write_text("", encoding="utf-8")
        manage_pid_file()
        assert pid_file.read_text().strip() == str(os.getpid())

        # Invalid int in pid file
        pid_file.write_text("invalid_pid_string", encoding="utf-8")
        manage_pid_file()
        assert pid_file.read_text().strip() == str(os.getpid())

        # Dead PID
        pid_file.write_text("99999999", encoding="utf-8")
        with patch("psutil.pid_exists", return_value=False):
            manage_pid_file()
        assert pid_file.read_text().strip() == str(os.getpid())

        # Stale instance running python that times out on terminate and requires kill
        pid_file.write_text("12345", encoding="utf-8")
        mock_proc = MagicMock()
        mock_proc.name.return_value = "python.exe"
        mock_proc.wait.side_effect = psutil.TimeoutExpired(5)

        with patch("psutil.pid_exists", return_value=True):
            with patch("psutil.Process", return_value=mock_proc):
                manage_pid_file()
                mock_proc.terminate.assert_called_once()
                mock_proc.kill.assert_called_once()

        # Stale non-python instance does not terminate
        pid_file.write_text("12346", encoding="utf-8")
        mock_non_py = MagicMock()
        mock_non_py.name.return_value = "notepad.exe"
        with patch("psutil.pid_exists", return_value=True):
            with patch("psutil.Process", return_value=mock_non_py):
                manage_pid_file()
                mock_non_py.terminate.assert_not_called()

        if pid_file.exists():
            pid_file.unlink()

        # Cleanup PID registered with atexit
        registered_callbacks = []
        with patch("atexit.register", side_effect=lambda fn: registered_callbacks.append(fn)):
            manage_pid_file()

        assert len(registered_callbacks) == 1
        cleanup_fn = registered_callbacks[0]

        # Case A: pid_file exists and matches os.getpid() -> unlinked
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        cleanup_fn()
        assert not pid_file.exists()

        # Case B: pid_file does not exist -> no-op
        cleanup_fn()

        # Case C: pid_file has a different pid -> not unlinked
        pid_file.write_text("11111", encoding="utf-8")
        cleanup_fn()
        assert pid_file.exists()

        # Case D: pid_file.unlink raises OSError -> handled
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        from pathlib import Path

        with patch.object(Path, "unlink", side_effect=OSError("permission denied")):
            cleanup_fn()

        # run_server execution with debug=True
        with patch("eval_runner.console.app.manage_pid_file") as mock_manage:
            mock_app = MagicMock()
            with patch("eval_runner.console.app.create_app", return_value=mock_app):
                run_server(host="127.0.0.1", port=5000, debug=True)
                mock_manage.assert_called_once()
                mock_app.run.assert_called_once_with(
                    host="127.0.0.1",
                    port=5000,
                    debug=True,
                    use_reloader=True,
                    reloader_interval=2,
                    threaded=True,
                    extra_files=[],
                )

    def test_telemetry_loopback_filtering_in_debug_and_production(self, monkeypatch, tmp_path):
        import io
        import logging

        from eval_runner.console.app import create_app

        # 1. Production Mode: loopback filtered
        monkeypatch.setenv("AGENTV_DEBUG", "0")
        monkeypatch.setenv("DEBUG", "0")
        app = create_app()
        app.debug = False
        client = app.test_client()

        # Check Werkzeug log filter
        w_logger = logging.getLogger("werkzeug")
        assert any(f.__class__.__name__ == "TelemetryLoopbackFilter" for f in w_logger.filters)
        telemetry_filter = next(
            f for f in w_logger.filters if f.__class__.__name__ == "TelemetryLoopbackFilter"
        )
        rec_200 = logging.LogRecord(
            name="werkzeug",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg='127.0.0.1 - - "POST /api/debugger/state HTTP/1.1" 200 -',
            args=(),
            exc_info=None,
        )
        assert telemetry_filter.filter(rec_200) is False

        rec_500 = logging.LogRecord(
            name="werkzeug",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg='127.0.0.1 - - "POST /api/debugger/state HTTP/1.1" 500 -',
            args=(),
            exc_info=None,
        )
        assert telemetry_filter.filter(rec_500) is True

        # Check request/response stderr tracing in production
        stderr_capture = io.StringIO()
        monkeypatch.setattr("sys.stderr", stderr_capture)

        # GET /api/debugger/state (returns 200 or 204 or whatever is configured)
        client.get("/api/debugger/state")
        trace_output = stderr_capture.getvalue()
        assert "/api/debugger/state" not in trace_output

        # Non-telemetry endpoint still emits trace
        stderr_capture.truncate(0)
        stderr_capture.seek(0)
        client.get("/favicon.svg")
        trace_output = stderr_capture.getvalue()
        assert "[Trace] GET /favicon.svg" in trace_output

        # 2. Debug Mode: loopback trace is preserved
        monkeypatch.setenv("AGENTV_DEBUG", "1")
        app_debug = create_app()
        client_debug = app_debug.test_client()

        stderr_capture.truncate(0)
        stderr_capture.seek(0)
        client_debug.get("/api/debugger/state")
        debug_trace_output = stderr_capture.getvalue()
        assert "[Trace] GET /api/debugger/state" in debug_trace_output
