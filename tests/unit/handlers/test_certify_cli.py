import json
from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest
from eval_runner.handlers import evaluation

@pytest.fixture
def mock_certify_args():
    args = MagicMock()
    args.path = "run.jsonl"
    args.private_key = None
    return args

@pytest.mark.asyncio
async def test_handle_certify_missing_trace(mock_certify_args, capsys):
    """Test certify fails if trace file is missing."""
    mock_certify_args.path = "non_existent.jsonl"
    await evaluation.handle_certify(mock_certify_args)
    captured = capsys.readouterr()
    assert "Error: Trace file not found" in captured.out

@pytest.mark.asyncio
async def test_handle_certify_success(mock_certify_args, tmp_path, capsys):
    """Test certify succeeds and creates a manifest."""
    trace_path = tmp_path / "run.jsonl"
    trace_path.write_text('{"event": "run_start"}\n')
    mock_certify_args.path = str(trace_path)
    
    mock_manifest = {
        "run_id": "test_id",
        "sha256": "dummy_hash",
        "signature_ed25519": None
    }
    
    with patch("eval_runner.verifier.TraceVerifier.sign_trace", return_value=mock_manifest) as mock_sign:
        await evaluation.handle_certify(mock_certify_args)
        mock_sign.assert_called_once_with(str(trace_path), private_key_path=None)
        
    captured = capsys.readouterr()
    assert "Success: Verification Certificate generated" in captured.out
    assert "Run ID: test_id" in captured.out
    assert "SHA-256: dummy_hash" in captured.out
