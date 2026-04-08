import pytest
from pathlib import Path
from argparse import Namespace
from eval_runner.handlers import evaluation
from eval_runner import config

@pytest.fixture
def certify_env(tmp_path, monkeypatch):
    """
    Creates a physical context for certification testing.
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
    run_id = "test_certification_run"
    run_dir = runs_dir / run_id
    run_dir.mkdir()
    trace_path = run_dir / "run.jsonl"
    trace_path.write_text('{"event": "run_start"}\n')
    
    return {
        "root": root,
        "run_id": run_id,
        "trace_path": trace_path
    }

@pytest.mark.asyncio
async def test_handle_certify_missing_trace(certify_env, capsys):
    """Test certify fails if trace file is missing."""
    # Passing a run-id that doesn't exist
    args = Namespace(run_id="non_existent", path=None, metadata=None, private_key=None)
    with pytest.raises(SystemExit) as e:
        await evaluation.handle_certify(args)
    assert e.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Trace file not found" in captured.out

@pytest.mark.asyncio
async def test_handle_certify_success(certify_env, capsys):
    """Test certify succeeds and creates a physical manifest."""
    # Use the established run-id
    args = Namespace(run_id=certify_env["run_id"], path=None, metadata=None, private_key=None)
    
    with pytest.raises(SystemExit) as e:
        await evaluation.handle_certify(args)
    assert e.value.code == 0
        
    captured = capsys.readouterr()
    assert "Success: Verification Certificate generated" in captured.out
    assert f"Run ID: {certify_env['run_id']}" in captured.out
    
    # Physical State Verification
    sidecar = certify_env["trace_path"].parent / "run_manifest.json"
    vault = config.REPORTS_DIR / "certificates" / f"{certify_env['run_id']}_vc.json"
    
    assert sidecar.exists(), "Sidecar manifest missing"
    assert vault.exists(), "Vault certificate missing"
