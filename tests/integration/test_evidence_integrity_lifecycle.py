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

    store = LocalFileRunStore(log_dir=log_dir)
    run_id = "cert-run-001"
    store.create_run(run_id=run_id, scenario_id="cert-scenario")
    events = [
        {"event": "run_start", "scenario": "s"},
        {"event": "run_end", "status": "success"},
    ]
    store.append_events(run_id, events)
    trace_bytes = store.get_trace_bytes(run_id)
    assert trace_bytes is not None

    vault = log_dir / run_id
    sidecar = vault / "scenario_original.json"
    sidecar.write_text(json.dumps({"id": "cert-scenario"}), encoding="utf-8")

    return {
        "run_id": run_id,
        "store": store,
        "vault": vault,
        "trace_bytes": trace_bytes,
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
    manifest = TraceVerifier.sign_trace_bytes(
        env["trace_bytes"],
        run_id=env["run_id"],
        run_store=env["store"],
        identity_id="system_id",
    )

    assert manifest["certification"]["outcome"] == "PROVISIONAL_PASS"
    assert manifest["vc_version"] == "3.0.0"
    assert manifest.get("trace_hash")

    # Publish to provider and verify sealed state
    env["store"].save_run_manifest(env["run_id"], manifest)
    env["store"].update_run_status(env["run_id"], "SEALED")

    published = env["store"].get_manifest(env["run_id"])
    assert published is not None
    assert (env["vault"] / ".sealed").exists()


def test_sign_failure_rolls_back_and_never_returns_certificate(cert_env, monkeypatch):
    import eval_runner.verifier as verifier_module

    env = cert_env

    def _exploding_sign(manifest, format):
        raise RuntimeError("HSM unreachable")

    monkeypatch.setattr(verifier_module.verification_service, "sign", _exploding_sign)

    with pytest.raises(RuntimeError, match="HSM unreachable"):
        TraceVerifier.sign_trace_bytes(
            env["trace_bytes"],
            run_id=env["run_id"],
            run_store=env["store"],
            identity_id="system_id",
        )

    # No certificate manifest published to provider
    manifest = env["store"].get_manifest(env["run_id"]) or {}
    assert "signature" not in manifest and "trace_hash" not in manifest
    assert not (env["vault"] / "run_manifest.json").exists()
    assert not (env["vault"] / ".sealed").exists()


def test_seal_failure_unsealed_run_fails_strict_verification(cert_env):
    env = cert_env
    manifest = TraceVerifier.sign_trace_bytes(
        env["trace_bytes"],
        run_id=env["run_id"],
        run_store=env["store"],
        identity_id="system_id",
    )
    env["store"].save_run_manifest(env["run_id"], manifest)

    # If the run is unsealed, strict trace_only=False verification fails
    assert not TraceVerifier.verify_trace(
        env["trace_bytes"],
        manifest,
        run_store=env["store"],
        trace_only=False,
    )


def test_provider_trace_ownership_mismatch_is_rejected_before_signing(cert_env):
    env = cert_env
    other_store = LocalFileRunStore(log_dir=env["reports"] / "other_runs")
    other_store.create_run(run_id=env["run_id"], scenario_id="other-scenario")
    other_store.append_events(env["run_id"], [{"event": "different_event"}])

    # Attempting to sign trace bytes that diverge from provider's owned
    # trace bytes raises CertificationFailedError
    with pytest.raises(CertificationFailedError, match="ProviderTraceOwnershipMismatch"):
        TraceVerifier.sign_trace_bytes(
            env["trace_bytes"],
            run_id=env["run_id"],
            run_store=other_store,
            identity_id="system_id",
        )


# ---------------------------------------------------------------------------
# P0 #12: full evidence-chain verification by default
# ---------------------------------------------------------------------------


def test_verify_defaults_to_full_ledger_and_detects_tampering(cert_env):
    env = cert_env
    manifest = TraceVerifier.sign_trace_bytes(
        env["trace_bytes"],
        run_id=env["run_id"],
        run_store=env["store"],
        identity_id="system_id",
    )
    env["store"].save_run_manifest(env["run_id"], manifest)
    env["store"].update_run_status(env["run_id"], "SEALED")

    assert (
        TraceVerifier.verify_trace(
            env["trace_bytes"],
            manifest,
            run_store=env["store"],
            trace_only=False,
        )
        is True
    )

    # Tamper with trace bytes
    tampered_bytes = env["trace_bytes"] + b"\n"
    assert (
        TraceVerifier.verify_trace(
            tampered_bytes,
            manifest,
            run_store=env["store"],
            trace_only=False,
        )
        is False
    )


def test_verify_run_uses_full_chain(cert_env):
    env = cert_env
    scenario_data = {"id": "cert-scenario"}
    manifest = TraceVerifier.sign_trace_bytes(
        env["trace_bytes"],
        run_id=env["run_id"],
        run_store=env["store"],
        scenario_data=scenario_data,
        identity_id="system_id",
    )
    env["store"].save_run_manifest(env["run_id"], manifest)
    env["store"].update_run_status(env["run_id"], "SEALED")

    result = TraceVerifier.verify_run(env["run_id"], run_store=env["store"])
    assert result["is_valid"] is True
    assert result["has_certificate"] is True
    assert result["verification_status"] == "VERIFIED_PROVISIONAL"


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
