"""
Golden pass/fail ground-truth verification matrix tests with Independent Oracle.
Verifies that TraceVerifier independently detects all forms of trace tampering,
reordering, deletion, event insertion, signature corruption, and key substitution.
Includes an independent cryptographic oracle built with stdlib/cryptography to
prevent symmetrical verification bugs.
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from agentv_runtime.manifest import compute_scenario_hash
from eval_runner import config
from eval_runner.identity import IdentityService
from eval_runner.verifier import (
    CertificationFailedError,
    TraceVerifier,
    VerificationResult,
    verify_trace_certificate,
)


class IndependentTraceOracle:
    """
    Independent Cryptographic Oracle.
    Independent cryptographic oracle for trace hashing (SHA3-256) and Ed25519 provenance,
    with an independent verification path for PQC (ML-DSA-65) signatures.
    """

    @staticmethod
    def compute_sha3_256(file_path) -> str:
        h = hashlib.sha3_256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def verify_manifest(manifest_path, trace_path) -> bool:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        # 1. Independent Trace SHA3-256 Check
        expected_hash = manifest.get("trace_hash")
        actual_hash = IndependentTraceOracle.compute_sha3_256(trace_path)
        if expected_hash != actual_hash:
            return False

        # 2. Independent Ed25519 Provenance Verification
        chain = manifest.get("provenance_chain", [])
        if not chain:
            return False

        manifest_copy = manifest.copy()
        manifest_copy.pop("provenance_chain", None)
        manifest_bytes = json.dumps(manifest_copy, sort_keys=True).encode("utf-8")

        for node in chain:
            identity_id = node.get("identity")
            sig_hex = node.get("signature")
            algorithm = node.get("algorithm", "ED25519")

            if algorithm == "ED25519":
                try:
                    pub_key = IdentityService.get_public_key(identity_id)
                    pub_key.verify(bytes.fromhex(sig_hex), manifest_bytes)
                except Exception:
                    return False
            elif algorithm == "ML-DSA-65":
                pqc_client = IdentityService.get_pqc_client()
                if pqc_client:
                    from eval_runner import forensics

                    shake_digest = forensics.compute_shake256_digest(manifest_bytes)
                    is_valid = pqc_client.verify_digest(
                        signature=sig_hex,
                        digest=shake_digest,
                        identity_id=config.PQC_IDENTITY_ID,
                    )
                    if not is_valid:
                        return False
        return True


@pytest.fixture
def clean_vault_setup(tmp_path, monkeypatch):
    """
    Sets up an isolated project vault structure for golden matrix verification testing.
    Includes a provisioned signing identity so certification is fail-closed-capable.
    """
    project_root = tmp_path / "project"
    run_log_dir = project_root / "runs"
    reports_dir = project_root / "reports"
    trust_root = project_root / ".aes" / "keys"
    run_id = "run-golden-matrix-001"
    run_dir = run_log_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    trust_root.mkdir(parents=True, exist_ok=True)

    trace_file = run_dir / "run.jsonl"
    line1 = json.dumps({"event": "start", "run_id": run_id, "turn": 1})
    line2 = json.dumps({"event": "action", "tool": "search", "query": "auth_key"})
    line3 = json.dumps({"event": "stop", "run_id": run_id, "turn": 2})
    trace_file.write_text(f"{line1}\n{line2}\n{line3}\n", encoding="utf-8")

    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", project_root)
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", run_log_dir)
    monkeypatch.setattr("eval_runner.config.REPORTS_DIR", reports_dir)
    monkeypatch.setattr("eval_runner.config.TRUST_ROOT", trust_root)

    # Provision system_id keypair: certification must be able to actually sign.
    from eval_runner.identity import IdentityService

    IdentityService._provision_local_identity("system_id")

    return {
        "project_root": project_root,
        "run_log_dir": run_log_dir,
        "run_id": run_id,
        "run_dir": run_dir,
        "trace_file": trace_file,
    }


def test_wsm_score_calculation_valid():
    """
    Test standard WSM scoring calculation with all dimensions above safety floor.
    """
    metrics = {
        "safety": 1.0,
        "security": 1.0,
        "reliability": 1.0,
        "fairness": 1.0,
        "explainability": 1.0,
        "privacy": 1.0,
        "resilience": 1.0,
    }
    result = VerificationResult(success=True, message="All clear", metrics=metrics)
    assert result.success is True
    assert result.aggregate_score == 1.0


def test_wsm_score_safety_floor_trigger():
    """
    Test that if safety metric drops below 0.5, aggregate score is capped at 0.49.
    """
    metrics = {
        "safety": 0.4,
        "security": 1.0,
        "reliability": 1.0,
        "fairness": 1.0,
        "explainability": 1.0,
        "privacy": 1.0,
        "resilience": 1.0,
    }
    result = VerificationResult(success=False, message="Safety violation", metrics=metrics)
    assert result.aggregate_score <= 0.49


# --- 7-Stage Verify-After-Tampering Matrix ---


def test_verify_after_tampering_stage1_valid_trace(clean_vault_setup):
    """
    Stage 1: Valid trace + valid signature -> Both TraceVerifier and Oracle return True.
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        compliance_status="pass",
        compliance_score=1.0,
        run_id=run_id,
    )
    manifest_path = trace_file.parent / "run_manifest.json"

    # Both TraceVerifier and Independent Oracle must report valid verification
    assert TraceVerifier.verify_trace(trace_file, manifest_path) is True
    assert IndependentTraceOracle.verify_manifest(manifest_path, trace_file) is True


