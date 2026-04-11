from argparse import Namespace

import pytest

from eval_runner.handlers import evaluation
from eval_runner.handlers.evaluation import handle_certify, handle_verify


@pytest.fixture
def physical_jail(tmp_path):
    """
    Creates a physical project jail for security testing.
    Standardized for Zero-Mock verification.
    """
    root = tmp_path / "root"
    root.mkdir()

    # Create the authoritative vault structure
    runs_dir = root / "runs"
    runs_dir.mkdir()

    # Authoritative Eval Artifact
    eval_id = "target_run"
    eval_dir = runs_dir / eval_id
    eval_dir.mkdir()
    (eval_dir / "run.jsonl").write_text('{"event": "run_start"}\n')

    # Return context
    return {
        "root": root,
        "runs_dir": runs_dir,
        "eval_id": eval_id,
        "eval_path": str(eval_dir / "run.jsonl"),
    }


@pytest.mark.asyncio
async def test_handle_certify_jail_enforcement(physical_jail, capsys, monkeypatch):
    """Verify handle_certify rejects paths outside project jail."""
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", physical_jail["root"])
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", physical_jail["runs_dir"])
    # [INDUSTRIAL HARDENING] Force strict jail to block temp-zone escapes during tests
    monkeypatch.setenv("AEH_STRICT_JAIL", "1")

    # Attempt traversal via Run ID
    args = Namespace(run_id="../../secrets", path=None, metadata=None, private_key=None)
    with pytest.raises(SystemExit) as e:
        await handle_certify(args)
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Security Error" in captured.out


@pytest.mark.asyncio
async def test_handle_verify_jail_enforcement(physical_jail, capsys, monkeypatch):
    """Verify handle_verify rejects paths outside project jail."""
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", physical_jail["root"])
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", physical_jail["runs_dir"])
    monkeypatch.setenv("AEH_STRICT_JAIL", "1")

    # Attempt traversal via Run ID
    args = Namespace(run_id="../../secrets", path=None, manifest=None)
    with pytest.raises(SystemExit) as e:
        await handle_verify(args)
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Security Error" in captured.out


@pytest.mark.asyncio
async def test_handle_gate_jail_enforcement(physical_jail, monkeypatch):
    """Verify handle_gate exits with failure if VC is outside jail."""
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", physical_jail["root"])
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", physical_jail["runs_dir"])
    monkeypatch.setattr("eval_runner.config.REPORTS_DIR", physical_jail["root"] / "reports")
    monkeypatch.setenv("AEH_STRICT_JAIL", "1")

    # In handle_gate, run_id is used for vault path resolution
    args = Namespace(run_id="../../traversal", vc=None, hash=None, public_key=None)
    with pytest.raises(SystemExit) as e:
        await evaluation.handle_gate(args)
    assert e.value.code == 1


@pytest.mark.asyncio
async def test_handle_replay_jail_enforcement(physical_jail, capsys, monkeypatch):
    """Verify handle_replay rejects paths outside project jail."""
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", physical_jail["root"])
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", physical_jail["runs_dir"])
    monkeypatch.setenv("AEH_STRICT_JAIL", "1")

    args = Namespace(run_id="../../secrets", path=None, agent=None)
    with pytest.raises(SystemExit) as e:
        await evaluation.handle_replay(args)
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Security Error" in captured.out
