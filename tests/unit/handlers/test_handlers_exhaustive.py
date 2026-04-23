from unittest.mock import MagicMock, patch

import pytest

from eval_runner import config
from eval_runner.handlers import evaluation, scenarios


@pytest.fixture
def mock_env_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    (tmp_path / "runs").mkdir()
    (tmp_path / "reports" / "certificates").mkdir(parents=True)
    return tmp_path


@pytest.mark.asyncio
async def test_handle_evaluate_error_paths(mock_env_config):
    # evaluation.py 107-172 error handling
    args = MagicMock(path="missing.json", plugin=[])
    with patch("eval_runner.loader.load_dataset", side_effect=Exception("Load Fail")):
        assert await evaluation.handle_evaluate(args) == 1


@pytest.mark.asyncio
async def test_handle_run_error_paths(mock_env_config):
    # evaluation.py 179-234 error handling
    args = MagicMock(scenario="missing.json", plugin=[])
    with patch("eval_runner.loader.load_scenario", side_effect=Exception("Load Fail")):
        assert await evaluation.handle_run(args) == 1


@pytest.mark.asyncio
async def test_handle_replay_error_paths(mock_env_config):
    # evaluation.py 264-311 error handling
    args = MagicMock(run_id="invalid")
    # _resolve_replay_trace returns None -> handled
    with patch("eval_runner.handlers.evaluation._resolve_replay_trace", return_value=None):
        assert await evaluation.handle_replay(args) == 1


@pytest.mark.asyncio
async def test_handle_verify_error_paths(mock_env_config):
    # evaluation.py 317-360 error handling
    args = MagicMock(run_id="run1")
    # File not found
    assert await evaluation.handle_verify(args) == 1


@pytest.mark.asyncio
async def test_handle_gate_error_paths(mock_env_config):
    # evaluation.py 369-439 error handling
    args = MagicMock(run_id="run1")
    # Certificate missing
    assert await evaluation.handle_gate(args) == 1


@pytest.mark.asyncio
async def test_handle_certify_error_paths(mock_env_config):
    # evaluation.py 451-515 error handling
    args = MagicMock(run_id="run1")
    # Trace missing
    assert await evaluation.handle_certify(args) == 1


@pytest.mark.asyncio
async def test_handle_aes_validate_various_paths(tmp_path, capsys):
    # scenarios.py 49-111
    # 1. No files found
    args = MagicMock(path=str(tmp_path / "empty"))
    (tmp_path / "empty").mkdir()
    assert await scenarios.handle_aes_validate(args) == 1
    assert "No AES scenarios found" in capsys.readouterr().out

    # 2. Directory with mixed files
    (tmp_path / "s1.aes.yaml").write_text("aes_version: 1.4")
    (tmp_path / "s2.json").write_text("{}")
    args = MagicMock(path=str(tmp_path), export=None)
    with patch("eval_runner.handlers.scenarios.validator_for"):
        # Should succeed because we patched validator
        assert await scenarios.handle_aes_validate(args) == 0


@pytest.mark.asyncio
async def test_handle_inspect_error_paths(capsys):
    # scenarios.py 130-150
    args = MagicMock(scenario_path="missing.json")
    with patch("eval_runner.loader.load_scenario", side_effect=Exception("Fail")):
        assert await scenarios.handle_inspect(args) == 1


@pytest.mark.asyncio
async def test_handle_mutate_error_paths(tmp_path):
    # scenarios.py 200-220
    args = MagicMock(input="missing.json")
    with patch("eval_runner.loader.load_scenario", side_effect=Exception("Fail")):
        assert await scenarios.handle_mutate(args) == 1


@pytest.mark.asyncio
async def test_handle_spec_to_eval_error_paths():
    # scenarios.py 223-232
    args = MagicMock(input="missing.md")
    assert await scenarios.handle_spec_to_eval(args) == 1


@pytest.mark.asyncio
async def test_handle_import_drift_error_paths():
    # scenarios.py 235-243
    args = MagicMock(input="missing.jsonl")
    with patch(
        "eval_runner.drift_importer.import_trace_as_scenario", side_effect=Exception("Fail")
    ):
        assert await scenarios.handle_import_drift(args) == 1
