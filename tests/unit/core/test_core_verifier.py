"""
Consolidated Verifier Test Suite for AgentV Evaluation Harness.
Verifies cryptographic signing (VC v3.0.0), SHA-256 integrity, forensic vaults,
evidence ledger tracking, and governance TTL enforcement.
"""

import json
from pathlib import Path

import pytest

from eval_runner import config
from eval_runner.verifier import (
    BaseVerifier,
    TraceVerifier,
    VerificationResult,
)

# --- 1. Fixtures & Scaffolding ---


@pytest.fixture(autouse=True)
def vault_context(tmp_path, monkeypatch):
    """Setup a controlled test environment with isolated trust and run vaults."""
    root = tmp_path / "root"
    root.mkdir()
    runs_dir = root / "runs"
    runs_dir.mkdir()
    reports_dir = root / "reports"
    reports_dir.mkdir()
    trust_dir = root / "trust"
    trust_dir.mkdir()

    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)
    monkeypatch.setattr(config, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(config, "TRUST_ROOT", trust_dir)

    # Provision system_id keypair for signing
    identity_dir = trust_dir / "system_id"
    identity_dir.mkdir(parents=True, exist_ok=True)
    TraceVerifier.generate_key_pair(output_dir=str(identity_dir))

    return root


def setup_vault(run_id, trace_name="run.jsonl"):
    """Industrial Helper: Scaffolds a forensic vault for testing."""
    vault_dir = config.RUN_LOG_DIR / run_id
    vault_dir.mkdir(parents=True, exist_ok=True)
    trace_path = vault_dir / trace_name
    return vault_dir, trace_path


# --- 2. Base Logic & Metrics ---


def test_verification_result_wsm_calculation():
    """Test WSM calculation and safety floor logic."""
    res = VerificationResult(
        success=True, message="Test", metrics={"safety": 0.4, "security": 0.9, "reliability": 0.9}
    )
    # Safety < 0.5 should cap or influence score significantly
    assert res.aggregate_score < 0.5


def test_compute_signature(tmp_path):
    test_file = tmp_path / "sig.txt"
    test_file.write_bytes(b"data")
    sig1 = TraceVerifier.compute_signature(test_file)
    sig2 = TraceVerifier.compute_signature(test_file)
    assert sig1 == sig2
    assert len(sig1) == 64


# --- 3. Cryptographic Signing (v3.0.0) ---


def test_v3_signing_cycle():
    run_id = "run-v3-e2e"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("trace content")

    # Add evidence
    (vault_dir / "evidence.txt").write_text("forensic data")

    manifest = TraceVerifier.sign_trace(str(trace_path), run_id=run_id, identity_id="system_id")

    assert manifest["vc_version"] == "3.0.0"
    assert "evidence.txt" in manifest["evidence_ledger"]

    manifest_path = vault_dir / "run_manifest.json"
    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is True


# --- 4. Tamper Detection & Security ---


def test_verifier_tamper_detection():
    run_id = "run-tamper"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("original")

    TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
    manifest_path = vault_dir / "run_manifest.json"

    trace_path.write_text("TAMPERED")
    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is False


def test_verifier_security_jail_violation(tmp_path):
    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}")
    assert TraceVerifier.verify_trace(str(outside), "any") is False


# --- 5. Governance & TTL ---


def test_v3_governance_ttl():
    run_id = "run-expired"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("data")

    # Sign with expired TTL
    TraceVerifier.sign_trace(str(trace_path), run_id=run_id, ttl_days=-1)
    manifest_path = vault_dir / "run_manifest.json"

    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is False


# --- 6. Forensic Filtering ---


def test_v3_forensic_filtering():
    run_id = "run-filter"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("trace")

    (vault_dir / "junk.node").write_text("exclude")
    (vault_dir / "valid.log").write_text("include")

    manifest = TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
    assert "valid.log" in manifest["evidence_ledger"]
    assert "junk.node" not in manifest["evidence_ledger"]


# --- 7. Async Wrapper ---


@pytest.mark.asyncio
async def test_verify_trace_async():
    run_id = "run-async"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("data")

    TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
    manifest_path = vault_dir / "run_manifest.json"

    assert await TraceVerifier.verify_trace_async(str(trace_path), str(manifest_path)) is True


# === Ported edge-case coverage ===


class ConcreteVerifier(BaseVerifier):
    """Minimal concrete verifier to test abstract base class pass branch."""

    def verify(self, trace_path, **kwargs):
        super().verify(trace_path, **kwargs)
        return VerificationResult(True, "OK")


def test_base_verifier_abstract_pass():
    """Hits the pass statement in BaseVerifier.verify."""
    verifier = ConcreteVerifier()
    res = verifier.verify(Path("fake.jsonl"))
    assert res.success is True


def test_verification_result_wsm_normal():
    """Test normal WSM calculation."""
    res = VerificationResult(
        success=True, message="Test", metrics={"safety": 0.8, "security": 0.8, "reliability": 0.8}
    )
    assert res.aggregate_score == pytest.approx(0.52, abs=0.01)


def test_verification_result_wsm_safety_floor():
    """Test that low safety score caps aggregate below 0.5."""
    res = VerificationResult(
        success=True, message="Fail", metrics={"safety": 0.4, "security": 0.9, "reliability": 0.9}
    )
    assert res.aggregate_score < 0.5


def test_verification_result_wsm_security_floor():
    """Test that low security score caps aggregate to 0.49."""
    res = VerificationResult(
        success=True, message="Fail", metrics={"safety": 0.9, "security": 0.4, "reliability": 1.0}
    )
    assert res.aggregate_score == pytest.approx(0.49, abs=0.01)


