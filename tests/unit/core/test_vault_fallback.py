from unittest.mock import patch

import pytest

from eval_runner import cli


def test_replay_vault_priority(tmp_path, monkeypatch, capsys):
    """
    Tier 1: Vault Resolution (Primary).
    Verify that the system prioritizes the nested industrial vault.
    """
    monkeypatch.chdir(tmp_path)
    run_id = "vault-run"

    # Setup Vault
    vault_dir = tmp_path / run_id
    vault_dir.mkdir()
    trace_file = vault_dir / "run.jsonl"
    trace_file.write_text(
        '{"event": "run_start", "run_id": "vault-run", "scenario": "test"}\n', encoding="utf-8"
    )

    with (
        patch("eval_runner.config.RUN_LOG_DIR", tmp_path),
        patch("sys.argv", ["agentv", "replay", "--run-id", run_id]),
        patch("eval_runner.plugins.manager.load_plugins"),
    ):
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 0

        captured = capsys.readouterr().out
        assert f"Reconstructing from Run ID: {run_id}" in captured
        assert "Vault directory not found" not in captured


def test_replay_master_fallback(tmp_path, monkeypatch, capsys):
    """
    Tier 2: Master Log Fallback (Recoverable).
    Verify fallback to root run.jsonl with mandatory ❌ [ERROR] notification.
    """
    monkeypatch.chdir(tmp_path)
    run_id = "fallback-run"

    # Setup Master Log (No Vault)
    master_log = tmp_path / "run.jsonl"
    master_log.write_text(
        '{"event": "run_start", "run_id": "fallback-run", "scenario": "master-test"}\n'
        '{"event": "prompt", "role": "user", "content": "hello", "run_id": "fallback-run"}\n',
        encoding="utf-8",
    )

    with (
        patch("eval_runner.config.RUN_LOG_DIR", tmp_path),
        patch("sys.argv", ["agentv", "replay", "--run-id", run_id]),
        patch("eval_runner.plugins.manager.load_plugins"),
    ):
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 0

        out, err = capsys.readouterr()
        # Verify Fallback Notification
        assert f"Vault directory not found for Run ID '{run_id}'" in out
        assert "Falling back to master log" in out
        assert "❌ [ERROR]" in out

        # Verify Content Recovery
        assert "--- Run Started: fallback-run" in out
        assert "[USER]: hello" in out


def test_replay_invalid_run_id(tmp_path, monkeypatch, capsys):
    """
    Tier 3: Unrecoverable (Invalid Run ID).
    Verify specific error message when ID is missing from both layers.
    """
    monkeypatch.chdir(tmp_path)
    run_id = "ghost-run"

    # Setup empty master log
    master_log = tmp_path / "run.jsonl"
    master_log.write_text('{"event": "run_start", "run_id": "other-run"}\n', encoding="utf-8")

    with (
        patch("eval_runner.config.RUN_LOG_DIR", tmp_path),
        patch("sys.argv", ["agentv", "replay", "--run-id", run_id]),
        patch("eval_runner.plugins.manager.load_plugins"),
    ):
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 1

        out, _ = capsys.readouterr()
        assert f"Run ID '{run_id}' not found in master log fallback" in out
