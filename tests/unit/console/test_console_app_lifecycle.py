from unittest.mock import MagicMock, patch

import pytest

from eval_runner.console.app import create_app, manage_pid_file


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


def test_manage_pid_file_stale_pid(tmp_path, monkeypatch):
    """Verify process guard terminates stale instances."""
    from eval_runner import config

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    pid_dir = tmp_path / ".aes"
    pid_dir.mkdir()
    pid_file = pid_dir / "server.pid"

    # Mock a stale PID that exists in the system
    stale_pid = 12345
    pid_file.write_text(str(stale_pid))

    mock_proc = MagicMock()
    mock_proc.name.return_value = "python"

    with patch("psutil.pid_exists", return_value=True):
        with patch("psutil.Process", return_value=mock_proc):
            with patch("os.getpid", return_value=54321):
                manage_pid_file()

                # Check that stale process was terminated
                mock_proc.terminate.assert_called_once()
                # Check that NEW pid was written
                assert pid_file.read_text().strip() == "54321"


def test_manage_pid_file_cleanup_on_exit(tmp_path, monkeypatch):
    """Verify PID file cleanup logic."""
    from eval_runner import config

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    pid_file = tmp_path / ".aes" / "server.pid"

    with patch("atexit.register") as mock_atexit:
        with patch("os.getpid", return_value=999):
            manage_pid_file()

            # Extract the cleanup function registered with atexit
            cleanup_func = mock_atexit.call_args[0][0]

            # 1. Verify it removes the file if PID matches
            assert pid_file.exists()
            cleanup_func()
            assert not pid_file.exists()

            # 2. Verify it DOES NOT remove if PID changed (another process started)
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            pid_file.write_text("888")
            cleanup_func()
            assert pid_file.exists()
