import pytest
from pathlib import Path
from unittest.mock import MagicMock
from eval_runner.handlers import evaluation

@pytest.fixture
def mock_args():
    args = MagicMock()
    args.path = "runs/valid.jsonl"
    args.vc = "reports/valid_vc.json"
    args.manifest = None
    args.private_key = None
    return args

@pytest.mark.asyncio
async def test_handle_certify_jail_enforcement(mock_args, capsys):
    """Verify handle_certify rejects paths outside project jail."""
    # Path traversal attempt
    mock_args.path = "../../outside.jsonl"
    with pytest.raises(SystemExit) as e:
        await evaluation.handle_certify(mock_args)
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Security Error" in captured.out
    assert "outside the project jail" in captured.out

@pytest.mark.asyncio
async def test_handle_verify_jail_enforcement(mock_args, capsys):
    """Verify handle_verify rejects paths outside project jail."""
    mock_args.path = "/absolute/system/path.jsonl"
    with pytest.raises(SystemExit) as e:
        await evaluation.handle_verify(mock_args)
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Security Error" in captured.out
    assert "outside the project jail" in captured.out

@pytest.mark.asyncio
async def test_handle_gate_jail_enforcement(mock_args):
    """Verify handle_gate exits with failure if VC is outside jail."""
    mock_args.vc = "../../traversal.json"
    with pytest.raises(SystemExit) as e:
        await evaluation.handle_gate(mock_args)
    assert e.value.code == 1

@pytest.mark.asyncio
async def test_handle_replay_jail_enforcement(mock_args, capsys):
    """Verify handle_replay rejects paths outside project jail."""
    mock_args.path = "../secrets.jsonl"
    with pytest.raises(SystemExit) as e:
        await evaluation.handle_replay(mock_args)
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Security Error" in captured.out
