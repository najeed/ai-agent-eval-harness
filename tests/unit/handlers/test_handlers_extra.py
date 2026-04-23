import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

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
async def test_ensure_path_safe_failure(mock_env_config, capsys):
    # evaluation.py 31-33
    assert evaluation._ensure_path_safe("/outside/project") is False
    assert "Security Error" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_resolve_replay_trace_variants(mock_env_config):
    # evaluation.py 43-64
    assert evaluation._resolve_replay_trace("") is None

    # Security check failure (relative traversal)
    assert evaluation._resolve_replay_trace("../traversal") is None

    # Vault hit
    run_id = "run1"
    vault_dir = mock_env_config / "runs" / run_id
    vault_dir.mkdir()
    trace_file = vault_dir / "run.jsonl"
    trace_file.write_text("[]")
    assert evaluation._resolve_replay_trace(run_id) == trace_file.resolve()

    # Master hit
    master_file = mock_env_config / "runs" / "run.jsonl"
    master_file.write_text("[]")
    trace_file.unlink()
    assert evaluation._resolve_replay_trace(run_id) == master_file.resolve()


@pytest.mark.asyncio
async def test_prepare_agent_env_branches():
    # evaluation.py 73-80
    args = MagicMock(protocol="local", agent_cmd="my_cmd")
    evaluation.prepare_agent_env(args)
    assert os.environ.get("AGENT_LOCAL_CMD") == "my_cmd"

    args = MagicMock(protocol="socket", agent_socket="localhost:1234")
    evaluation.prepare_agent_env(args)
    assert os.environ.get("AGENT_SOCKET_ADDR") == "localhost:1234"


@pytest.mark.asyncio
async def test_load_plugins_error_handling(capsys):
    # evaluation.py 98-101
    with patch("eval_runner.plugins.manager.load", side_effect=Exception("Plugin Crash")):
        evaluation.load_plugins_from_args(MagicMock(plugin=["bad_plugin"]))
    assert "Warning: Failed to load plugin" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_handle_evaluate_full_flow(mock_env_config):
    # evaluation.py 107-172
    args = MagicMock(
        path="scenarios.json",
        run_log_dir=str(mock_env_config / "custom_logs"),
        per_run_logs=True,
        master_log=True,
        seed="test_seed",
        format="json",
        plugin=[],
        protocol="http",
        agent="http://agent",
        attempts=2,
        run_id="test_run",
    )
    scenarios_list = [{"id": "s1", "title": "S1"}, {"id": "s2"}]
    with (
        patch("eval_runner.loader.load_dataset", return_value=scenarios_list),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as mock_run,
    ):
        assert await evaluation.handle_evaluate(args) == 0
        assert mock_run.call_count == 4  # 2 scenarios * 2 attempts


