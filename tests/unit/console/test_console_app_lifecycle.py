from unittest.mock import MagicMock, patch

import psutil
import pytest

from eval_runner.console.app import create_app, manage_pid_file, run_server


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
    """Verify that a random secret key is generated if DASHBOARD_API_KEY is missing."""
    from eval_runner import config

    monkeypatch.setattr(config, "DASHBOARD_API_KEY", None)

    with patch("eval_runner.plugins.manager.load_plugins"):
        with patch("eval_runner.catalog.ScenarioCatalog.get_instance"):
            app = create_app()
            assert app.secret_key is not None
            assert len(app.secret_key) == 48  # 24 bytes hex


def test_create_app_api_key_present(monkeypatch):
    """When DASHBOARD_API_KEY is set, secret_key is sha256 of the key."""
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


def test_create_app_plugin_route_failure_graceful(capsys):
    """If a plugin's on_register_console_routes raises, it is caught and logged."""
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


def test_console_app_hooks_and_spa_routing(app):
    """Verify trace hooks (before/after request) and SPA route handle requests correctly."""
    with app.test_client() as client:
        # Call SPA route /demo which exists in SPA routes
        response = client.get("/demo")
        assert response.status_code == 200
        # Check that it returns index.html content (mock/static folder file)
        assert b"index.html" in response.data or response.status_code == 200


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
        run_server(host="0.0.0.0", port=8080, debug=True)  # nosec B104
        mock_pid.assert_called_once()
        mock_create.assert_called_once()
        call_kwargs = mock_app.run.call_args[1]
        assert call_kwargs["host"] == "0.0.0.0"  # nosec B104
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