def test_verify_after_tampering_stage2_event_data_modified(clean_vault_setup):
    """
    Stage 2: Tamper with event payload data -> Verification fails.
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        compliance_status="pass",
        run_id=run_id,
    )
    manifest_path = trace_file.parent / "run_manifest.json"

    # Tamper with event payload
    content = trace_file.read_text(encoding="utf-8")
    tampered_content = content.replace("search", "unauthorized_admin_escalation")
    trace_file.write_text(tampered_content, encoding="utf-8")

    assert TraceVerifier.verify_trace(trace_file, manifest_path) is False
    assert IndependentTraceOracle.verify_manifest(manifest_path, trace_file) is False


def test_verify_after_tampering_stage3_event_deleted(clean_vault_setup):
    """
    Stage 3: Delete an event line from trace -> Verification fails.
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        compliance_status="pass",
        run_id=run_id,
    )
    manifest_path = trace_file.parent / "run_manifest.json"

    lines = trace_file.read_text(encoding="utf-8").strip().split("\n")
    # Delete second line
    trace_file.write_text(f"{lines[0]}\n{lines[2]}\n", encoding="utf-8")

    assert TraceVerifier.verify_trace(trace_file, manifest_path) is False
    assert IndependentTraceOracle.verify_manifest(manifest_path, trace_file) is False


def test_verify_after_tampering_stage4_event_inserted(clean_vault_setup):
    """
    Stage 4: Insert an unauthorized event line into trace -> Verification fails.
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        compliance_status="pass",
        run_id=run_id,
    )
    manifest_path = trace_file.parent / "run_manifest.json"

    content = trace_file.read_text(encoding="utf-8")
    extra_line = json.dumps({"event": "malicious_injection", "tool": "exec_shell"})
    trace_file.write_text(f"{content}{extra_line}\n", encoding="utf-8")

    assert TraceVerifier.verify_trace(trace_file, manifest_path) is False
    assert IndependentTraceOracle.verify_manifest(manifest_path, trace_file) is False


def test_verify_after_tampering_stage5_event_reordered(clean_vault_setup):
    """
    Stage 5: Reorder event sequence -> Verification fails.
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        compliance_status="pass",
        run_id=run_id,
    )
    manifest_path = trace_file.parent / "run_manifest.json"

    lines = trace_file.read_text(encoding="utf-8").strip().split("\n")
    # Reorder lines 1 and 2
    trace_file.write_text(f"{lines[1]}\n{lines[0]}\n{lines[2]}\n", encoding="utf-8")

    assert TraceVerifier.verify_trace(trace_file, manifest_path) is False
    assert IndependentTraceOracle.verify_manifest(manifest_path, trace_file) is False


def test_verify_after_tampering_stage6_signature_corrupted(clean_vault_setup):
    """
    Stage 6: Modify signature hex in manifest -> Verification fails.
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    manifest = TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        compliance_status="pass",
        run_id=run_id,
    )
    manifest_path = trace_file.parent / "run_manifest.json"

    # Corrupt signature in manifest
    manifest["provenance_chain"][0]["signature"] = "a" * 128
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert TraceVerifier.verify_trace(trace_file, manifest_path) is False
    assert IndependentTraceOracle.verify_manifest(manifest_path, trace_file) is False


def test_verify_after_tampering_stage7_key_substituted(clean_vault_setup):
    """
    Stage 7: Substitute identity ID in manifest with unauthorized key -> Verification fails.
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    manifest = TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        compliance_status="pass",
        run_id=run_id,
    )
    manifest_path = trace_file.parent / "run_manifest.json"

    # Substitute identity ID to un-registered / unauthorized key
    manifest["provenance_chain"][0]["identity"] = "unauthorized_attacker_key"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert TraceVerifier.verify_trace(trace_file, manifest_path) is False
    assert IndependentTraceOracle.verify_manifest(manifest_path, trace_file) is False


def test_verifier_computed_hash_mismatch(clean_vault_setup):
    """
    Mutation Assurance Test: Verifies that compute_signature != expected_file_hash returns False
    (kills != -> == mutation in trace hash verification).
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    manifest = TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        compliance_status="pass",
        run_id=run_id,
    )
    manifest_path = trace_file.parent / "run_manifest.json"

    # Corrupt trace_hash in manifest
    manifest["trace_hash"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert TraceVerifier.verify_trace(trace_file, manifest_path) is False


def test_verifier_fresh_manifest_ttl_age(clean_vault_setup):
    """
    Mutation Assurance Test: Verifies age calculation datetime.now() - created_at
    uses subtraction '-' (kills - -> + mutation in TTL age calculation).
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        compliance_status="pass",
        run_id=run_id,
    )
    manifest_path = trace_file.parent / "run_manifest.json"

    # A fresh manifest must pass TTL verification
    assert TraceVerifier.verify_trace(trace_file, manifest_path) is True


def test_verifier_nested_key_dir_creation(tmp_path):
    """
    Mutation Assurance Test: Verifies generate_key_pair creates nested parent directories
    using parents=True (kills parents=True -> False mutation in output directory creation).
    """
    nested_dir = tmp_path / "deep" / "nested" / "keys"
    # Ensure parents do not exist
    assert not nested_dir.parent.exists()

    TraceVerifier.generate_key_pair(output_dir=str(nested_dir))
    assert (nested_dir / "private_key.pem").exists()
    assert (nested_dir / "public_key.pem").exists()


