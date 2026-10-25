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

    from eval_runner.identity import IdentityService
    from eval_runner.reference.local_run_store import LocalFileRunStore

    IdentityService._provision_local_identity("system_id")

    # Authoritative Eval Artifact
    store = LocalFileRunStore(log_dir=runs_dir)
    run_id = "test_gate_run"
    store.create_run(run_id=run_id, scenario_id="gate-scenario", metadata={"git_hash": "abc"})
    store.append_events(run_id, [{"event": "run_start", "run_id": run_id}])
    trace_bytes = store.get_trace_bytes(run_id)
    assert trace_bytes is not None

    # Generate Physical Manifest using real logic
    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        run_id=run_id,
        run_store=store,
        metadata={"git_hash": "abc"},
    )
    manifest_path = store.save_run_manifest(run_id, manifest)
    store.update_run_status(run_id, "SEALED")

    return {
        "root": root,
        "run_id": run_id,
        "store": store,
        "trace_path": str(runs_dir / run_id / "run.jsonl"),
        "manifest_path": str(manifest_path),
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

    # Schema validation of manifest used by gate
    import json
    from pathlib import Path

    from jsonschema import validate

    project_root = Path(__file__).parent.parent.parent.parent
    vc_schema_path = project_root / "spec" / "vc" / "vc.schema.json"
    assert vc_schema_path.exists()

    with open(vc_schema_path, encoding="utf-8") as sf:
        schema = json.load(sf)

    with open(gate_env["manifest_path"], encoding="utf-8") as mf:
        manifest_data = json.load(mf)

    validate(instance=manifest_data, schema=schema)


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

    IdentityService._provision_local_identity(identity_id)
    store = gate_env["store"]
    run_id_asym = "test_gate_asym_run"
    store.create_run(
        run_id=run_id_asym, scenario_id="gate-asym-scenario", metadata={"git_hash": "abc"}
    )
    store.append_events(run_id_asym, [{"event": "run_start", "run_id": run_id_asym}])
    trace_bytes_asym = store.get_trace_bytes(run_id_asym)
    assert trace_bytes_asym is not None

    manifest_asym = TraceVerifier.sign_trace_bytes(
        trace_bytes_asym,
        run_id=run_id_asym,
        run_store=store,
        identity_id=identity_id,
        metadata={"git_hash": "abc"},
    )
    store.save_run_manifest(run_id_asym, manifest_asym)
    store.update_run_status(run_id_asym, "SEALED")

    # 3. Handle gate with public key from IdentityService
    pub_key_path = trust_root / identity_id / "public_key.pem"
    args = Namespace(run_id=run_id_asym, vc=None, hash=None, public_key=str(pub_key_path))

    result = await evaluation.handle_gate(args)
    assert result == 0

    captured = capsys.readouterr()
    assert "[GATE] SUCCESS" in captured.out
