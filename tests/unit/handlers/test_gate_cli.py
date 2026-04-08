import json
import pytest
import os
from pathlib import Path
from argparse import Namespace
from eval_runner.handlers import evaluation
from eval_runner.verifier import TraceVerifier
from eval_runner import config

@pytest.fixture
def gate_env(tmp_path, monkeypatch):
    """
    Creates a physical context for gating testing.
    Standardized for Zero-Mock verification.
    """
    root = tmp_path / "root"
    root.mkdir()
    
    # Configure industrial paths
    runs_dir = root / "runs"
    runs_dir.mkdir()
    reports_dir = root / "reports"
    reports_dir.mkdir()
    (reports_dir / "certificates").mkdir()
    
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", root)
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", runs_dir)
    monkeypatch.setattr("eval_runner.config.REPORTS_DIR", reports_dir)
    
    # Authoritative Eval Artifact
    run_id = "test_gate_run"
    run_dir = runs_dir / run_id
    run_dir.mkdir()
    trace_path = run_dir / "run.jsonl"
    trace_path.write_text('{"event": "run_start"}\n')
    
    # Generate Physical Manifest using real logic
    manifest = TraceVerifier.sign_trace(
        str(trace_path),
        metadata={"git_hash": "abc"}
    )
    
    return {
        "root": root,
        "run_id": run_id,
        "trace_path": str(trace_path),
        "manifest_path": str(run_dir / "run_manifest.json")
    }

@pytest.mark.asyncio
async def test_handle_gate_missing_vc(gate_env, capsys):
    """Test gate fails if manifest/VC is missing."""
    # Passing a run-id that doesn't have a manifest
    args = Namespace(run_id="missing_manifest", vc=None, hash=None, public_key=None)
    with pytest.raises(SystemExit) as e:
        await evaluation.handle_gate(args)
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "[GATE] FAILURE: Manifest not found" in captured.out

@pytest.mark.asyncio
async def test_handle_gate_success(gate_env, capsys):
    """Test gate succeeds with valid manifest and trace."""
    args = Namespace(run_id=gate_env["run_id"], vc=None, hash=None, public_key=None)

    with pytest.raises(SystemExit) as e:
        await evaluation.handle_gate(args)
    assert e.value.code == 0
        
    captured = capsys.readouterr()
    assert "[GATE] SUCCESS" in captured.out

@pytest.mark.asyncio
async def test_handle_gate_hash_mismatch(gate_env, capsys):
    """Test gate fails if commit hash mismatch."""
    args = Namespace(run_id=gate_env["run_id"], vc=None, hash="wrong_hash", public_key=None)

    with pytest.raises(SystemExit) as e:
        await evaluation.handle_gate(args)
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "[GATE] FAILURE: Commit mismatch" in captured.out

@pytest.mark.asyncio
async def test_handle_gate_asymmetric_success(gate_env, capsys):
    """Test gate succeeds with ED25519 signature."""
    # 1. Setup physical keys
    keys_dir = gate_env["root"] / "keys"
    TraceVerifier.generate_key_pair(str(keys_dir))
    priv_key = keys_dir / "private_key.pem"
    pub_key = keys_dir / "public_key.pem"
    
    # 2. Resign trace with real keys
    TraceVerifier.sign_trace(gate_env["trace_path"], private_key_path=str(priv_key))
    
    # 3. Handle gate with public key
    args = Namespace(run_id=gate_env["run_id"], vc=None, hash=None, public_key=str(pub_key))

    with pytest.raises(SystemExit) as e:
        await evaluation.handle_gate(args)
    assert e.value.code == 0
        
    captured = capsys.readouterr()
    assert "[GATE] SUCCESS" in captured.out