def test_verifier_trace_lifecycle_event_appended(clean_vault_setup):
    """
    Mutation Assurance Test: Verifies sign_trace appends 'verification_certificate_issued'
    event to trace file (kills + -> - mutation in lifecycle event recording).
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        compliance_status="pass",
        run_id=run_id,
    )

    trace_content = trace_file.read_text(encoding="utf-8")
    assert "verification_certificate_issued" in trace_content, (
        "Expected sign_trace to append 'verification_certificate_issued' event to trace file"
    )
    assert "seal_hash" in trace_content


def test_verifier_jail_escape_attempt(tmp_path):
    """
    Mutation Assurance Test: Verifies verify_trace returns False for paths outside project jail
    (kills return False -> True mutation in path safety check at line 543).
    """
    from unittest.mock import patch

    outside_trace = tmp_path / "run.jsonl"
    outside_manifest = tmp_path / "run_manifest.json"
    outside_trace.write_text('{"event": "start"}\n', encoding="utf-8")
    outside_manifest.write_text('{"trace_hash": "abc"}\n', encoding="utf-8")

    # Mock is_path_safe to return False (simulating jail escape)
    with patch("eval_runner.verifier.utils.is_path_safe", return_value=False):
        assert TraceVerifier.verify_trace(outside_trace, outside_manifest) is False


def test_verifier_existing_output_dir_exist_ok(tmp_path):
    """
    Mutation Assurance Test: Verifies generate_key_pair succeeds on an existing directory
    using exist_ok=True (kills exist_ok=True -> exist_ok=False mutation in key generation).
    """
    existing_dir = tmp_path / "existing_keys_dir"
    existing_dir.mkdir(parents=True, exist_ok=True)

    # Calling generate_key_pair on existing directory requires exist_ok=True
    TraceVerifier.generate_key_pair(output_dir=str(existing_dir))
    assert (existing_dir / "private_key.pem").exists()


def test_verifier_governance_ttl_subtraction(clean_vault_setup):
    """
    Mutation Assurance Test: Verifies age calculation uses subtraction '-'
    (kills age = now - created_at '+' mutation in verifier TTL verification).
    """
    from datetime import datetime

    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    manifest = TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        compliance_status="pass",
        run_id=run_id,
    )
    manifest_path = trace_file.parent / "run_manifest.json"

    # Set timezone-aware timestamp
    manifest["timestamp"] = datetime.now().astimezone().isoformat()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    # Re-sign trace with valid timezone-aware timestamp
    manifest = TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        compliance_status="pass",
        run_id=run_id,
    )

    # A freshly signed manifest with timezone must return True
    # If '-' is mutated to '+', age = now + created_at (4000+ years > 30 days), returning False.
    assert TraceVerifier.verify_trace(trace_file, manifest_path) is True


def test_verifier_evidence_ledger_tampered_artifact(clean_vault_setup):
    """
    Mutation Assurance Test: Verifies evidence ledger tampered artifact detection
    (kills != -> == mutation in forensic evidence verification at line 579).
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    # Create sidecar artifact with run_id prefix BEFORE sign_trace
    # so ForensicRelevanceEngine includes it
    artifact_file = trace_file.parent / f"{run_id}_artifact.txt"
    artifact_file.write_text("original content", encoding="utf-8")

    # Sign trace to generate valid signature over manifest containing evidence_ledger
    TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        compliance_status="pass",
        run_id=run_id,
    )
    manifest_path = trace_file.parent / "run_manifest.json"

    # Tamper sidecar artifact content AFTER sign_trace (manifest signature remains valid)
    artifact_file.write_text("tampered malicious content", encoding="utf-8")

    # Tampered evidence ledger artifact MUST fail verification when verify_ledger=True
    assert TraceVerifier.verify_trace(trace_file, manifest_path, verify_ledger=True) is False


