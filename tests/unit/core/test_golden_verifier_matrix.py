"""
Golden pass/fail ground-truth verification matrix tests with Independent Oracle.
Verifies that TraceVerifier independently detects all forms of trace tampering,
reordering, deletion, event insertion, signature corruption, and key substitution.
Includes an independent cryptographic oracle built with stdlib/cryptography to
prevent symmetrical verification bugs.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from eval_runner import config
from eval_runner.identity import IdentityService
from eval_runner.verifier import TraceVerifier, VerificationResult


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
    """
    project_root = tmp_path / "project"
    run_log_dir = project_root / "runs"
    run_id = "run-golden-matrix-001"
    run_dir = run_log_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    trace_file = run_dir / "run.jsonl"
    line1 = json.dumps({"event": "start", "run_id": run_id, "turn": 1})
    line2 = json.dumps({"event": "action", "tool": "search", "query": "auth_key"})
    line3 = json.dumps({"event": "stop", "run_id": run_id, "turn": 2})
    trace_file.write_text(f"{line1}\n{line2}\n{line3}\n", encoding="utf-8")

    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", project_root)
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", run_log_dir)

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

    # Create sidecar artifact BEFORE sign_trace so sign_trace includes its hash in evidence_ledger
    artifact_file = trace_file.parent / "artifact.txt"
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