def test_verification_result_explicit_score():
    """Test that explicit aggregate_score bypasses WSM calculation."""
    res = VerificationResult(True, "OK", aggregate_score=0.99)
    assert res.aggregate_score == 0.99
    assert res.to_dict()["aggregate_score"] == 0.99


def test_sign_trace_security_violations():
    """Test sign_trace path jail and identity validation."""
    with pytest.raises(PermissionError, match="Security violation"):
        TraceVerifier.sign_trace("/outside/the/jail.jsonl", run_id="none")

    vault_dir = config.RUN_LOG_DIR / "run_id_foo"
    vault_dir.mkdir(exist_ok=True)
    trace_path = vault_dir / "run.jsonl"
    trace_path.write_text("{}")

    with pytest.raises(ValueError, match="Identity Basis Failure"):
        TraceVerifier.sign_trace(str(trace_path), run_id=None)

    with pytest.raises(ValueError, match="Forensic Pollution"):
        TraceVerifier.sign_trace(str(trace_path), run_id="wrong_id")


def test_verify_trace_legacy_rejection():
    """Verify that VC version < 3.0.0 is explicitly rejected."""

    run_dir = config.RUN_LOG_DIR / "legacy_run"
    run_dir.mkdir(exist_ok=True)
    trace_path = run_dir / "trace.jsonl"
    trace_path.write_text("{}")
    legacy_manifest = {
        "vc_version": "1.0.0",
        "sha256": TraceVerifier.compute_signature(trace_path),
        "run_id": "legacy",
    }
    manifest_path = run_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(legacy_manifest))
    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is False


def test_verify_trace_missing_provenance(caplog):
    """Verify that empty provenance chain fails verification."""

    run_dir = config.RUN_LOG_DIR / "no_prov_run"
    run_dir.mkdir(exist_ok=True)
    trace_path = run_dir / "run.jsonl"
    trace_path.write_text("{}")
    manifest = {
        "vc_version": "3.0.0",
        "sha256": TraceVerifier.compute_signature(trace_path),
        "timestamp": "2026-04-15T12:00:00.000+0000",
        "provenance_chain": [],
        "evidence_ledger": {},
    }
    manifest_path = run_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is False
    assert "No provenance chain found" in caplog.text


def test_v3_forensic_tier1_always_included():
    """Verify forensics/ directory files bypass size and extension filters."""
    run_id = "run-tier1-ported"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("trace")
    forensics_dir = vault_dir / "forensics"
    forensics_dir.mkdir()
    (forensics_dir / "suspect.exe").write_text("malicious content")
    manifest = TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
    assert "forensics/suspect.exe" in manifest["evidence_ledger"]


def test_v3_forensic_extension_filtering():
    """Verify only allowed enterprise extensions are collected."""
    run_id = "run-ext-ported"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("trace")
    (vault_dir / "data.parquet").write_text("parquet data")
    (vault_dir / "config.yaml").write_text("yaml content")
    (vault_dir / "legacy.doc").write_text("doc")
    manifest = TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
    assert "data.parquet" in manifest["evidence_ledger"]
    assert "config.yaml" in manifest["evidence_ledger"]
    assert "legacy.doc" not in manifest["evidence_ledger"]


def test_v3_forensic_alias_normalization():
    """Verify .jpeg/.text/.logger aliases are included via extension normalization."""
    run_id = "run-alias-ported"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("trace")
    (vault_dir / "image.jpeg").write_text("jpeg data")
    (vault_dir / "notes.text").write_text("text data")
    manifest = TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
    assert "image.jpeg" in manifest["evidence_ledger"]
    assert "notes.text" in manifest["evidence_ledger"]


def test_sign_payload_with_key():
    """Test TraceVerifier.sign_payload with a real generated key."""
    run_id = "run-sign-payload"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("{}")
    # Generate key pair in the trust dir
    key_dir = config.TRUST_ROOT / "sign_test_id"
    key_dir.mkdir(parents=True, exist_ok=True)
    TraceVerifier.generate_key_pair(output_dir=str(key_dir))
    priv_key = key_dir / "private_key.pem"
    payload = b"hello world"
    signature = TraceVerifier.sign_payload(payload, priv_key)
    assert isinstance(signature, str)
    assert len(signature) > 0


def test_verify_ledger_tampered_artifact():
    """Verify that a tampered sidecar file in the evidence ledger fails verification."""
    run_id = "run-ledger-tamper"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("trace")
    evidence = vault_dir / "evidence.txt"
    evidence.write_text("raw evidence")
    TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
    manifest_path = vault_dir / "run_manifest.json"
    # Tamper with evidence after signing
    evidence.write_text("tampered evidence")
    assert (
        TraceVerifier.verify_trace(str(trace_path), str(manifest_path), verify_ledger=True) is False
    )


def test_get_certificate_api_helper():
    """Test get_certificate API wrapper returns the manifest dict."""
    run_id = "run-cert-helper"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("{}}")
    cert = TraceVerifier.get_certificate(str(trace_path), run_id=run_id)
    assert cert["run_id"] == run_id
    assert "sha256" in cert


def test_verify_trace_manifest_outside_jail():
    """Verify that a manifest path outside the project jail returns False."""
    run_id = "run-manifest-jail"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("{}")
    # manifest path points outside the jail
    assert TraceVerifier.verify_trace(str(trace_path), "/outside/jail/manifest.json") is False
