import pytest
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from eval_runner.handlers import evaluation

@pytest.fixture
def mock_gate_args():
    args = MagicMock()
    args.vc = "manifest.json"
    args.hash = None
    args.public_key = None
    return args

def test_handle_gate_missing_vc(mock_gate_args, capsys):
    """Test gate fails if VC is missing."""
    mock_gate_args.vc = "non_existent.json"
    with pytest.raises(SystemExit) as e:
        evaluation.handle_gate(mock_gate_args)
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "[GATE] FAILURE: Verification Certificate not found" in captured.out

def test_handle_gate_success(mock_gate_args, tmp_path, capsys):
    """Test gate succeeds with valid manifest and trace."""
    trace = tmp_path / "run.jsonl"
    trace.write_text("{\"event\": \"run_start\"}")
    
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "trace_file": "run.jsonl",
        "sha256": "dummy_sig",
        "metadata": {"git_hash": "abc"}
    }))
    
    mock_gate_args.vc = str(manifest_path)
    
    with patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=True):
        with pytest.raises(SystemExit) as e:
            evaluation.handle_gate(mock_gate_args)
    
    assert e.value.code == 0
    captured = capsys.readouterr()
    assert "[GATE] SUCCESS" in captured.out

def test_handle_gate_hash_mismatch(mock_gate_args, tmp_path, capsys):
    """Test gate fails if commit hash mismatch."""
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "trace_file": "run.jsonl",
        "sha256": "dummy",
        "metadata": {"git_hash": "wrong"}
    }))
    (tmp_path / "run.jsonl").write_text("{}")
    
    mock_gate_args.vc = str(manifest_path)
    mock_gate_args.hash = "correct"
    
    with patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=True):
        with pytest.raises(SystemExit) as e:
            evaluation.handle_gate(mock_gate_args)
    
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "[GATE] FAILURE: Commit mismatch" in captured.out

def test_handle_gate_asymmetric_success(mock_gate_args, tmp_path, capsys):
    """Test gate succeeds with ED25519 signature."""
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({
        "trace_file": "run.jsonl",
        "sha256": "dummy",
        "signature": "valid_hex"
    }))
    (tmp_path / "run.jsonl").write_text("{}")
    (tmp_path / "pub.pem").write_text("public key content")
    
    mock_gate_args.vc = str(manifest_path)
    mock_gate_args.public_key = str(tmp_path / "pub.pem")
    
    with patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=True), \
         patch("eval_runner.verifier.TraceVerifier.verify_asymmetric", return_value=True):
        with pytest.raises(SystemExit) as e:
            evaluation.handle_gate(mock_gate_args)
    
    assert e.value.code == 0
    captured = capsys.readouterr()
    assert "[GATE] SUCCESS" in captured.out
