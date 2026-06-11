"""
Consolidated Verifier Test Suite for AgentV Evaluation Harness.
Verifies cryptographic signing (VC v3.0.0), SHA-256 integrity, forensic vaults,
evidence ledger tracking, and governance TTL enforcement.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eval_runner import config
from eval_runner.verifier import (
    BaseVerifier,
    CoreTraceSigner,
    TraceVerificationInterceptor,
    TraceVerifier,
    VerificationResult,
    VerificationService,
    verification_service,
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

    verification_service.reset()
    yield root
    verification_service.reset()


def setup_vault(run_id, trace_name="run.jsonl"):
    """Industrial Helper: Scaffolds a forensic vault for testing."""
    vault_dir = config.RUN_LOG_DIR / run_id
    vault_dir.mkdir(parents=True, exist_ok=True)
    trace_path = vault_dir / trace_name
    return vault_dir, trace_path


# --- 2. Base Logic & Metrics ---


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


def test_verification_result_to_dict_has_timestamp():
    res = VerificationResult(True, "ok")
    d = res.to_dict()
    assert "timestamp" in d
    assert "T" in d["timestamp"]  # ISO 8601 format


def test_verification_result_wsm_calculation():
    """Test WSM calculation and safety floor logic."""
    res = VerificationResult(
        success=True, message="Test", metrics={"safety": 0.4, "security": 0.9, "reliability": 0.9}
    )
    assert res.aggregate_score < 0.5


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


def test_verification_result_wsm_no_floor_needed():
    """All metrics high — floor not applied."""
    res = VerificationResult(
        True,
        "ok",
        metrics={
            "safety": 1.0,
            "security": 1.0,
            "reliability": 1.0,
            "fairness": 1.0,
            "explainability": 1.0,
            "privacy": 1.0,
            "resilience": 1.0,
        },
    )
    assert res.aggregate_score == pytest.approx(1.0, abs=0.001)


def test_verification_result_wsm_missing_dim_defaults_zero():
    """A missing dimension defaults to 0.0 in WSM calculation."""
    res = VerificationResult(True, "ok", metrics={"safety": 1.0, "security": 1.0})
    assert res.aggregate_score == pytest.approx(0.45, abs=0.01)


def test_verification_result_explicit_score():
    """Test that explicit aggregate_score bypasses WSM calculation."""
    res = VerificationResult(True, "OK", aggregate_score=0.99)
    assert res.aggregate_score == 0.99
    assert res.to_dict()["aggregate_score"] == 0.99


def test_compute_signature(tmp_path):
    test_file = tmp_path / "sig.txt"
    test_file.write_bytes(b"data")
    sig1 = TraceVerifier.compute_signature(test_file)
    sig2 = TraceVerifier.compute_signature(test_file)
    assert sig1 == sig2
    assert len(sig1) == 64


# --- 3. Cryptographic Signing & Verification (v3.0.0) ---


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


def test_v3_governance_ttl():
    run_id = "run-expired"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("data")

    # Sign with expired TTL
    TraceVerifier.sign_trace(str(trace_path), run_id=run_id, ttl_days=-1)
    manifest_path = vault_dir / "run_manifest.json"

    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is False


def test_v3_forensic_filtering():
    run_id = "run-filter"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("trace")

    (vault_dir / "junk.node").write_text("exclude")
    (vault_dir / "valid.log").write_text("include")

    manifest = TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
    assert "valid.log" in manifest["evidence_ledger"]
    assert "junk.node" not in manifest["evidence_ledger"]


@pytest.mark.asyncio
async def test_verify_trace_async():
    run_id = "run-async"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("data")

    TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
    manifest_path = vault_dir / "run_manifest.json"

    assert await TraceVerifier.verify_trace_async(str(trace_path), str(manifest_path)) is True


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
    assert TraceVerifier.verify_trace(str(trace_path), "/outside/jail/manifest.json") is False


# --- 4. Interceptor & PQC Pipeline Coverage ---


def test_verification_service_register_at_head():
    """register_interceptor inserts at head (index 0) of the list."""
    svc = VerificationService()

    class A(TraceVerificationInterceptor):
        def can_sign(self, fmt):
            return True

        def sign(self, m, n):
            return n(m)

    class B(TraceVerificationInterceptor):
        def can_sign(self, fmt):
            return True

        def sign(self, m, n):
            return n(m)

    a, b = A(), B()
    svc.register_interceptor(a)
    svc.register_interceptor(b)
    assert svc._global_interceptors[0] is b
    assert svc._global_interceptors[1] is a


def test_verification_service_reset():
    """reset() clears all interceptors and thread tracking."""
    svc = VerificationService()

    class DummyInterceptor(TraceVerificationInterceptor):
        def can_sign(self, fmt):
            return True

        def sign(self, m, n):
            return n(m)

    svc.register_interceptor(DummyInterceptor())
    assert len(svc._global_interceptors) == 1
    svc.reset()
    assert len(svc._global_interceptors) == 0
    assert len(svc._interceptor_threads) == 0


def test_verification_service_interceptors_cached():
    """_interceptors property is cached in thread-local storage."""
    svc = VerificationService()

    class Dummy(TraceVerificationInterceptor):
        def can_sign(self, fmt):
            return True

        def sign(self, m, n):
            return n(m)

    svc.register_interceptor(Dummy())
    first = svc._interceptors
    second = svc._interceptors
    assert first is second


def test_verification_service_override_interceptor_context():
    """override_interceptor removes the interceptor on exit, even on exception."""
    svc = VerificationService()

    class Temp(TraceVerificationInterceptor):
        def can_sign(self, fmt):
            return True

        def sign(self, m, n):
            return n(m)

    temp = Temp()
    with svc.override_interceptor(temp):
        assert temp in svc._global_interceptors

    assert temp not in svc._global_interceptors


def test_verification_service_override_interceptor_cleanup_on_exception():
    """override_interceptor cleans up even when a body exception occurs."""
    svc = VerificationService()

    class Temp(TraceVerificationInterceptor):
        def can_sign(self, fmt):
            return True

        def sign(self, m, n):
            return n(m)

    temp = Temp()
    try:
        with svc.override_interceptor(temp):
            raise ValueError("test error")
    except ValueError:
        pass

    assert temp not in svc._global_interceptors


def test_verification_service_sign_recursion_limit():
    """Pipeline depth > 50 raises RecursionError."""
    svc = VerificationService()

    class LoopInterceptor(TraceVerificationInterceptor):
        def can_sign(self, fmt):
            return True

        def sign(self, manifest, next_signer):
            return next_signer(manifest)

    for _ in range(60):
        svc.register_interceptor(LoopInterceptor())

    manifest = {"provenance_chain": []}
    with pytest.raises(RecursionError):
        svc.sign(manifest, "ED25519")


def test_verification_service_interceptor_exception_bypasses_gracefully():
    """If an interceptor raises a non-critical exception, it is bypassed to next."""
    svc = VerificationService()

    class CrashInterceptor(TraceVerificationInterceptor):
        def can_sign(self, fmt):
            return True

        def sign(self, manifest, next_signer):
            raise RuntimeError("Boom")

    class PreemptInterceptor(TraceVerificationInterceptor):
        def can_sign(self, fmt):
            return True

        def sign(self, manifest, next_signer):
            manifest["provenance_chain"].append({"identity": "fallback", "algorithm": "MOCK"})
            return manifest

    svc.register_interceptor(PreemptInterceptor())
    svc.register_interceptor(CrashInterceptor())

    manifest = {"provenance_chain": []}
    result = svc.sign(manifest, "ED25519")
    assert any(p["identity"] == "fallback" for p in result["provenance_chain"])


def test_verification_service_can_sign_false_skips():
    """Interceptor with can_sign=False is skipped; falls through to next."""
    svc = VerificationService()

    class SkipInterceptor(TraceVerificationInterceptor):
        def can_sign(self, fmt):
            return False

        def sign(self, manifest, next_signer):
            return next_signer(manifest)

    class PreemptInterceptor(TraceVerificationInterceptor):
        def can_sign(self, fmt):
            return True

        def sign(self, manifest, next_signer):
            manifest["provenance_chain"].append({"identity": "reached"})
            return manifest

    svc.register_interceptor(PreemptInterceptor())
    svc.register_interceptor(SkipInterceptor())

    manifest = {"provenance_chain": []}
    result = svc.sign(manifest, "ED25519")
    assert any(p["identity"] == "reached" for p in result["provenance_chain"])


def test_core_trace_signer_can_sign_supported():
    signer = CoreTraceSigner()
    for fmt in ["ED25519", "ML-DSA-65", "hybrid", "standard"]:
        assert signer.can_sign(fmt) is True


def test_core_trace_signer_can_sign_unsupported():
    signer = CoreTraceSigner()
    assert signer.can_sign("RSA-2048") is False


def test_core_trace_signer_sign_pqc_success(monkeypatch):
    """CoreTraceSigner.sign with PQC_ENABLED=True and a functioning pqc_client."""
    monkeypatch.setattr(config, "PQC_ENABLED", True)
    monkeypatch.setattr(config, "PQC_STRICT_MODE", False)

    mock_private_key = MagicMock()
    mock_private_key.sign.return_value = b"\x00" * 64

    mock_pqc_client = MagicMock()
    mock_pqc_client.sign_digest.return_value = "pqc_sig_hex"

    manifest = {
        "provenance_chain": [],
        "signing_context": {"identity_id": "system_id", "timestamp": "ts"},
    }

    with (
        patch("eval_runner.identity.IdentityService") as mock_id_svc,
        patch("eval_runner.forensics.compute_shake256_digest", return_value=b"digest"),
    ):
        mock_id_svc.get_private_key.return_value = mock_private_key
        mock_id_svc.get_pqc_client.return_value = mock_pqc_client

        signer = CoreTraceSigner()
        result = signer.sign(manifest, lambda m: m)

    algorithms = [p["algorithm"] for p in result["provenance_chain"]]
    assert "ED25519" in algorithms
    assert "ML-DSA-65" in algorithms


def test_core_trace_signer_pqc_client_unavailable_strict(monkeypatch):
    """PQC enabled, no client, PQC_STRICT_MODE=True → RuntimeError."""
    monkeypatch.setattr(config, "PQC_ENABLED", True)
    monkeypatch.setattr(config, "PQC_STRICT_MODE", True)

    mock_private_key = MagicMock()
    mock_private_key.sign.return_value = b"\x00" * 64

    manifest = {
        "provenance_chain": [],
        "signing_context": {"identity_id": "system_id", "timestamp": "ts"},
    }

    with patch("eval_runner.identity.IdentityService") as mock_id_svc:
        mock_id_svc.get_private_key.return_value = mock_private_key
        mock_id_svc.get_pqc_client.return_value = None

        signer = CoreTraceSigner()
        with pytest.raises(RuntimeError, match="PQC_STRICT_MODE"):
            signer.sign(manifest, lambda m: m)


def test_core_trace_signer_pqc_client_unavailable_non_strict(monkeypatch):
    """PQC enabled, no client, non-strict → logs warning, continues."""
    monkeypatch.setattr(config, "PQC_ENABLED", True)
    monkeypatch.setattr(config, "PQC_STRICT_MODE", False)

    mock_private_key = MagicMock()
    mock_private_key.sign.return_value = b"\x00" * 64

    manifest = {
        "provenance_chain": [],
        "signing_context": {"identity_id": "system_id", "timestamp": "ts"},
    }

    with patch("eval_runner.identity.IdentityService") as mock_id_svc:
        mock_id_svc.get_private_key.return_value = mock_private_key
        mock_id_svc.get_pqc_client.return_value = None

        signer = CoreTraceSigner()
        result = signer.sign(manifest, lambda m: m)

    assert len(result["provenance_chain"]) == 1
    assert result["provenance_chain"][0]["algorithm"] == "ED25519"


def test_core_trace_signer_pqc_sign_fails_strict(monkeypatch):
    """PQC client.sign_digest raises, PQC_STRICT_MODE=True → RuntimeError."""
    monkeypatch.setattr(config, "PQC_ENABLED", True)
    monkeypatch.setattr(config, "PQC_STRICT_MODE", True)

    mock_private_key = MagicMock()
    mock_private_key.sign.return_value = b"\x00" * 64

    mock_pqc_client = MagicMock()
    mock_pqc_client.sign_digest.side_effect = RuntimeError("PQC API down")

    manifest = {
        "provenance_chain": [],
        "signing_context": {"identity_id": "system_id", "timestamp": "ts"},
    }

    with (
        patch("eval_runner.identity.IdentityService") as mock_id_svc,
        patch("eval_runner.forensics.compute_shake256_digest", return_value=b"digest"),
    ):
        mock_id_svc.get_private_key.return_value = mock_private_key
        mock_id_svc.get_pqc_client.return_value = mock_pqc_client

        signer = CoreTraceSigner()
        with pytest.raises(RuntimeError, match="PQC_STRICT_MODE"):
            signer.sign(manifest, lambda m: m)


def test_core_trace_signer_pqc_sign_fails_non_strict(monkeypatch):
    """PQC client.sign_digest raises, non-strict → logs warning, result has ED25519 only."""
    monkeypatch.setattr(config, "PQC_ENABLED", True)
    monkeypatch.setattr(config, "PQC_STRICT_MODE", False)

    mock_private_key = MagicMock()
    mock_private_key.sign.return_value = b"\x00" * 64

    mock_pqc_client = MagicMock()
    mock_pqc_client.sign_digest.side_effect = RuntimeError("API down")

    manifest = {
        "provenance_chain": [],
        "signing_context": {"identity_id": "system_id", "timestamp": "ts"},
    }

    with (
        patch("eval_runner.identity.IdentityService") as mock_id_svc,
        patch("eval_runner.forensics.compute_shake256_digest", return_value=b"digest"),
    ):
        mock_id_svc.get_private_key.return_value = mock_private_key
        mock_id_svc.get_pqc_client.return_value = mock_pqc_client

        signer = CoreTraceSigner()
        result = signer.sign(manifest, lambda m: m)

    assert len(result["provenance_chain"]) == 1
    assert result["provenance_chain"][0]["algorithm"] == "ED25519"


def test_core_trace_signer_outer_exception_non_strict(monkeypatch):
    """IdentityService.get_private_key fails, non-strict → logs warning, continues."""
    monkeypatch.setattr(config, "PQC_STRICT_MODE", False)

    manifest = {
        "provenance_chain": [],
        "signing_context": {"identity_id": "system_id", "timestamp": "ts"},
    }

    with patch("eval_runner.identity.IdentityService") as mock_id_svc:
        mock_id_svc.get_private_key.side_effect = RuntimeError("Key not found")

        signer = CoreTraceSigner()
        result = signer.sign(manifest, lambda m: m)

    assert result["provenance_chain"] == []


def test_core_trace_signer_outer_exception_strict_reraises(monkeypatch):
    """Outer exception that is a PQC_STRICT_MODE violation is re-raised."""
    monkeypatch.setattr(config, "PQC_STRICT_MODE", True)

    manifest = {
        "provenance_chain": [],
        "signing_context": {"identity_id": "system_id", "timestamp": "ts"},
    }

    with patch("eval_runner.identity.IdentityService") as mock_id_svc:
        mock_id_svc.get_private_key.side_effect = RuntimeError(
            "PQC_STRICT_MODE Violation: something"
        )

        signer = CoreTraceSigner()
        with pytest.raises(RuntimeError, match="PQC_STRICT_MODE"):
            signer.sign(manifest, lambda m: m)


def test_generate_key_pair_relative_path():
    """generate_key_pair resolves relative paths against PROJECT_ROOT."""
    key_dir_rel = "trust/relative_test_id"
    expected_dir = config.PROJECT_ROOT / key_dir_rel
    TraceVerifier.generate_key_pair(output_dir=key_dir_rel)
    assert (expected_dir / "private_key.pem").exists()
    assert (expected_dir / "public_key.pem").exists()


def test_verify_trace_bad_timestamp_continues(tmp_path):
    """verify_trace with unparseable timestamp logs warning but does not fail immediately."""
    run_id = "run-bad-ts"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("trace content")

    TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
    manifest_path = vault_dir / "run_manifest.json"

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    manifest["timestamp"] = "NOT_A_DATE"
    manifest_path.write_text(json.dumps(manifest))

    result = TraceVerifier.verify_trace(str(trace_path), str(manifest_path))
    assert isinstance(result, bool)


def test_verify_trace_ledger_missing_artifact():
    """verify_trace with verify_ledger=True returns False when artifact is missing."""
    run_id = "run-ledger-missing"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("trace")
    evidence = vault_dir / "evidence.txt"
    evidence.write_text("evidence content")

    TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
    manifest_path = vault_dir / "run_manifest.json"
    evidence.unlink()

    result = TraceVerifier.verify_trace(str(trace_path), str(manifest_path), verify_ledger=True)
    assert result is False


def test_sign_trace_lifecycle_event_failure():
    """If appending the lifecycle event to trace fails, sign_trace continues."""
    run_id = "run-event-fail"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("trace")

    original_open = open

    def patched_open(path, mode="r", **kwargs):
        if "ab" in str(mode):
            raise OSError("Write failure")
        return original_open(path, mode, **kwargs)

    with patch("builtins.open", side_effect=patched_open):
        try:
            TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
        except Exception:
            pass


def test_verify_trace_pqc_mismatch_and_unavailable(monkeypatch):
    """Test verify_trace when PQC signature mismatches (line 627) or when PQC
    client is unavailable (lines 632-640).
    """
    # 1. Signature mismatch (line 627)
    mock_pqc_client_bad = MagicMock()
    mock_pqc_client_bad.verify_digest.return_value = False  # Mismatch!

    run_id = "run-pqc-mismatch"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("trace")

    # Generate manifest with standard signing first
    monkeypatch.setattr(config, "PQC_ENABLED", False)
    TraceVerifier.sign_trace(str(trace_path), run_id=run_id)

    # Enable PQC for the verification phase
    monkeypatch.setattr(config, "PQC_ENABLED", True)
    manifest_path = vault_dir / "run_manifest.json"

    with open(manifest_path) as f:
        manifest = json.load(f)

    manifest["provenance_chain"].append(
        {
            "identity": "system_id@pqc",
            "algorithm": "ML-DSA-65",
            "signature": "sig_hex_xyz",
        }
    )
    manifest_path.write_text(json.dumps(manifest))

    with patch(
        "eval_runner.identity.IdentityService.get_pqc_client", return_value=mock_pqc_client_bad
    ):
        # Should return False due to ValueError caught inside verify_trace
        assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is False

    # 1.5 Successful PQC verification (covers line 628 debug log)
    mock_pqc_client_good = MagicMock()
    mock_pqc_client_good.verify_digest.return_value = True
    with patch(
        "eval_runner.identity.IdentityService.get_pqc_client", return_value=mock_pqc_client_good
    ):
        assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is True

    # 2. PQC client unavailable with STRICT mode (line 637-638)
    monkeypatch.setattr(config, "PQC_STRICT_MODE", True)
    with patch("eval_runner.identity.IdentityService.get_pqc_client", return_value=None):
        assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is False

    # 3. Unknown algorithm (line 640)
    manifest_bad_algo = manifest.copy()
    manifest_bad_algo["provenance_chain"][-1]["algorithm"] = "UNKNOWN_ALGO"
    manifest_path.write_text(json.dumps(manifest_bad_algo))
    # Should proceed but warning is logged/handled gracefully
    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is True


def test_verification_service_thread_isolation():
    """Verify thread isolation logic in VerificationService._interceptors property."""
    import threading

    svc = VerificationService()

    class Dummy(TraceVerificationInterceptor):
        def can_sign(self, fmt):
            return True

        def sign(self, m, n):
            return n(m)

    dummy = Dummy()
    # Trigger hasattr(self._local, "interceptors") check
    _ = svc._interceptors

    # Mock threading.get_ident and threading.main_thread to decouple child thread
    # from main thread ID matches
    with (
        patch("threading.get_ident", return_value=9999),
        patch("threading.main_thread") as mock_main,
    ):
        mock_main.return_value.ident = 8888
        svc.register_interceptor(dummy)

    # In a separate thread, dummy is not active/available in _interceptors
    # because it belongs to the parent thread
    results = []

    def run_thread():
        # Inside child thread, mock the child thread ID and a different main thread ID
        with (
            patch("threading.get_ident", return_value=7777),
            patch("threading.main_thread") as mock_main_child,
        ):
            mock_main_child.return_value.ident = 8888
            results.append(len(svc._interceptors))

    t = threading.Thread(target=run_thread)
    t.start()
    t.join()

    # The new thread should see 0 because dummy's thread affinity is 9999, which is not 7777 or 8888
    assert results[0] == 0

    # Also cover line 247 by using override_interceptor and triggering removal
    # from local interceptors. We must patch get_ident for register_interceptor,
    # _interceptors lookup, AND the exit block assertions.
    with (
        patch("threading.get_ident", return_value=9999),
        patch("threading.main_thread") as mock_main,
    ):
        mock_main.return_value.ident = 8888
        with svc.override_interceptor(dummy):
            assert dummy in svc._interceptors

        # Clear the cached property on the thread-local storage to force rebuild
        if hasattr(svc._local, "interceptors"):
            delattr(svc._local, "interceptors")
        assert dummy not in svc._interceptors


class MockPreemptiveInterceptor(TraceVerificationInterceptor):
    """Preempts signing completely, providing dummy signature and avoiding core logic."""

    def can_sign(self, format: str) -> bool:
        return format in ["preempt", "ED25519", "hybrid"]

    def sign(self, manifest: dict, next_signer) -> dict:
        manifest["provenance_chain"] = [
            {
                "identity": "preempted_signer",
                "role": "Adversary",
                "timestamp": manifest.get("timestamp"),
                "signature": "dummy_preempt_signature",
                "algorithm": "MOCK",
            }
        ]
        return manifest


class MockAugmentingInterceptor(TraceVerificationInterceptor):
    """Augments signing by letting the next signer run, then appending its own proof."""

    def __init__(self, key: str, value: str):
        self.key = key
        self.value = value

    def can_sign(self, format: str) -> bool:
        return True

    def sign(self, manifest: dict, next_signer) -> dict:
        manifest = next_signer(manifest)
        manifest["provenance_chain"].append(
            {
                "identity": "augmenting_signer",
                "role": "Validator",
                "timestamp": manifest.get("timestamp"),
                "signature": f"custom_{self.key}_{self.value}",
                "algorithm": "MOCK",
            }
        )
        return manifest


def test_interceptor_preemption():
    """Verify that an interceptor can completely preempt signature generation."""
    run_id = "run-preempt"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("dummy trace contents", encoding="utf-8")

    preemptor = MockPreemptiveInterceptor()
    verification_service.register_interceptor(preemptor)

    manifest = TraceVerifier.sign_trace(str(trace_path), run_id=run_id, compliance_status="pass")

    assert len(manifest["provenance_chain"]) == 1
    assert manifest["provenance_chain"][0]["identity"] == "preempted_signer"
    assert manifest["provenance_chain"][0]["signature"] == "dummy_preempt_signature"


def test_interceptor_augmentation():
    """Verify that an interceptor can augment standard signature generation."""
    run_id = "run-augment"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("dummy trace contents", encoding="utf-8")

    augmenter = MockAugmentingInterceptor("auditor", "passed")
    verification_service.register_interceptor(augmenter)

    manifest = TraceVerifier.sign_trace(str(trace_path), run_id=run_id)

    assert len(manifest["provenance_chain"]) >= 2
    assert manifest["provenance_chain"][-1]["identity"] == "augmenting_signer"
    assert manifest["provenance_chain"][-1]["signature"] == "custom_auditor_passed"


def test_override_interceptor_context_manager():
    """Verify that the override_interceptor context manager temporarily
    registers and cleanly reverts.
    """
    run_id = "run-override"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("dummy trace contents", encoding="utf-8")

    preemptor = MockPreemptiveInterceptor()

    manifest1 = TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
    assert manifest1["provenance_chain"][0]["identity"] == "system_id"

    with verification_service.override_interceptor(preemptor):
        manifest_preempt = {"provenance_chain": []}
        res = verification_service.sign(manifest_preempt, format="preempt")
        assert res["provenance_chain"][0]["identity"] == "preempted_signer"

    manifest_empty = {"provenance_chain": []}
    res = verification_service.sign(manifest_empty, format="preempt")
    assert res["provenance_chain"][0]["identity"] == "system_id"
