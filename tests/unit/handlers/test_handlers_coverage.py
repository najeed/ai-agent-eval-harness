import os
from unittest.mock import MagicMock, patch

import pytest

from eval_runner.handlers import environment, evaluation


@pytest.fixture
def mock_args():
    args = MagicMock()
    args.agent = "http://localhost:8080"
    args.protocol = "http"
    args.path = "scenarios"
    args.attempts = 1
    return args


# --- 1. Evaluation Handler ---


def test_prepare_agent_env_socket(monkeypatch):
    """Verify socket protocol environment setup."""
    args = MagicMock()
    args.protocol = "socket"
    args.agent_socket = "127.0.0.1:9000"

    evaluation.prepare_agent_env(args)
    assert os.environ.get("AGENT_SOCKET_ADDR") == "127.0.0.1:9000"


@pytest.mark.asyncio
async def test_replay_rejects_missing_provider_evidence():
    """Replay reads only provider events and has no filesystem recovery path."""
    provider = MagicMock()
    provider.get_events.return_value = []
    with patch("eval_runner.runtime_services.resolve_run_store", return_value=provider):
        assert await evaluation.handle_replay(MagicMock(run_id="malicious_id")) == 1


# --- 3. Environment Handler ---


def test_list_industries_fallback():
    """Verify industry list fallback on registry load failure."""
    with patch("eval_runner.registry_sync.load_registry", side_effect=Exception("Load error")):
        industries = environment.list_industries()
        # Should still have standard defaults
        assert "finance" in industries
        assert "generic" in industries


def test_detect_framework_req_failure(tmp_path, monkeypatch):
    """Verify framework detection resilience on requirements.txt Read error."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "requirements.txt").write_text("some content")

    with patch("pathlib.Path.read_text", side_effect=PermissionError("Locked")):
        res = environment.detect_framework()
        assert res == "Custom"


@pytest.mark.asyncio
async def test_handle_doctor_error_handling(mock_args):
    """Verify doctor handler error reporting."""
    with patch("eval_runner.doctor.run_doctor", side_effect=RuntimeError("Audit failed")):
        res = await environment.handle_doctor(mock_args)
        assert res == 1


@pytest.mark.asyncio
async def test_handle_plugin_list_error(mock_args):
    """Verify plugin listing error handling."""
    with patch("eval_runner.plugins.manager.load_plugins", side_effect=Exception("Plugin error")):
        res = await environment.handle_plugin_list(mock_args)
        assert res == 1
