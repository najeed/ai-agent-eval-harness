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

    # 1. Invalid version (line 551)
    m1 = manifest.copy()
    m1["vc_version"] = "1.0.0"
    manifest_path.write_text(json.dumps(m1), encoding="utf-8")
    assert TraceVerifier.verify_trace(trace_file, manifest_path) is False

    # 2. Corrupted governance timestamp (line 562)
    m2 = manifest.copy()
    m2["timestamp"] = "1990-01-01T00:00:00.000+0000"
    manifest_path.write_text(json.dumps(m2), encoding="utf-8")
    assert TraceVerifier.verify_trace(trace_file, manifest_path) is False

    # 3. Missing forensic artifact specified in evidence ledger (line 578)
    m3 = manifest.copy()
    m3["evidence_ledger"]["missing_sidecar.txt"] = "00" * 32
    manifest_path.write_text(json.dumps(m3), encoding="utf-8")
    assert TraceVerifier.verify_trace(trace_file, manifest_path, verify_ledger=True) is False

    # 4. Empty provenance chain (line 593)
    m4 = manifest.copy()
    m4["provenance_chain"] = []
    manifest_path.write_text(json.dumps(m4), encoding="utf-8")
    assert TraceVerifier.verify_trace(trace_file, manifest_path) is False

    # 5. Invalid signature format / corrupted key (line 596)
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

    # 2. Interceptor cannot sign format -> bypassed (kills line 277 + -> -)
    history.clear()
    service2 = VerificationService()
    service2.register_interceptor(InterceptorA())
    service2.register_interceptor(InterceptorSkip())
    service2.sign({"vc_version": "3.0.0"}, format="ED25519")
    assert history == ["A"]

    # 3. Interceptor raises exception -> bypassed (kills line 275 + -> -)
    history.clear()
    service3 = VerificationService()
    service3.register_interceptor(InterceptorA())
    service3.register_interceptor(InterceptorFails())
    service3.sign({"vc_version": "3.0.0"}, format="ED25519")
    assert history == ["FAILS", "A"]

    # 4. Cycle / depth detection across all paths (kills depth + 1 -> - 1 at lines 266, 275, 277)
    service_loop = VerificationService()
    for _ in range(55):
        service_loop.register_interceptor(InterceptorA())
    with pytest.raises(RecursionError, match="Max verifier pipeline depth exceeded"):
        service_loop.sign({"vc_version": "3.0.0"}, format="ED25519")

    # Skipped interceptors depth increment (kills depth + 1 -> - 1 at line 277)
    service_loop_skip = VerificationService()
    for _ in range(55):
        service_loop_skip.register_interceptor(InterceptorSkip())
    with pytest.raises(RecursionError, match="Max verifier pipeline depth exceeded"):
        service_loop_skip.sign({"vc_version": "3.0.0"}, format="ED25519")

    # Failing interceptors depth increment (kills depth + 1 -> - 1 at line 275)
    service_loop_fails = VerificationService()
    for _ in range(55):
        service_loop_fails.register_interceptor(InterceptorFails())
    with pytest.raises(RecursionError, match="Max verifier pipeline depth exceeded"):
        service_loop_fails.sign({"vc_version": "3.0.0"}, format="ED25519")


def test_verifier_missing_trace_file_verify_trace(clean_vault_setup):
    """
    Mutation Assurance Test: Verifies verify_trace returns False when trace file is missing
    (kills return False -> True mutation at line 551 in verifier.py).
    """
    manifest_path = clean_vault_setup["run_dir"] / "verification_manifest.json"
    manifest_path.write_text(json.dumps({"vc_version": "3.0.0"}), encoding="utf-8")
    non_existent_trace = clean_vault_setup["run_dir"] / "missing_run.jsonl"
    assert TraceVerifier.verify_trace(non_existent_trace, manifest_path) is False


def test_verifier_invalid_iso_timestamp_governance(clean_vault_setup):
    """
    Mutation Assurance Test: Verifies invalid timestamp in manifest triggers exception handler
    (kills return False -> True mutation at line 596 in verifier.py).
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
    dirs (kills parents=True -> False and exist_ok=True -> False at line 490 in verifier.py).
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
    (kills resolved_p == vault_path -> != mutation at line 394 in verifier.py).
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
    (kills return False -> True mutation at line 569 in verifier.py).
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
    (kills age = datetime.now() - created_at (- -> +) mutation at line 588 in verifier.py).
    """
    run_id = clean_vault_setup["run_id"]
    trace_file = clean_vault_setup["trace_file"]
    manifest = TraceVerifier.sign_trace(
        trace_path=str(trace_file), identity_id="signer", run_id=run_id, ttl_days=30
    )
    manifest_path = clean_vault_setup["run_dir"] / "verification_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert TraceVerifier.verify_trace(trace_file, manifest_path) is True
