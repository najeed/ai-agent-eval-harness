import pytest

from eval_runner import config
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.verifier import TraceVerifier


def test_key_generation(tmp_path):
    """Test generating ED25519 key pair via TraceVerifier utility."""
    key_dir = tmp_path / "keys"
    TraceVerifier.generate_key_pair(str(key_dir))

    assert (key_dir / "private_key.pem").exists()
    assert (key_dir / "public_key.pem").exists()

    # Check if they are PEM formatted
    priv_content = (key_dir / "private_key.pem").read_text()
    pub_content = (key_dir / "public_key.pem").read_text()

    assert "-----BEGIN PRIVATE KEY-----" in priv_content
    assert "-----BEGIN PUBLIC KEY-----" in pub_content


def test_trace_verification_cycle(tmp_path, monkeypatch):
    """
    Test the full VC v3.0.0 cycle: compute hash, sign, and verify.
    This replaces the legacy test_asymmetric_sign_verify.
    """
    # 1. Setup - Create a mock trace in a run directory
    run_id = "test-run-v3"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    trace_path = run_dir / "run.jsonl"
    trace_content = b'{"event":"test"}'
    trace_path.write_bytes(trace_content)

    # 2. Setup Identities
    identity_id = "tester_id"
    keys_dir = tmp_path / "keys" / identity_id
    TraceVerifier.generate_key_pair(str(keys_dir))

    # Configure TRUST_ROOT and PROJECT_ROOT for testing
    monkeypatch.setattr(config, "TRUST_ROOT", tmp_path / "keys")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    run_store = LocalFileRunStore(tmp_path / "runs")
    run_store.create_run(run_id, "asymmetric-verifier")

    # 3. Sign Trace
    trace_bytes = trace_path.read_bytes()
    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes, identity_id=identity_id, run_id=run_id, run_store=run_store
    )
    run_store.save_run_manifest(run_id, manifest)
    run_store.update_run_status(run_id, "SEALED")

    assert manifest["vc_version"] == "3.0.0"
    assert manifest["run_id"] == run_id
    assert len(manifest["provenance_chain"]) == 1
    assert manifest["provenance_chain"][0]["identity"] == identity_id

    # 4. Success Verification
    assert (
        TraceVerifier.verify_trace(trace_bytes, manifest, run_store=run_store, trace_only=True)
        is True
    )

    # 5. Tamper Verification (Data mismatch)
    tampered_bytes = b"TAMPERED"
    assert (
        TraceVerifier.verify_trace(tampered_bytes, manifest, run_store=run_store, trace_only=True)
        is False
    )

    # 6. Corruption Verification (Manifest mismatch)
    bad_manifest = dict(manifest)
    bad_manifest["trace_hash"] = "wrong-hash"
    assert (
        TraceVerifier.verify_trace(trace_bytes, bad_manifest, run_store=run_store, trace_only=True)
        is False
    )


def test_verification_service_pipeline_depth_and_override(tmp_path):
    from eval_runner.verifier import (
        CertificationFailedError,
        TraceVerificationInterceptor,
        VerificationService,
    )

    svc = VerificationService()

    class CyclicInterceptor(TraceVerificationInterceptor):
        def can_sign(self, format: str) -> bool:
            return True

        def sign(self, manifest: dict, next_signer) -> dict:
            return next_signer(manifest)

    # Register interceptor with override_interceptor context manager
    with svc.override_interceptor(CyclicInterceptor()):
        assert len(svc._interceptors) > 0

    # Mandatory interceptor failure
    class FailingMandatoryInterceptor(TraceVerificationInterceptor):
        is_mandatory = True

        def can_sign(self, format: str) -> bool:
            return True

        def sign(self, manifest: dict, next_signer) -> dict:
            raise RuntimeError("Mandatory signer failed")

    with svc.override_interceptor(FailingMandatoryInterceptor()):
        with pytest.raises(CertificationFailedError):
            svc.sign({"test": "manifest"}, "default")
