"""
Hardened Audit Defensibility & Trace Freeze Test Suite.
Tests the hardened evaluation -> trace -> certification -> verification pipeline:
  1. Hard-freeze run lifecycle and write rejection during/after FINALIZING
  2. Deterministic evidence root derivation and mismatch detection
  3. Portable verification with public keys only (never private keys)
  4. Mandatory scenario hash binding
  5. Score-independent verification semantics (score < 1.0 with passing status)
  6. Explain run temporary file isolation with UUID
  7. SSE intrinsic _seq emission
  8. VerificationAuthority mandatory signature requirement
  9. Authoritative verdict execution
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from agentv_runtime.package import VerificationPackage
from eval_runner.console.routes.runs import _authoritative_verdict, run_bp, tail_file_generator
from eval_runner.console.routes.trust import trust_bp
from eval_runner.events import Event
from eval_runner.flight_recorder import FlightRecorderPlugin
from eval_runner.identity import IdentityService
from eval_runner.verifier import (
    TraceVerifier,
    VerificationAuthority,
    verify_trace_certificate,
)


@pytest.fixture
def isolated_vault(tmp_path, monkeypatch):
    """Sets up an isolated test project environment."""
    project_root = tmp_path / "project"
    run_log_dir = project_root / "runs"
    reports_dir = project_root / "reports"
    trust_root = project_root / ".aes" / "keys"

    run_log_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    trust_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", project_root)
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", run_log_dir)
    monkeypatch.setattr("eval_runner.config.REPORTS_DIR", reports_dir)
    monkeypatch.setattr("eval_runner.config.TRUST_ROOT", trust_root)

    IdentityService._provision_local_identity("system_id")
    IdentityService._provision_local_identity("test_signer")

    return {
        "project_root": project_root,
        "run_log_dir": run_log_dir,
        "reports_dir": reports_dir,
        "trust_root": trust_root,
    }


def test_flight_recorder_write_rejection_after_freeze(isolated_vault):
    """Verify FlightRecorderPlugin rejects event writes once a run is FINALIZING/SEALED."""
    recorder = FlightRecorderPlugin(log_dir=isolated_vault["run_log_dir"])
    run_id = "freeze-test-run-001"
    run_dir = isolated_vault["run_log_dir"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_file = run_dir / "run.jsonl"

    # 1. Normal write while RUNNING
    recorder.handle_event(Event("test_action", {"run_id": run_id, "data": "initial_event"}))
    recorder.flush()
    assert trace_file.exists()
    initial_content = trace_file.read_text(encoding="utf-8")
    assert "initial_event" in initial_content

    # 2. Freeze the run
    recorder.freeze_run(run_id)
    assert recorder.get_run_state(run_id) == "SEALED"

    # 3. Subsequent event writes are dropped/rejected
    recorder.handle_event(Event("test_action", {"run_id": run_id, "data": "post_freeze_mutation"}))
    recorder.flush()
    post_content = trace_file.read_text(encoding="utf-8")
    assert "post_freeze_mutation" not in post_content


def test_deterministic_evidence_root_derivation_and_mismatch(isolated_vault):
    """Verify sign_trace computes evidence_root_hash deterministically and fails on mismatch."""
    run_id = "evroot-test-run-001"
    run_dir = isolated_vault["run_log_dir"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_file = run_dir / "run.jsonl"

    evt1 = json.dumps({"event": "metric_evaluated", "metric": "safety", "passed": True, "_seq": 1})
    evt2 = json.dumps({"event": "run_end", "_seq": 2})
    trace_file.write_text(f"{evt1}\n{evt2}\n", encoding="utf-8")

    # 1. sign_trace without evidence_root_hash -> derives automatically
    manifest = TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        run_id=run_id,
        compliance_status="pass",
    )
    derived_root = manifest.get("evidence_root_hash")
    assert derived_root is not None
    assert derived_root.startswith("sha3_256:")

    # 2. sign_trace with mismatched evidence_root_hash -> fails closed
    bogus_root = "sha3_256:" + "0" * 64
    with pytest.raises(Exception) as exc_info:
        TraceVerifier.sign_trace(
            trace_path=str(trace_file),
            identity_id="test_signer",
            run_id=run_id,
            evidence_root_hash=bogus_root,
        )
    err_str = str(exc_info.value)
    assert "EvidenceRootMismatch" in err_str or "CERTIFICATION_FAILED" in err_str


def test_public_key_only_verification_without_private_key(isolated_vault, monkeypatch):
    """Verify verify_trace_certificate verifies using public keys only."""
    run_id = "pubkey-verify-run-001"
    run_dir = isolated_vault["run_log_dir"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_file = run_dir / "run.jsonl"
    trace_file.write_text(json.dumps({"event": "start", "_seq": 1}) + "\n", encoding="utf-8")

    manifest = TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        run_id=run_id,
        compliance_status="pass",
    )

    # Monkeypatch get_private_key to raise an error to prove it is NEVER called
    def _forbidden_get_private_key(*args, **kwargs):
        raise AssertionError("Private key accessed during verification! Must use public keys only.")

    target = "eval_runner.identity.IdentityService.get_private_key"
    monkeypatch.setattr(target, _forbidden_get_private_key)

    raw_trace_bytes = trace_file.read_bytes()
    res = verify_trace_certificate(run_id=run_id, trace_bytes=raw_trace_bytes, cert_data=manifest)
    assert res["verified"] is True
    assert res["signer_identity"] == "test_signer"


def test_scenario_hash_binding_enforcement(isolated_vault):
    """Verify verify_trace_certificate requires scenario_hash_match to certify."""
    run_id = "scenario-bound-run-001"
    run_dir = isolated_vault["run_log_dir"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_file = run_dir / "run.jsonl"
    trace_file.write_text(json.dumps({"event": "start", "_seq": 1}) + "\n", encoding="utf-8")

    manifest = TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        run_id=run_id,
        metadata={"scenario_hash": "sha3_256:correct_scen_hash_123"},
    )
    raw_trace_bytes = trace_file.read_bytes()

    # 1. Missing scenario data when scenario_hash is present -> verified = False
    res_missing = verify_trace_certificate(
        run_id=run_id, trace_bytes=raw_trace_bytes, cert_data=manifest
    )
    assert res_missing["verified"] is False
    assert any("Scenario binding verification required" in err for err in res_missing["errors"])


def test_public_verification_score_independence(isolated_vault):
    """Verify /v1/verify/<run_id> reports verified=True for a passing status with score < 1.0."""
    run_id = "score-indep-run-001"
    run_dir = isolated_vault["run_log_dir"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_file = run_dir / "run.jsonl"
    trace_file.write_text(json.dumps({"event": "start", "_seq": 1}) + "\n", encoding="utf-8")

    TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        run_id=run_id,
        compliance_status="pass",
        compliance_score=0.96,  # Non-perfect passing score
    )

    app = Flask(__name__)
    app.register_blueprint(trust_bp)
    client = app.test_client()

    resp = client.get(f"/api/v1/verify/{run_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["verified"] is True
    assert data["cryptographically_valid"] is True
    assert data["compliance_score"] == 0.96
    assert data["policy_compliant"] is True


def test_explain_run_temp_file_uuid_isolation(isolated_vault):
    """Verify explain_run uses UUID in temp filename to prevent collisions."""
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(run_bp, url_prefix="/api")
    client = app.test_client()

    master_log = isolated_vault["run_log_dir"] / "run.jsonl"
    evt = json.dumps({"event": "start", "run_id": "master-run-001", "_seq": 1})
    master_log.write_text(f"{evt}\n", encoding="utf-8")

    with client.session_transaction() as sess:
        sess["user"] = {"id": "tester", "roles": ["admin"]}

    with patch("eval_runner.console.auth_manager.get_auth_provider") as get_provider:
        provider = MagicMock()
        provider.has_permission.return_value = True
        get_provider.return_value = provider

        resp = client.get("/api/v1/explain/master-run-001")
        assert resp.status_code == 200
        # Verify no temp files remain lingering
        lingering = list(isolated_vault["run_log_dir"].glob("temp_explain_*"))
        assert len(lingering) == 0


def test_tail_file_generator_intrinsic_seq(isolated_vault):
    """Verify tail_file_generator streams frames preserving intrinsic event _seq."""
    run_id = "seq-test-run-001"
    run_dir = isolated_vault["run_log_dir"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_file = run_dir / "run.jsonl"

    evt1 = json.dumps({"event": "step_1", "_seq": 42})
    evt2 = json.dumps({"event": "run_end", "_seq": 43})
    trace_file.write_text(f"{evt1}\n{evt2}\n", encoding="utf-8")

    chunks = list(tail_file_generator(trace_file, run_id=run_id, last_event_id=0))
    emitted = "".join(chunks)
    assert '"_seq": 42' in emitted
    assert '"_seq": 43' in emitted
    assert "id: 1" in emitted
    assert "id: 2" in emitted


def test_verification_authority_default_require_signature():
    """Verify VerificationAuthority.verify_package enforces require_signature=True."""
    pkg = VerificationPackage(
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:abcd",
        manifest_id="manifest-001",
        manifest_hash="sha3_256:fedcba0987654321fedcba0987654321fedcba0987654321fedcba0987654321",
        execution_identity={"agent_id": "test_agent"},
        trace_hash="sha3_256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        trace_seal={"seal": "ok"},
        evidence_root_hash="sha3_256:1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"verdict": "PASS"},
        signature=None,  # Unsigned
    )

    res = VerificationAuthority.verify_package(pkg)
    assert res["verified"] is False
    assert any("UnsignedPackage" in f for f in res["failures"])


def test_authoritative_verdict_execution(isolated_vault):
    """Verify _authoritative_verdict runs full TraceVerifier verification."""
    run_id = "auth-verdict-run-001"
    run_dir = isolated_vault["run_log_dir"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_file = run_dir / "run.jsonl"
    trace_file.write_text(json.dumps({"event": "start", "_seq": 1}) + "\n", encoding="utf-8")

    # Before signing -> UNKNOWN
    assert _authoritative_verdict(run_id) == "UNKNOWN"

    # Sign trace without declared mode -> VERIFIED_PROVISIONAL
    TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        run_id=run_id,
        compliance_status="pass",
    )
    assert _authoritative_verdict(run_id) == "VERIFIED_PROVISIONAL"

    # Sign trace with declared non-provisional mode -> VERIFIED
    TraceVerifier.sign_trace(
        trace_path=str(trace_file),
        identity_id="test_signer",
        run_id=run_id,
        compliance_status="pass",
        execution_mode="live",
        provisional=False,
    )
    assert _authoritative_verdict(run_id) == "VERIFIED"

    # Tamper trace file -> FAILED_VERIFICATION
    trace_file.write_text("tampered_content\n", encoding="utf-8")
    assert _authoritative_verdict(run_id) == "FAILED_VERIFICATION"