def test_verifier_pqc_algorithm_branch(clean_vault_setup):
    """
    Mutation Assurance Test: Verifies PQC algorithm branch check 'elif algorithm == "ML-DSA-65"'
    (kills == -> != mutation in verifier signature verification).
    """
    from unittest.mock import MagicMock, patch

    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    manifest = TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        compliance_status="pass",
        run_id=run_id,
    )
    manifest_path = trace_file.parent / "run_manifest.json"

    # Add ML-DSA-65 signature to provenance_chain
    manifest["provenance_chain"].append(
        {
            "identity": "pqc_signer",
            "algorithm": "ML-DSA-65",
            "signature": "00" * 32,
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    mock_client = MagicMock()
    mock_client.verify_digest.return_value = False

    # When == is mutated to !=, algorithm ML-DSA-65 skips PQC verification (returns True).
    with patch("eval_runner.identity.IdentityService.get_pqc_client", return_value=mock_client):
        assert TraceVerifier.verify_trace(trace_file, manifest_path) is False


def test_verifier_master_log_anchoring(clean_vault_setup, monkeypatch):
    """
    Mutation Assurance Test: Verifies is_master = resolved_p == master_path
    (kills == -> != mutation at line 395 in verifier.py).
    """
    master_log_dir = clean_vault_setup["project_root"] / "runs"
    master_log_dir.mkdir(parents=True, exist_ok=True)
    master_log = master_log_dir / "run.jsonl"
    master_log.write_text('{"event": "start"}\n', encoding="utf-8")

    monkeypatch.setattr(config, "RUN_LOG_DIR", master_log_dir)
    manifest = TraceVerifier.sign_trace(
        trace_path=str(master_log),
        identity_id="system_id",
        compliance_status="pass",
        run_id="master_run",
    )
    assert manifest["run_id"] == "master_run"


def test_verifier_certificate_mkdir_exist_ok(clean_vault_setup):
    """
    Mutation Assurance Test: Verifies cert_dir.mkdir(parents=True, exist_ok=True)
    when cert_dir already exists (kills exist_ok=True -> False mutation at line 490).
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    cert_dir = config.REPORTS_DIR / "certificates"
    cert_dir.mkdir(parents=True, exist_ok=True)

    m1 = TraceVerifier.sign_trace(str(trace_file), identity_id="s1", run_id=run_id)
    m2 = TraceVerifier.sign_trace(str(trace_file), identity_id="s2", run_id=run_id)
    assert m1 is not None and m2 is not None


def test_verifier_invalid_manifest_branches(clean_vault_setup):
    """
    Mutation Assurance Test: Verifies invalid manifest failure returns False
    (kills return False -> True mutations at lines 551, 562, 578, 593, 596, 602 in verifier.py).
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    manifest = TraceVerifier.sign_trace(
        trace_path=str(trace_file), identity_id="signer", run_id=run_id
    )
    manifest_path = trace_file.parent / "run_manifest.json"

    # 1. Invalid version
    m1 = manifest.copy()
    m1["vc_version"] = "1.0.0"
    manifest_path.write_text(json.dumps(m1), encoding="utf-8")
    assert TraceVerifier.verify_trace(trace_file, manifest_path) is False

    # 2. Corrupted governance timestamp
    m2 = manifest.copy()
    m2["timestamp"] = "1990-01-01T00:00:00.000+0000"
    manifest_path.write_text(json.dumps(m2), encoding="utf-8")
    assert TraceVerifier.verify_trace(trace_file, manifest_path) is False

    # 3. Missing forensic artifact specified in evidence ledger
    m3 = manifest.copy()
    m3["evidence_ledger"]["missing_sidecar.txt"] = "00" * 32
    manifest_path.write_text(json.dumps(m3), encoding="utf-8")
    assert TraceVerifier.verify_trace(trace_file, manifest_path, verify_ledger=True) is False

    # 4. Empty provenance chain
    m4 = manifest.copy()
    m4["provenance_chain"] = []
    manifest_path.write_text(json.dumps(m4), encoding="utf-8")
    assert TraceVerifier.verify_trace(trace_file, manifest_path) is False

    # 5. Invalid signature format / corrupted key
    m5 = manifest.copy()
    m5["provenance_chain"] = [{"identity": "s", "algorithm": "ED25519", "signature": "xyz"}]
    manifest_path.write_text(json.dumps(m5), encoding="utf-8")
    assert TraceVerifier.verify_trace(trace_file, manifest_path) is False


def test_verification_service_interceptor_pipeline():
    """
    Mutation Assurance Test: Verifies VerificationService interceptor pipeline
    uses index + 1 and depth + 1 (kills index + 1 -> - 1 and depth + 1 -> - 1).
    """
    from eval_runner.verifier import VerificationService

    history = []

    class InterceptorA:
        def can_sign(self, format):
            return True

        def sign(self, manifest, next_fn):
            history.append("A")
            return next_fn(manifest)

    class InterceptorB:
        def can_sign(self, format):
            return True

        def sign(self, manifest, next_fn):
            history.append("B")
            return next_fn(manifest)

    class InterceptorSkip:
        def can_sign(self, format):
            return False

        def sign(self, manifest, next_fn):
            history.append("SKIP")
            return next_fn(manifest)

    class InterceptorFails:
        def can_sign(self, format):
            return True

        def sign(self, manifest, next_fn):
            history.append("FAILS")
            raise RuntimeError("Interceptor crashed")

    # 1. Normal multi-interceptor execution
    service = VerificationService()
    service.register_interceptor(InterceptorA())
    service.register_interceptor(InterceptorB())

    res = service.sign({"vc_version": "3.0.0"}, format="ED25519")
    assert history == ["B", "A"]
    assert isinstance(res, dict)

    # 2. Interceptor cannot sign format -> bypassed
    history.clear()
    service2 = VerificationService()
    service2.register_interceptor(InterceptorA())
    service2.register_interceptor(InterceptorSkip())
    service2.sign({"vc_version": "3.0.0"}, format="ED25519")
    assert history == ["A"]

    # 3. Interceptor raises exception -> bypassed
    history.clear()
    service3 = VerificationService()
    service3.register_interceptor(InterceptorA())
    service3.register_interceptor(InterceptorFails())
    service3.sign({"vc_version": "3.0.0"}, format="ED25519")
    assert history == ["FAILS", "A"]

    # 4. Cycle / depth detection across all paths (kills depth + 1 -> - 1)
    service_loop = VerificationService()
    for _ in range(55):
        service_loop.register_interceptor(InterceptorA())
    with pytest.raises(RecursionError, match="Max verifier pipeline depth exceeded"):
        service_loop.sign({"vc_version": "3.0.0"}, format="ED25519")

    # Skipped interceptors depth increment (kills depth + 1 -> - 1)
    service_loop_skip = VerificationService()
    for _ in range(55):
        service_loop_skip.register_interceptor(InterceptorSkip())
    with pytest.raises(RecursionError, match="Max verifier pipeline depth exceeded"):
        service_loop_skip.sign({"vc_version": "3.0.0"}, format="ED25519")

    # Failing interceptors depth increment (kills depth + 1 -> - 1)
    service_loop_fails = VerificationService()
    for _ in range(55):
        service_loop_fails.register_interceptor(InterceptorFails())
    with pytest.raises(RecursionError, match="Max verifier pipeline depth exceeded"):
        service_loop_fails.sign({"vc_version": "3.0.0"}, format="ED25519")


def test_verifier_missing_trace_file_verify_trace(clean_vault_setup):
    """
    Mutation Assurance Test: Verifies verify_trace returns False when trace file is missing
    (kills return False -> True mutation).
    """
    manifest_path = clean_vault_setup["run_dir"] / "verification_manifest.json"
    manifest_path.write_text(json.dumps({"vc_version": "3.0.0"}), encoding="utf-8")
    non_existent_trace = clean_vault_setup["run_dir"] / "missing_run.jsonl"
    assert TraceVerifier.verify_trace(non_existent_trace, manifest_path) is False


def test_verifier_invalid_iso_timestamp_governance(clean_vault_setup):
    """
    Mutation Assurance Test: Verifies invalid timestamp in manifest triggers exception handler
    (kills return False -> True mutation).
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]
    manifest = TraceVerifier.sign_trace(
        trace_path=str(trace_file), identity_id="signer", run_id=run_id
    )
    manifest_path = clean_vault_setup["run_dir"] / "verification_manifest.json"
    manifest["timestamp"] = "not-a-valid-iso-date-string"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert TraceVerifier.verify_trace(trace_file, manifest_path) is False


def test_verifier_certificate_mkdir_nested_parents(clean_vault_setup, monkeypatch, tmp_path):
    """
    Mutation Assurance Test: Verifies cert_dir.mkdir(parents=True, exist_ok=True) creates nested
    dirs (kills parents=True -> False and exist_ok=True -> False).
    """
    deep_project = tmp_path / "deep" / "nested" / "project"
    deep_reports = deep_project / "reports"
    monkeypatch.setattr(config, "PROJECT_ROOT", deep_project)
    monkeypatch.setattr(config, "REPORTS_DIR", deep_reports)
    monkeypatch.setattr(config, "RUN_LOG_DIR", deep_project / "runs")
    run_id = "run-deep-001"
    deep_run_dir = deep_project / "runs" / run_id
    deep_run_dir.mkdir(parents=True, exist_ok=True)
    deep_trace = deep_run_dir / "run.jsonl"
    deep_trace.write_text('{"event": "start"}\n', encoding="utf-8")

    # 1. Parents=True test on non-existent parent directory
    m1 = TraceVerifier.sign_trace(trace_path=str(deep_trace), identity_id="signer", run_id=run_id)
    assert m1 is not None
    cert_file1 = deep_reports / "certificates" / f"{run_id}_vc.json"
    assert cert_file1.exists()

    # 2. Exist_ok=True test on already existing directory with new run_id
    run_id2 = "run-deep-002"
    deep_run_dir2 = deep_project / "runs" / run_id2
    deep_run_dir2.mkdir(parents=True, exist_ok=True)
    deep_trace2 = deep_run_dir2 / "run.jsonl"
    deep_trace2.write_text('{"event": "start"}\n', encoding="utf-8")
    m2 = TraceVerifier.sign_trace(trace_path=str(deep_trace2), identity_id="signer", run_id=run_id2)
    assert m2 is not None
    cert_file2 = deep_reports / "certificates" / f"{run_id2}_vc.json"
    assert cert_file2.exists()


def test_verifier_sign_outside_vault_raises_error(clean_vault_setup, tmp_path):
    """
    Mutation Assurance Test: Verifies signing a trace outside vault raises Forensic Pollution error
    (kills resolved_p == vault_path -> != mutation).
    """
    outside_trace = clean_vault_setup["project_root"] / "outside_run.jsonl"
    outside_trace.write_text('{"event": "start"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="Forensic Pollution"):
        TraceVerifier.sign_trace(
            trace_path=str(outside_trace), identity_id="signer", run_id="run-outside"
        )


def test_verifier_tampered_trace_hash_returns_false(clean_vault_setup):
    """
    Mutation Assurance Test: Verifies verify_trace returns False on trace hash mismatch
    (kills return False -> True mutation).
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]
    manifest = TraceVerifier.sign_trace(
        trace_path=str(trace_file), identity_id="signer", run_id=run_id
    )
    manifest_path = clean_vault_setup["run_dir"] / "verification_manifest.json"
    manifest["trace_hash"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert TraceVerifier.verify_trace(trace_file, manifest_path) is False


def test_verifier_valid_trace_with_governance_ttl_assert_true(clean_vault_setup):
    """
    Mutation Assurance Test: Verifies verify_trace with governance TTL subtraction
    (kills age = datetime.now() - created_at (- -> +) mutation).
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]
    manifest = TraceVerifier.sign_trace(
        trace_path=str(trace_file), identity_id="signer", run_id=run_id, ttl_days=30
    )
    manifest_path = clean_vault_setup["run_dir"] / "verification_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert TraceVerifier.verify_trace(trace_file, manifest_path) is True


# --- Wave-1 Hotfix Regression: WSM scoring authority -----------------------


def test_wsm_explicit_aggregate_score_override():
    """An explicitly provided aggregate_score must be honored verbatim (fail-closed scoring)."""
    metrics = {dim: 1.0 for dim in VerificationResult.WSM_WEIGHTS}
    result = VerificationResult(
        success=True, message="override", metrics=metrics, aggregate_score=0.1234
    )
    assert result.aggregate_score == 0.1234


def test_wsm_safety_floor_boundaries_and_rounding():
    """Safety/security floors cap exactly at 0.49; boundary 0.5 is uncapped; score rounds to 4dp."""
    dims = list(VerificationResult.WSM_WEIGHTS)

    def _metrics(**overrides):
        m = {d: 1.0 for d in dims}
        m.update(overrides)
        return m

    # Below-floor safety caps exactly at 0.49 even with every other dimension maxed.
    assert VerificationResult(False, "s", metrics=_metrics(safety=0.49)).aggregate_score == 0.49
    # Below-floor security caps exactly at 0.49.
    assert VerificationResult(False, "s", metrics=_metrics(security=0.49)).aggregate_score == 0.49
    # Exactly AT the floor boundary there is no cap: 0.25*0.5 + 0.75 = 0.875.
    assert VerificationResult(True, "ok", metrics=_metrics(safety=0.5)).aggregate_score == 0.875

    # Aggregate score is rounded to 4 decimal places.
    flat = {d: 0.0 for d in dims}
    flat["reliability"] = 0.1111111
    result = VerificationResult(True, "r", metrics=flat)
    assert result.aggregate_score == round(0.1111111 * 0.20, 4) == 0.0222


# --- Wave-1 Hotfix Regression: fail-closed signer (S2) ----------------------


def test_core_signer_unsignable_identity_fails_closed(clean_vault_setup, monkeypatch):
    """
    An identity exposing no signing capability must abort certification outright.
    Degenerate placeholder signatures ('00'*64) are prohibited: no certificate,
    sidecar, or published artifact may survive an un-signable transaction.
    """

    class _UnsignableKey:
        """Resolved identity object with neither private_bytes nor sign."""

    monkeypatch.setattr(
        "eval_runner.identity.IdentityService.get_private_key",
        lambda *a, **k: _UnsignableKey(),
    )
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]
    original_content = trace_file.read_text(encoding="utf-8")
    sidecar = trace_file.parent / "run_manifest.json"

    with pytest.raises(CertificationFailedError, match="no usable signing capability"):
        TraceVerifier.sign_trace(str(trace_file), identity_id="ghost_signer", run_id=run_id)

    # Fail-closed: the aborted transaction leaves zero certificate artifacts.
    assert not sidecar.exists()
    assert not (config.REPORTS_DIR / "certificates" / f"{run_id}_vc.json").exists()
    assert trace_file.read_text(encoding="utf-8") == original_content


def test_certification_failure_rolls_back_partial_mutation(clean_vault_setup):
    """
    A failed post-signature verification stage must roll back the trace append
    and remove partial artifacts before surfacing CertificationFailedError.
    """
    from unittest.mock import patch

    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]
    original_content = trace_file.read_text(encoding="utf-8")

    with patch.object(TraceVerifier, "verify_trace", return_value=False):
        with pytest.raises(CertificationFailedError, match="stage 'verify'"):
            TraceVerifier.sign_trace(str(trace_file), identity_id="signer", run_id=run_id)

    # The trace was truncated back to its exact pre-append content.
    assert trace_file.read_text(encoding="utf-8") == original_content
    assert not (trace_file.parent / "run_manifest.json").exists()
    assert not (config.REPORTS_DIR / "certificates" / f"{run_id}_vc.json").exists()


def test_lifecycle_event_never_merged_or_doubled(clean_vault_setup):
    """
    The certification event must start on a fresh line whether or not the trace
    ends with a newline, and must never introduce a doubled blank separator.
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]
    manifest_path = trace_file.parent / "run_manifest.json"
    event_marker = '{"event": "verification_certificate_issued"'

    # Case 1: trace WITHOUT trailing newline -> exactly one separator inserted.
    content = trace_file.read_text(encoding="utf-8")
    trace_file.write_text(content.rstrip("\n"), encoding="utf-8")
    TraceVerifier.sign_trace(str(trace_file), identity_id="signer", run_id=run_id)
    data = trace_file.read_text(encoding="utf-8")
    idx = data.rindex(event_marker)
    assert idx > 0
    assert data[idx - 1] == "\n", "certification event must begin on a fresh line"
    assert data[idx - 2] != "\n", "certification event must not introduce a doubled newline"
    assert TraceVerifier.verify_trace(str(trace_file), str(manifest_path)) is True

    # Case 2: newline-terminated trace -> appended directly, still no doubling.
    TraceVerifier.sign_trace(str(trace_file), identity_id="signer", run_id=run_id)
    data2 = trace_file.read_text(encoding="utf-8")
    idx2 = data2.rindex(event_marker)
    assert data2[idx2 - 1] == "\n"
    assert data2[idx2 - 2] != "\n"


def test_lifecycle_event_on_empty_trace_starts_at_byte_zero(clean_vault_setup):
    """
    Certifying a zero-byte vault must append the lifecycle event at byte 0 with
    no synthetic leading newline (kills needs_newline initializer mutations that
    are otherwise shadowed by the trailing-byte detection on non-empty traces).
    """
    run_id = "run-empty-001"
    empty_run_dir = clean_vault_setup["run_log_dir"] / run_id
    empty_run_dir.mkdir(parents=True, exist_ok=True)
    empty_trace = empty_run_dir / "run.jsonl"
    empty_trace.write_bytes(b"")

    manifest = TraceVerifier.sign_trace(str(empty_trace), identity_id="signer", run_id=run_id)
    assert manifest["certification"]["outcome"] == "CERTIFIED"

    raw = empty_trace.read_bytes()
    assert raw.startswith(b'{"event": "verification_certificate_issued"'), (
        "certification event must start at byte zero on an empty trace"
    )
    assert raw.endswith(b"\n")
    assert (
        TraceVerifier.verify_trace(str(empty_trace), str(empty_trace.parent / "run_manifest.json"))
        is True
    )


# --- Wave-1 Hotfix Regression: verify_trace_certificate + degenerate sigs ---

VC_EVENT_LINE = '{"event": "start"}\n'


@pytest.fixture
def certified_manifest(clean_vault_setup):
    """A genuinely certified vault: signed manifest plus raw trace bytes."""
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]
    manifest = TraceVerifier.sign_trace(str(trace_file), identity_id="test_signer", run_id=run_id)
    return {
        "manifest": manifest,
        "trace_bytes": trace_file.read_bytes(),
        **clean_vault_setup,
    }


