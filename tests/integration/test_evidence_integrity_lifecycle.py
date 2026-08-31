"""
Integration tests for evidence integrity lifecycle:

  - transactional certification: freeze -> hash -> sign -> persist -> verify
    -> seal -> publish, with CERTIFICATION_FAILED on any stage failure (P0 #11)
  - full evidence-chain verification by default; trace_only opt-in (P0 #12)
  - append-only immutable run manifests (P0 #13)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import eval_runner.config as harness_config
from eval_runner.identity import IdentityService
from eval_runner.reference.local_run_store import (
    LocalFileRunStore,
    RunManifestImmutableError,
)
from eval_runner.verifier import CertificationFailedError, TraceVerifier


@pytest.fixture()
def cert_env(tmp_path, monkeypatch):
    log_dir = tmp_path / "runs"
    reports = tmp_path / "reports"
    trust_root = tmp_path / ".aes" / "keys"
    for d in (log_dir, reports, trust_root):
        d.mkdir(parents=True)

    monkeypatch.setattr(harness_config, "RUN_LOG_DIR", log_dir)
    monkeypatch.setattr(harness_config, "REPORTS_DIR", reports)
    monkeypatch.setattr(harness_config, "TRUST_ROOT", trust_root)
    # Provision a deterministic local signing identity for the certification pipeline
    IdentityService._provision_local_identity("system_id")

    run_id = "cert-run-001"
    vault = log_dir / run_id
    vault.mkdir(parents=True)
    trace = vault / "run.jsonl"
    with open(trace, "w", encoding="utf-8") as f:
        f.write(json.dumps({"event": "run_start", "scenario": "s"}) + "\n")
        f.write(json.dumps({"event": "run_end", "status": "success"}) + "\n")
    # A sidecar evidence artifact so the ledger is non-trivial
    sidecar = vault / "scenario_original.json"
    sidecar.write_text(json.dumps({"id": "cert-scenario"}), encoding="utf-8")

    return {
        "run_id": run_id,
        "vault": vault,
        "trace": trace,
        "sidecar": sidecar,
        "reports": reports,
    }


def _original_size(path: Path) -> int:
    return path.stat().st_size


# ---------------------------------------------------------------------------
# P0 #11: atomic certification
# ---------------------------------------------------------------------------


def test_sign_trace_happy_path_is_fully_certified(cert_env):
    env = cert_env
    manifest = TraceVerifier.sign_trace(
        str(env["trace"]), run_id=env["run_id"], identity_id="system_id"
    )

    assert manifest["certification"]["outcome"] == "CERTIFIED"
    assert all(s["status"] == "ok" for s in manifest["certification"]["stages"])
    expected_stages = [s["stage"] for s in manifest["certification"]["stages"]]
    assert expected_stages == [
        "freeze",
        "freeze_seal_hash",
        "canonicalize",
        "hash",
        "sign",
        "persist",
        "verify",
        "seal",
        "publish",
    ]

    # Sidecar manifest persisted and certificate backup published
    assert (env["vault"] / "run_manifest.json").exists()
    assert (env["reports"] / "certificates" / f"{env['run_id']}_vc.json").exists()

    # Lifecycle event appended exactly once
    lines = [ln for ln in env["trace"].read_text(encoding="utf-8").splitlines() if ln]
    assert json.loads(lines[-1])["event"] == "verification_certificate_issued"

    # Vault is sealed
    assert (env["vault"] / ".sealed").exists()


def test_sign_failure_rolls_back_and_never_returns_certificate(cert_env, monkeypatch):
    import eval_runner.verifier as verifier_module

    env = cert_env

    def _exploding_sign(manifest, format):
        raise RuntimeError("HSM unreachable")

    monkeypatch.setattr(verifier_module.verification_service, "sign", _exploding_sign)

    with pytest.raises(CertificationFailedError) as excinfo:
        TraceVerifier.sign_trace(str(env["trace"]), run_id=env["run_id"], identity_id="system_id")

    assert excinfo.value.outcome == "CERTIFICATION_FAILED"
    failed_stages = [s for s in excinfo.value.stage_log if s["status"] == "failed"]
    assert any(s["stage"] == "sign" for s in failed_stages)

    # No certificate issued on signing failure
    lines = [ln for ln in env["trace"].read_text(encoding="utf-8").splitlines() if ln]
    assert not any("verification_certificate_issued" in ln for ln in lines)

    # No partial artifacts published anywhere
    assert not (env["vault"] / "run_manifest.json").exists()
    assert not (env["reports"] / "certificates" / f"{env['run_id']}_vc.json").exists()
    assert not (env["vault"] / ".sealed").exists()


def test_seal_failure_rolls_back_and_raises(cert_env):
    from eval_runner.interfaces.artifact import ArtifactStore

    class _SealFailsStore(ArtifactStore):
        def store_artifact(self, run_id, artifact_name, content, **kwargs):
            return f"mock://{run_id}/{artifact_name}"

        def get_artifact(self, run_id, artifact_name):
            return None

        def exists(self, run_id, artifact_name):
            return False

        def list_artifacts(self, run_id):
            return []

        def seal(self, run_id, metadata=None):
            raise OSError("object-lock unavailable")

        def is_sealed(self, run_id):
            return False

    env = cert_env

    with pytest.raises(CertificationFailedError) as excinfo:
        TraceVerifier.sign_trace(
            str(env["trace"]),
            run_id=env["run_id"],
            identity_id="system_id",
            artifact_store=_SealFailsStore(),
        )

    assert any(s["stage"] == "seal" and s["status"] == "failed" for s in excinfo.value.stage_log)
    # No certificate may survive an incomplete sealing operation.
    assert not (env["reports"] / "certificates" / f"{env['run_id']}_vc.json").exists()
    assert not (env["vault"] / ".sealed").exists()


# ---------------------------------------------------------------------------
# P0 #12: full evidence-chain verification by default
# ---------------------------------------------------------------------------


def test_verify_defaults_to_full_ledger_and_detects_tampering(cert_env):
    env = cert_env
    manifest_path = env["vault"] / "run_manifest.json"

    TraceVerifier.sign_trace(str(env["trace"]), run_id=env["run_id"], identity_id="system_id")
    assert TraceVerifier.verify_trace(str(env["trace"]), str(manifest_path)) is True

    # Tamper with a referenced evidence artifact
    env["sidecar"].write_text(json.dumps({"id": "TAMPERED"}), encoding="utf-8")

    assert TraceVerifier.verify_trace(str(env["trace"]), str(manifest_path)) is False
    # Explicit partial verification still validates only the trace itself
    assert (
        TraceVerifier.verify_trace(str(env["trace"]), str(manifest_path), trace_only=True) is True
    )


def test_verify_run_directory_uses_full_chain(cert_env):
    env = cert_env
    TraceVerifier.sign_trace(str(env["trace"]), run_id=env["run_id"], identity_id="system_id")
    result = TraceVerifier.verify_run_directory(env["vault"])
    assert result["is_valid"] is True

    env["sidecar"].write_text("tampered", encoding="utf-8")
    result = TraceVerifier.verify_run_directory(env["vault"])
    assert result["is_valid"] is False


# ---------------------------------------------------------------------------
# P0 #13: append-only run store
# ---------------------------------------------------------------------------


def test_run_store_first_publication_wins_and_divergence_appends(tmp_path):
    store = LocalFileRunStore(log_dir=tmp_path / "runs")
    p1 = store.save_run_manifest("r1", {"v": 1})
    p2 = store.save_run_manifest("r1", {"v": 2})  # divergent republish

    authoritative = Path(p1)
    assert json.loads(authoritative.read_text(encoding="utf-8")) == {"v": 1}

    revision_path = Path(p2)
    assert "manifest_revisions" in str(revision_path)
    assert revision_path.exists()

    revisions = store.list_manifest_revisions("r1")
    assert len(revisions) == 1

    info = store.get_run("r1")
    assert info["manifest"] == {"v": 1}


def test_run_store_identical_republish_is_idempotent(tmp_path):
    store = LocalFileRunStore(log_dir=tmp_path / "runs")
    manifest = {"run_id": "r2", "pass_at_k": 1.0}
    p1 = store.save_run_manifest("r2", manifest)
    p2 = store.save_run_manifest("r2", dict(manifest))
    assert p1 == p2
    assert store.list_manifest_revisions("r2") == []


def test_sealed_run_refuses_overwrite(tmp_path):
    store = LocalFileRunStore(log_dir=tmp_path / "runs")
    store.save_run_manifest("r3", {"v": 1})
    vault = tmp_path / "runs" / "r3"
    (vault / ".sealed").write_text("{}", encoding="utf-8")

    with pytest.raises(RunManifestImmutableError):
        store.save_run_manifest("r3", {"v": 999})

    # Original publication untouched
    assert json.loads((vault / "run_manifest.json").read_text(encoding="utf-8")) == {"v": 1}


def test_sealed_run_refuses_deletion(tmp_path):
    store = LocalFileRunStore(log_dir=tmp_path / "runs")
    store.save_run_manifest("r4", {"v": 1})
    vault = tmp_path / "runs" / "r4"
    (vault / ".sealed").write_text("{}", encoding="utf-8")

    with pytest.raises(RunManifestImmutableError):
        store.delete_run("r4")
