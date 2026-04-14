from argparse import Namespace

import pytest

from eval_runner.handlers import evaluation
from eval_runner.verifier import TraceVerifier


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

    trust_root = root / "trust"
    trust_root.mkdir()
    monkeypatch.setattr("eval_runner.config.TRUST_ROOT", trust_root)
    monkeypatch.setattr("eval_runner.config.ALLOW_SYSTEM_IDENTITY_PROVISIONING", True)

    # Authoritative Eval Artifact
    run_id = "test_gate_run"
    run_dir = runs_dir / run_id
    run_dir.mkdir()
    trace_path = run_dir / "run.jsonl"
    trace_path.write_text('{"event": "run_start"}\n')

    # Generate Physical Manifest using real logic
    TraceVerifier.sign_trace(str(trace_path), metadata={"git_hash": "abc"}, run_id=run_id)

    return {
        "root": root,
        "run_id": run_id,
        "trace_path": str(trace_path),
        "manifest_path": str(run_dir / "run_manifest.json"),
    }


@pytest.mark.asyncio
async def test_handle_gate_missing_vc(gate_env, capsys):
    """Test gate fails if manifest/VC is missing."""
    # Passing a run-id that doesn't have a manifest
    args = Namespace(run_id="missing_manifest", vc=None, hash=None, public_key=None)
    result = await evaluation.handle_gate(args)
    assert result == 1
    captured = capsys.readouterr()
    assert "[GATE] FAILURE: Manifest not found" in captured.out


@pytest.mark.asyncio
async def test_handle_gate_success(gate_env, capsys):
    """Test gate succeeds with valid manifest and trace."""
    args = Namespace(run_id=gate_env["run_id"], vc=None, hash=None, public_key=None)

    result = await evaluation.handle_gate(args)
    assert result == 0

    captured = capsys.readouterr()
    assert "[GATE] SUCCESS" in captured.out


@pytest.mark.asyncio
async def test_handle_gate_hash_mismatch(gate_env, capsys):
    """Test gate fails if commit hash mismatch."""
    args = Namespace(run_id=gate_env["run_id"], vc=None, hash="wrong_hash", public_key=None)

    result = await evaluation.handle_gate(args)
    assert result == 1
    captured = capsys.readouterr()
    assert "[GATE] FAILURE: Commit mismatch" in captured.out


@pytest.mark.asyncio
async def test_handle_gate_asymmetric_success(gate_env, capsys, monkeypatch):
    """Test gate succeeds with ED25519 signature via IdentityService."""
    from eval_runner import config
    from eval_runner.identity import IdentityService

    # 1. Setup physical trust root
    trust_root = gate_env["root"] / "trust"
    trust_root.mkdir(exist_ok=True)
    monkeypatch.setattr(config, "TRUST_ROOT", trust_root)

    identity_id = "test_tester"

    # 2. Provision identity and resign trace
    # IdentityService auto-provisions if private_key.pem is missing
    IdentityService.get_private_key(identity_id)
    TraceVerifier.sign_trace(
        gate_env["trace_path"], identity_id=identity_id, run_id=gate_env["run_id"]
    )

    # 3. Handle gate with public key from IdentityService
    pub_key_path = trust_root / identity_id / "public_key.pem"
    args = Namespace(run_id=gate_env["run_id"], vc=None, hash=None, public_key=str(pub_key_path))

    result = await evaluation.handle_gate(args)
    assert result == 0

    captured = capsys.readouterr()
    assert "[GATE] SUCCESS" in captured.out