def test_verify_trace_certificate_happy_path(certified_manifest):
    """A genuinely certified evidence blob verifies with full attribution."""
    manifest = certified_manifest["manifest"]

    # Transactional certification metadata must be present and truthful.
    assert manifest["certification"]["transactional"] is True
    assert manifest["certification"]["outcome"] == "CERTIFIED"

    result = verify_trace_certificate(
        certified_manifest["run_id"], certified_manifest["trace_bytes"], manifest
    )
    assert result["verified"] is True
    assert result["manifest_hash_match"] is True
    assert result["scenario_hash_match"] is False  # no scenario data supplied
    assert result["signer_identity"] == "test_signer"
    assert result["algorithm"] == "ED25519"
    assert result["errors"] == []


def test_verify_trace_certificate_hash_mismatch(certified_manifest):
    """Any byte-level divergence between trace and cert hash must be flagged."""
    tampered = certified_manifest["trace_bytes"][:-8] + b"tampered"
    result = verify_trace_certificate(
        certified_manifest["run_id"], tampered, certified_manifest["manifest"]
    )
    assert result["verified"] is False
    assert result["manifest_hash_match"] is False
    assert any("Trace hash mismatch" in e for e in result["errors"])


def test_verify_trace_certificate_missing_trace_hash(certified_manifest):
    """A certificate without a trace_hash can never be verified."""
    stripped = {k: v for k, v in certified_manifest["manifest"].items() if k != "trace_hash"}
    result = verify_trace_certificate(
        certified_manifest["run_id"], certified_manifest["trace_bytes"], stripped
    )
    assert result["verified"] is False
    assert result["manifest_hash_match"] is False
    assert any("does not contain a trace_hash" in e for e in result["errors"])


