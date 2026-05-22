"""
Unit tests for the Cryptographic Trace Signing Interceptor Pipeline.
Verifies registration, preemption, augmentation, reset, and context manager overrides.
"""

import pytest

from eval_runner import config
from eval_runner.verifier import (
    TraceVerificationInterceptor,
    TraceVerifier,
    verification_service,
)


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
        # Run standard signing first
        manifest = next_signer(manifest)
        # Augment with custom metadata
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


@pytest.fixture(autouse=True)
def setup_isolation(tmp_path, monkeypatch):
    """Isolates directories and resets the verification service before and after each test."""
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

    # Provision system_id keypair for standard signing fallback
    identity_dir = trust_dir / "system_id"
    identity_dir.mkdir(parents=True, exist_ok=True)
    TraceVerifier.generate_key_pair(output_dir=str(identity_dir))

    # Reset registry before test
    verification_service.reset()
    yield
    # Reset registry after test to prevent leak pollution
    verification_service.reset()


def setup_vault(run_id, trace_name="run.jsonl"):
    vault_dir = config.RUN_LOG_DIR / run_id
    vault_dir.mkdir(parents=True, exist_ok=True)
    trace_path = vault_dir / trace_name
    return vault_dir, trace_path


def test_interceptor_preemption():
    """Verify that an interceptor can completely preempt signature generation."""
    run_id = "run-preempt"
    vault_dir, trace_path = setup_vault(run_id)
    trace_path.write_text("dummy trace contents", encoding="utf-8")

    preemptor = MockPreemptiveInterceptor()
    verification_service.register_interceptor(preemptor)

    # Use format='preempt' to activate preemptor
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

    # Standard signing format
    manifest = TraceVerifier.sign_trace(str(trace_path), run_id=run_id)

    # Provenance chain should have:
    # 1. Standard Evaluator (ED25519) [and PQC if enabled]
    # 2. MockAugmentingInterceptor (MOCK)
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

    # Before context manager: verification service is empty, standard signature is generated
    manifest1 = TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
    assert manifest1["provenance_chain"][0]["identity"] == "system_id"

    with verification_service.override_interceptor(preemptor):
        # Inside context manager: preemptor is active
        TraceVerifier.sign_trace(str(trace_path), run_id=run_id, compliance_status="pass")
        # If it bypassed can_sign, standard signing would run.
        # But wait, TraceVerifier uses config.PQC_ENABLED or hybrid or ED25519.
        # Wait, if we call sign_trace, it passes "hybrid" or "ED25519" to verification_service.sign.
        # So we can temporarily override MockPreemptiveInterceptor's can_sign to return True!
        pass

    # Let's write a targeted test directly using verification_service.sign to verify the
    # override context manager.
    with verification_service.override_interceptor(preemptor):
        manifest_preempt = {"provenance_chain": []}
        res = verification_service.sign(manifest_preempt, format="preempt")
        assert res["provenance_chain"][0]["identity"] == "preempted_signer"

    # Outside context manager: preemptor is removed
    manifest_empty = {"provenance_chain": []}
    # Bypasses to core signer
    res = verification_service.sign(manifest_empty, format="preempt")
    assert res["provenance_chain"][0]["identity"] == "system_id"
