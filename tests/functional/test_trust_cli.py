import json
import os
import subprocess

import pytest

from eval_runner import config


@pytest.fixture
def cli_env(tmp_path, isolated_trust, monkeypatch):
    """Setup a mock environment for CLI testing with standard run directory structure."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    run_id = "test-run-001"
    run_vault = runs_dir / run_id
    run_vault.mkdir()

    trace_path = run_vault / "run.jsonl"
    trace_path.write_text('{"event":"start"}\n{"event":"end"}')

    # We must patch config and env for the subprocess to pick them up
    # In a real environment, we'd use environment variables
    # For now, we'll rely on the subprocess using the current working directory or environment
    return {"runs_dir": runs_dir, "run_id": run_id, "trace_path": trace_path, "tmp_path": tmp_path}


@pytest.fixture
def isolated_trust(tmp_path, monkeypatch):
    """Isolate the Identity Registry for testing."""
    trust_root = tmp_path / "trust"
    trust_root.mkdir()
    monkeypatch.setattr(config, "TRUST_ROOT", trust_root)
    # Also set env var so subprocess sees it
    monkeypatch.setenv("TRUST_ROOT", str(trust_root))
    return trust_root


def test_cli_certify_success(cli_env, monkeypatch):
    """Verify certify command with mandatory --run-id."""
    run_id = cli_env["run_id"]
    trace_path = cli_env["trace_path"]

    # Set RUN_LOG_DIR for the subprocess
    monkeypatch.setenv("RUN_LOG_DIR", str(cli_env["runs_dir"]))
    monkeypatch.setenv("REPORTS_DIR", str(cli_env["tmp_path"] / "reports"))

    cmd = [
        "python",
        "-m",
        "eval_runner.cli",
        "certify",
        "--run-id",
        run_id,
        "--status",
        "pass",
        "--score",
        "0.95",
        "--identity",
        "ci_bot",
        "--policy-ref",
        "CI-P-01",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0
    assert f"Certified: {run_id}" in result.stdout or "Success" in result.stdout

    # Verify manifest existence (Autonomous discovery)
    manifest_path = trace_path.parent / "run_manifest.json"
    assert manifest_path.exists()

    with open(manifest_path) as f:
        manifest = json.load(f)
        assert manifest["compliance"]["status"] == "pass"
        assert manifest["compliance"]["policy_ref"] == "CI-P-01"
        assert manifest["run_id"] == run_id


def test_cli_gate_success(cli_env, monkeypatch):
    """Verify gate command with Run ID centric discovery."""
    run_id = cli_env["run_id"]

    monkeypatch.setenv("RUN_LOG_DIR", str(cli_env["runs_dir"]))
    monkeypatch.setenv("TRUST_ROOT", str(config.TRUST_ROOT))
    monkeypatch.setenv("REPORTS_DIR", str(cli_env["tmp_path"] / "reports"))

    # 1. Certify first
    subprocess.run(
        ["python", "-m", "eval_runner.cli", "certify", "--run-id", run_id, "--identity", "ci_bot"],
        env=dict(os.environ, **{"RUN_LOG_DIR": str(cli_env["runs_dir"])}),
        check=True,
    )

    # 2. Gate using Run ID
    cmd = ["python", "-m", "eval_runner.cli", "gate", "--run-id", run_id, "--verify-ledger"]

    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0
    assert "SUCCESS" in result.stdout


def test_cli_gate_failure_tampered(cli_env, monkeypatch):
    """Verify gate command rejects tampered files via Run ID discovery."""
    run_id = cli_env["run_id"]
    trace_path = cli_env["trace_path"]

    monkeypatch.setenv("RUN_LOG_DIR", str(cli_env["runs_dir"]))
    monkeypatch.setenv("REPORTS_DIR", str(cli_env["tmp_path"] / "reports"))

    # 1. Certify
    subprocess.run(
        ["python", "-m", "eval_runner.cli", "certify", "--run-id", run_id, "--identity", "ci_bot"],
        check=True,
    )

    # 2. Tamper trace
    trace_path.write_text("TAMPERED")

    # 3. Gate
    cmd = ["python", "-m", "eval_runner.cli", "gate", "--run-id", run_id]

    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode != 0
    assert "FAILURE" in result.stdout