def test_verify_certificate_scenario_hash_match_and_mismatch(certified_manifest):
    """Scenario binding: matching canonical hash flags a match; any drift flags a mismatch."""
    scenario = {"scenario_id": "sc-1", "name": "demo", "steps": [{"tool": "search"}]}
    expected = compute_scenario_hash(scenario)  # 'sha3_256:<hex>' prefixed form
    with_hash = {**certified_manifest["manifest"], "scenario_hash": expected}

    ok = verify_trace_certificate(
        certified_manifest["run_id"],
        certified_manifest["trace_bytes"],
        with_hash,
        scenario_data=scenario,
    )
    assert ok["scenario_hash_match"] is True
    # Post-signing payload mutation (the injected scenario_hash) breaks the signature:
    # integrity binding means verification cannot silently pass.
    assert ok["verified"] is False

    other = {**scenario, "name": "tampered"}
    bad = verify_trace_certificate(
        certified_manifest["run_id"],
        certified_manifest["trace_bytes"],
        with_hash,
        scenario_data=other,
    )
    assert bad["scenario_hash_match"] is False
    assert bad["verified"] is False
    assert any("Scenario hash mismatch" in e for e in bad["errors"])


def test_verify_certificate_rejects_degenerate_all_zero_signature(certified_manifest):
    """
    S2b: all-zero placeholder signatures are structurally invalid and must be
    rejected with an explicit fail-closed error, never treated as proof.
    """
    forged = copy.deepcopy(certified_manifest["manifest"])
    forged["provenance_chain"][0]["signature"] = "00" * 64

    result = verify_trace_certificate(
        certified_manifest["run_id"], certified_manifest["trace_bytes"], forged
    )
    assert result["verified"] is False
    assert result["signer_identity"] is None
    assert any(
        "Degenerate all-zero signature rejected for identity 'test_signer'" in e
        for e in result["errors"]
    )


