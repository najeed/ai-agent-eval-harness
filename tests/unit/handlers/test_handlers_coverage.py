import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.handlers import environment, evaluation, scenarios


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


def test_resolve_replay_trace_security(monkeypatch):
    """Verify security rejection for out-of-jail traces."""
    with patch("eval_runner.utils.is_path_safe", return_value=False):
        res = evaluation._resolve_replay_trace("malicious_id")
        assert res is None


@pytest.mark.asyncio
async def test_handle_evaluate_non_int_attempts(mock_args):
    """Verify fallback for non-integer attempt counts."""
    mock_args.attempts = "many"
    with (
        patch("eval_runner.loader.load_dataset", return_value=[{"id": "s1"}]),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock),
    ):
        res = await evaluation.handle_evaluate(mock_args)
        assert res == 0


# --- 2. Scenarios Handler ---


def test_classify_scenario_fallback():
    """Verify industry classification fallback when ML deps are missing."""
    with patch("sentence_transformers.SentenceTransformer", side_effect=ImportError):
        res = scenarios.classify_scenario({"title": "Loans"})
        assert res["industry"] == "generic"


@pytest.mark.asyncio
async def test_handle_aes_validate_no_files(mock_args, tmp_path):
    """Verify error when no AES files are found in path."""
    mock_args.path = str(tmp_path)
    # Ensure folder is empty
    res = await scenarios.handle_aes_validate(mock_args)
    assert res == 1


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
