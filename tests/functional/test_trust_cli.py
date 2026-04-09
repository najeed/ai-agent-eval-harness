import json
import subprocess
import pytest
from pathlib import Path
from eval_runner import config

@pytest.fixture
def cli_env(tmp_path, isolated_trust):
    """Setup a mock environment for CLI testing."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    
    trace_path = runs_dir / "run-test-01.jsonl"
    trace_path.write_text("{\"event\":\"start\"}\n{\"event\":\"end\"}")
    
    return {
        "runs_dir": runs_dir,
        "trace_path": trace_path
    }

@pytest.fixture
def isolated_trust(tmp_path):
    original_root = config.TRUST_ROOT
    config.TRUST_ROOT = tmp_path / "trust"
    yield config.TRUST_ROOT
    config.TRUST_ROOT = original_root

def test_cli_certify_success(cli_env):
    """Verify certify command with v3 flags."""
    trace_path = cli_env["trace_path"]
    
    cmd = [
        "python", "-m", "eval_runner.cli", "certify",
        "--path", str(trace_path),
        "--status", "pass",
        "--score", "0.95",
        "--identity", "ci_bot",
        "--policy-ref", "CI-P-01"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0
    assert "Success" in result.stdout
    
    # Verify manifest existence
    manifest_path = trace_path.parent / f"{trace_path.stem}_manifest.json"
    assert manifest_path.exists()
    
    with open(manifest_path) as f:
        manifest = json.load(f)
        assert manifest["compliance"]["status"] == "pass"
        assert manifest["compliance"]["policy_ref"] == "CI-P-01"

def test_cli_gate_success(cli_env):
    """Verify gate command with ledger verification."""
    trace_path = cli_env["trace_path"]
    
    # 1. Certify first
    subprocess.run([
        "python", "-m", "eval_runner.cli", "certify",
        "--path", str(trace_path),
        "--identity", "ci_bot"
    ], check=True)
    
    manifest_path = trace_path.parent / f"{trace_path.stem}_manifest.json"
    
    # 2. Gate
    cmd = [
        "python", "-m", "eval_runner.cli", "gate",
        "--vc", str(manifest_path),
        "--verify-ledger"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0
    assert "SUCCESS" in result.stdout

def test_cli_gate_failure_tampered(cli_env):
    """Verify gate command rejects tampered files."""
    trace_path = cli_env["trace_path"]
    
    # 1. Certify
    subprocess.run([
        "python", "-m", "eval_runner.cli", "certify",
        "--path", str(trace_path),
        "--identity", "ci_bot"
    ], check=True)
    
    manifest_path = trace_path.parent / f"{trace_path.stem}_manifest.json"
    
    # 2. Tamper trace
    trace_path.write_text("TAMPERED")
    
    # 3. Gate
    cmd = [
        "python", "-m", "eval_runner.cli", "gate",
        "--vc", str(manifest_path)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode != 0
    assert "FAILURE" in result.stdout