def test_degenerate_signature_cannot_bypass_via_transparent_key(certified_manifest, monkeypatch):
    """
    S2b rationale: against a transparent/mock key object an all-zero signature
    would otherwise pass verification silently. The structural rejection guard
    must fire before any key material is consulted.
    """
    from unittest.mock import MagicMock

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    transparent_key = MagicMock(spec=Ed25519PublicKey)
    # verify() on this spec'd mock returns a Mock (no exception) — a naive
    # verifier would accept the degenerate signature.

    class _TransparentIdentity:
        def public_key(self):
            return transparent_key

    monkeypatch.setattr(
        "eval_runner.identity.IdentityService.get_private_key",
        lambda *a, **k: _TransparentIdentity(),
    )

    forged = copy.deepcopy(certified_manifest["manifest"])
    forged["provenance_chain"][0]["signature"] = "00" * 64

    result = verify_trace_certificate(
        certified_manifest["run_id"], certified_manifest["trace_bytes"], forged
    )
    assert result["verified"] is False
    assert result["signer_identity"] is None
    assert any("Degenerate all-zero" in e for e in result["errors"])


def test_verify_trace_rejects_empty_provenance_chain(certified_manifest):
    """
    A v3 manifest with an empty provenance chain must fail full verification
    (deep copy: prior ledger contamination in shared dicts must not mask the
    chain-authority branch).
    """
    certified_manifest["run_id"]
    trace_file = certified_manifest["trace_file"]
    manifest_path = trace_file.parent / "verification_manifest.json"

    stripped = copy.deepcopy(certified_manifest["manifest"])
    stripped.pop("certification", None)
    stripped["provenance_chain"] = []
    manifest_path.write_text(json.dumps(stripped), encoding="utf-8")

    assert TraceVerifier.verify_trace(trace_file, manifest_path) is False


def test_verify_certificate_provenance_chain_defects(certified_manifest):
    """Empty, malformed, and undersized provenance entries are each rejected."""
    run_id = certified_manifest["run_id"]
    trace_bytes = certified_manifest["trace_bytes"]
    base = certified_manifest["manifest"]

    empty = copy.deepcopy(base)
    empty["provenance_chain"] = []
    r1 = verify_trace_certificate(run_id, trace_bytes, empty)
    assert r1["verified"] is False
    assert any("no provenance_chain entries" in e for e in r1["errors"])

    malformed = copy.deepcopy(base)
    malformed["provenance_chain"] = ["not-a-dict"]
    r2 = verify_trace_certificate(run_id, trace_bytes, malformed)
    assert r2["verified"] is False
    assert any("Malformed provenance entry" in e for e in r2["errors"])

    undersized = copy.deepcopy(base)
    undersized["provenance_chain"][0]["signature"] = "abcd"
    r3 = verify_trace_certificate(run_id, trace_bytes, undersized)
    assert r3["verified"] is False
    assert any("empty or malformed" in e for e in r3["errors"])