@pytest.mark.asyncio
async def test_handle_run_full_flow(mock_env_config):
    # evaluation.py 179-234
    args = MagicMock(
        scenario="s1.json",
        run_log_dir=None,
        per_run_logs=None,
        master_log=None,
        seed=None,
        plugin=[],
        protocol="http",
        agent="http://agent",
        attempts=1,
        run_id="run1",
    )
    with (
        patch("eval_runner.loader.load_scenario", return_value={"id": "s1"}),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock) as mock_run,
    ):
        assert await evaluation.handle_run(args) == 0
        mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_handle_replay_success(mock_env_config, capsys):
    # evaluation.py 264-311
    run_id = "run_r"
    vault_dir = mock_env_config / "runs" / run_id
    vault_dir.mkdir()
    trace_file = vault_dir / "run.jsonl"
    events = [
        {"event": "run_start", "run_id": run_id, "scenario": "sc1"},
        {"event": "prompt", "role": "user", "content": "hello"},
        {"event": "agent_response", "content": "hi"},
        {"event": "run_end", "status": "success"},
    ]
    with open(trace_file, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    args = MagicMock(run_id=run_id)
    assert await evaluation.handle_replay(args) == 0
    out = capsys.readouterr().out
    assert "Run Started" in out
    assert "[USER]: hello" in out
    assert "Agent: hi" in out


@pytest.mark.asyncio
async def test_handle_verify_success(mock_env_config, capsys):
    # evaluation.py 317-360
    run_id = "run_v"
    run_dir = mock_env_config / "runs" / run_id
    run_dir.mkdir()
    (run_dir / "run.jsonl").write_text("[]")
    (run_dir / "run_manifest.json").write_text("{}")

    args = MagicMock(run_id=run_id)
    with patch(
        "eval_runner.verifier.TraceVerifier.verify_trace_async", new_callable=AsyncMock
    ) as mock_v:
        mock_v.return_value = True
        assert await evaluation.handle_verify(args) == 0


@pytest.mark.asyncio
async def test_handle_gate_success(mock_env_config):
    # evaluation.py 369-439
    run_id = "run_g"
    cert_dir = mock_env_config / "reports" / "certificates"
    cert_file = cert_dir / f"{run_id}_vc.json"
    cert_file.write_text(json.dumps({"trace_file": "run.jsonl", "metadata": {"git_hash": "abc"}}))

    run_dir = mock_env_config / "runs" / run_id
    run_dir.mkdir()
    (run_dir / "run.jsonl").write_text("[]")

    args = MagicMock(run_id=run_id, hash="abc", verify_ledger=True)
    with patch(
        "eval_runner.verifier.TraceVerifier.verify_trace_async", new_callable=AsyncMock
    ) as mock_v:
        mock_v.return_value = True
        assert await evaluation.handle_gate(args) == 0


@pytest.mark.asyncio
async def test_handle_certify_success(mock_env_config):
    # evaluation.py 451-515
    run_id = "run_c"
    run_dir = mock_env_config / "runs" / run_id
    run_dir.mkdir()
    (run_dir / "run.jsonl").write_text("[]")

    args = MagicMock(run_id=run_id, identity="sys", status="pass", score=1.0, ttl=30)
    with patch("eval_runner.verifier.TraceVerifier.sign_trace") as mock_s:
        mock_s.return_value = {
            "run_id": run_id,
            "sha256": "123",
            "vc_version": "3",
            "governance_ttl": 30,
        }
        assert await evaluation.handle_certify(args) == 0


@pytest.mark.asyncio
async def test_aes_validate_success(tmp_path, capsys):
    # scenarios.py 49-107
    scenario_file = tmp_path / "test.aes.yaml"
    scenario_file.write_text("aes_version: 1.4")
    args = MagicMock(path=str(scenario_file), export=None)

    mock_validator = MagicMock()
    # Patch the validator_for call
    with (
        patch("eval_runner.handlers.scenarios.validator_for") as mock_val_for,
        patch(
            "eval_runner.handlers.scenarios.yaml.safe_load",
            return_value={
                "aes_version": 1.4,
                "metadata": {"name": "test", "id": "test_v", "compliance_level": "Standard"},
                "workflow": {"nodes": [], "edges": []},
                "evaluation": {"consensus": {"strategy": "Majority_Vote", "min_judges": 1}},
            },
        ),
    ):
        mock_val_for.return_value = MagicMock(return_value=mock_validator)
        assert await scenarios.handle_aes_validate(args) == 0
        assert "Valid (AES v1.4)" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_inspect_success(capsys):
    args = MagicMock(scenario_path="s1.json")
    with patch(
        "eval_runner.loader.load_scenario",
        return_value={"metadata": {"id": "s1"}, "industry": "fin", "description": "desc"},
    ):
        assert await scenarios.handle_inspect(args) == 0
        assert "SCENARIO INSPECTOR" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_lint_success():
    args = MagicMock(target=".")
    with patch("eval_runner.linter.run_lint") as mock_lint:
        assert await scenarios.handle_lint(args) == 0
        mock_lint.assert_called_once()


@pytest.mark.asyncio
async def test_list_and_catalog_search(capsys):
    with patch("eval_runner.catalog.ScenarioCatalog") as mock_cat_cls:
        mock_cat = mock_cat_cls.return_value
        mock_cat.search.return_value = [{"id": "res1", "title": "Title 1"}]

        args = MagicMock(refresh=True, search="query")
        with patch("eval_runner.catalog.list_scenarios"):
            assert await scenarios.handle_list(args) == 0

        args_search = MagicMock(query="q")
        assert await scenarios.handle_catalog_search(args_search) == 0
        assert "res1: Title 1" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_mutate_success(tmp_path):
    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps({"id": "orig"}))
    args = MagicMock(input=str(input_file), type="typos", output="mutated.json")

    with (
        patch("eval_runner.mutator.mutate_scenario", return_value={"id": "mut"}),
        patch("eval_runner.mutator.save_mutated_scenario") as mock_save,
    ):
        assert await scenarios.handle_mutate(args) == 0
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_spec_to_eval_success(tmp_path):
    input_file = tmp_path / "spec.md"
    input_file.write_text("# Spec")
    args = MagicMock(input=str(input_file), output="scenario.json")

    with (
        patch(
            "eval_runner.spec_parser.parse_markdown_to_scenario", new_callable=AsyncMock
        ) as mock_p,
        patch("eval_runner.spec_parser.save_scenario_json") as mock_s,
    ):
        mock_p.return_value = {"id": "spec"}
        assert await scenarios.handle_spec_to_eval(args) == 0
        mock_s.assert_called_once()


@pytest.mark.asyncio
async def test_import_drift_success(tmp_path):
    args = MagicMock(input="trace.jsonl", industry="fin", output_dir=str(tmp_path))
    with patch("eval_runner.drift_importer.import_trace_as_scenario") as mock_i:
        assert await scenarios.handle_import_drift(args) == 0
        mock_i.assert_called_once()


@pytest.mark.asyncio
async def test_catalog_refresh_success():
    args = MagicMock()
    with patch("eval_runner.catalog.ScenarioCatalog") as mock_cat_cls:
        assert await scenarios.handle_catalog_refresh(args) == 0
        mock_cat_cls.return_value.build_index.assert_called_once()


@pytest.mark.asyncio
async def test_classify_scenario_fallback(monkeypatch):
    # Force failure to cover line 46
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    res = scenarios.classify_scenario({"id": "test"})
    assert res["industry"] == "generic"