def test_verify_run_directory_status_matrix(clean_vault_setup):
    """Every verify_run_directory terminal state reports exact, truthful fields."""
    project_root = clean_vault_setup["project_root"]
    run_log_dir = clean_vault_setup["run_log_dir"]
    run_id = clean_vault_setup["run_id"]
    run_dir = clean_vault_setup["run_dir"]
    trace_file = clean_vault_setup["trace_file"]

    # NOT_FOUND: run directory absent.
    missing = TraceVerifier.verify_run_directory(run_log_dir / "does-not-exist")
    assert missing["verification_status"] == "NOT_FOUND"
    assert missing["is_valid"] is False
    assert missing["has_certificate"] is False
    assert missing["has_signature"] is False
    assert missing["failure_reason"] == "Run directory does not exist"

    # UNVERIFIED: directory + trace exist but no certificate anywhere.
    unverified = TraceVerifier.verify_run_directory(run_dir)
    assert unverified["verification_status"] == "UNVERIFIED"
    assert unverified["is_valid"] is False
    assert unverified["has_certificate"] is False
    assert unverified["has_signature"] is False

    # FAILED_VERIFICATION: certificate present but execution trace missing.
    cert_path = run_dir / "run_manifest.json"
    cert_path.write_text(json.dumps({"vc_version": "3.0.0"}), encoding="utf-8")
    trace_file.unlink()
    orphan_cert = TraceVerifier.verify_run_directory(run_dir)
    assert orphan_cert["verification_status"] == "FAILED_VERIFICATION"
    assert orphan_cert["is_valid"] is False
    assert orphan_cert["has_certificate"] is True
    assert orphan_cert["has_signature"] is False
    assert "missing" in orphan_cert["failure_reason"].lower()

    # VERIFIED: freshly certified vault passes with full chain validation.
    trace_file.write_text(VC_EVENT_LINE, encoding="utf-8")
    TraceVerifier.sign_trace(str(trace_file), identity_id="test_signer", run_id=run_id)
    verified = TraceVerifier.verify_run_directory(run_dir)
    assert verified["verification_status"] == "VERIFIED"
    assert verified["is_valid"] is True
    assert verified["has_certificate"] is True
    assert verified["failure_reason"] is None

    # FAILED_VERIFICATION: post-certification trace tampering is detected.
    with open(trace_file, "ab") as f:
        f.write(b'{"event": "injected"}\n')
    tampered = TraceVerifier.verify_run_directory(run_dir)
    assert tampered["verification_status"] == "FAILED_VERIFICATION"
    assert tampered["is_valid"] is False
    assert tampered["failure_reason"]

    # FAILED_VERIFICATION: unreadable certificate surfaces a verification error.
    cert_path.write_text("{not valid json", encoding="utf-8")
    corrupt = TraceVerifier.verify_run_directory(run_dir)
    assert corrupt["verification_status"] == "FAILED_VERIFICATION"
    assert corrupt["is_valid"] is False
    assert corrupt["has_certificate"] is True
    assert "Verification error" in corrupt["failure_reason"]

    assert project_root.exists()  # jail intact throughout


def test_verify_trace_only_mode_skips_ledger_check(clean_vault_setup):
    """trace_only=True must skip forensic ledger validation explicitly."""
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    artifact = trace_file.parent / f"{run_id}_artifact.txt"
    artifact.write_text("original content", encoding="utf-8")
    TraceVerifier.sign_trace(str(trace_file), identity_id="signer", run_id=run_id)
    manifest_path = trace_file.parent / "run_manifest.json"

    # Tamper the ledger-referenced artifact AFTER certification.
    artifact.write_text("tampered malicious content", encoding="utf-8")

    assert TraceVerifier.verify_trace(trace_file, manifest_path, verify_ledger=True) is False
    assert TraceVerifier.verify_trace(trace_file, manifest_path, trace_only=True) is True


def test_verify_run_directory_enforces_full_evidence_chain(clean_vault_setup):
    """
    verify_run_directory must validate the FULL evidence chain: tampering a
    ledger-referenced artifact (trace untouched) downgrades the verdict to
    FAILED_VERIFICATION.
    """
    run_id = clean_vault_setup["run_id"]
    run_dir = clean_vault_setup["run_dir"]
    trace_file = clean_vault_setup["trace_file"]

    evidence = trace_file.parent / f"{run_id}_artifact.txt"
    evidence.write_text("original content", encoding="utf-8")
    TraceVerifier.sign_trace(str(trace_file), identity_id="test_signer", run_id=run_id)

    # Sanity: pristine evidence verifies cleanly.
    assert TraceVerifier.verify_run_directory(run_dir)["verification_status"] == "VERIFIED"

    # Tamper ONLY the ledger-referenced artifact; execution trace stays intact.
    evidence.write_text("tampered malicious content", encoding="utf-8")

    res = TraceVerifier.verify_run_directory(run_dir)
    assert res["verification_status"] == "FAILED_VERIFICATION"
    assert res["is_valid"] is False
    assert res["failure_reason"]


def test_self_verify_stage_enforces_full_evidence_chain(clean_vault_setup):
    """
    The certification transaction's self-verification stage must run with FULL
    evidence-chain validation: an artifact poisoned between freeze and verify
    aborts certification (fail-closed), it is never sealed.
    """
    from eval_runner.reference.local_artifact import LocalFileArtifactStore

    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]

    evidence = trace_file.parent / f"{run_id}_artifact.txt"
    evidence.write_text("pristine content", encoding="utf-8")

    class _PoisoningStore(LocalFileArtifactStore):
        """Mimics storage side-effects that mutate evidence mid-transaction."""

        def __init__(self, poison_path):
            super().__init__()
            self._poison_path = poison_path

        def store_artifact(self, run_id, artifact_name, content, **kwargs):
            result = super().store_artifact(run_id, artifact_name, content, **kwargs)
            self._poison_path.write_text("post-freeze tampering", encoding="utf-8")
            return result

    with pytest.raises(CertificationFailedError, match="stage 'verify'"):
        TraceVerifier.sign_trace(
            str(trace_file),
            identity_id="signer",
            run_id=run_id,
            artifact_store=_PoisoningStore(evidence),
        )

    # No certificate may survive the aborted transaction.
    assert not (config.REPORTS_DIR / "certificates" / f"{run_id}_vc.json").exists()
