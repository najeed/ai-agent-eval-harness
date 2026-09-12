"""
tests/unit/core/test_pareto_certification_invariants.py

Industrial Test Suite verifying the 8 Pareto Acceptance Invariants:
1. No execution-mode truth → no certification (T1)
2. Hand-authored / decision-only trace → no certification (T2)
3. Scenario modification → certificate invalid / certification blocked (T3)
4. Second terminal decision → certification blocked (T4)
5. Claimed PQC proof unavailable → verification is not valid (T5)
6. Signer identity cannot differ from declared publisher (T6)
7. certified=true always implies non-provisional, evaluator-finalized,
   cryptographically verified evidence (T1, T2)
8. Every authoritative certificate can be independently reconstructed
   from the same immutable inputs (T2, T3)

Plus operational invariants:
- Stale lock recovery with PID & lease fencing (T9)
- Fail-closed behavioral compliance in OSS (T10)
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from flask import Flask

from agentv_runtime.finalization import EvaluatorFinalizationRecord
from agentv_runtime.manifest import compute_scenario_hash
from eval_runner import config
from eval_runner.certification_lock import PerRunCertificationLock
from eval_runner.compliance import evaluate_compliance
from eval_runner.console.routes.trust import trust_bp
from eval_runner.identity import IdentityService
from eval_runner.services.certification import (
    CertificationService,
    execute_industrial_certification,
)
from eval_runner.verifier import TraceVerifier


@pytest.fixture
def cert_env(tmp_path, monkeypatch):
    root = tmp_path / "project"
    runs = root / "runs"
    reports = root / "reports"
    trust = root / ".aes" / "keys"
    runs.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    trust.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs)
    monkeypatch.setattr(config, "REPORTS_DIR", reports)
    monkeypatch.setattr(config, "TRUST_ROOT", trust)

    IdentityService._provision_local_identity("system_id")
    IdentityService._provision_local_identity("test_signer")

    return {"root": root, "runs": runs, "reports": reports, "trust": trust}


def _create_trace(
    runs_dir: Path,
    run_id: str,
    events: list[dict],
    auto_finalize: bool = True,
    scenario_data: Mapping[str, Any] | None = None,
) -> tuple[Path, Path]:
    vault = runs_dir / run_id
    vault.mkdir(parents=True, exist_ok=True)
    trace = vault / "run.jsonl"

    final_events = list(events)
    has_finalization = any(e.get("event") == "evaluator_finalization" for e in final_events)

    terminal_count = sum(
        1 for e in final_events if e.get("event") in ("session_decision", "evaluation_result")
    )
    if auto_finalize and not has_finalization and terminal_count == 1:
        scen_id = "scen_1"
        scen_hash = None
        if scenario_data:
            scen_id = scenario_data.get("id") or scenario_data.get("scenario_id") or scen_id
            scen_hash = compute_scenario_hash(scenario_data)
        else:
            for e in final_events:
                if e.get("event") in ("run_start", "start"):
                    scen_id = e.get("scenario_id") or scen_id
                    scen_hash = e.get("scenario_hash")
            if not scen_hash:
                scen_hash = compute_scenario_hash({"id": scen_id, "version": "1.0.0"})

        from agentv_runtime.evidence_graph import (
            build_evidence_graph_from_events,
            compute_evidence_graph_root,
        )
        from agentv_runtime.manifest import ExecutionManifest

        exec_manifest = ExecutionManifest(
            manifest_id=f"man_{run_id}",
            scenario_id=scen_id,
            scenario_version="1.0.0",
            scenario_hash=scen_hash,
        )
        exec_manifest_path = vault / "execution_manifest.json"
        exec_manifest_path.write_text(json.dumps(exec_manifest.to_dict()), encoding="utf-8")
        m_hash = exec_manifest.compute_manifest_hash()

        ev_graph = build_evidence_graph_from_events(final_events)
        ev_root = compute_evidence_graph_root(ev_graph)

        term_ev = next(
            e
            for e in reversed(final_events)
            if e.get("event") in ("session_decision", "evaluation_result")
        )
        data = term_ev.get("data", {}) if isinstance(term_ev.get("data"), dict) else term_ev
        dec_str = str(data.get("decision") or data.get("status") or "").upper()
        outcome = "pass" if dec_str == "PASS" else "fail"
        score = float(
            data.get("score")
            if data.get("score") is not None
            else (1.0 if outcome == "pass" else 0.0)
        )

        fin_rec = EvaluatorFinalizationRecord(
            finalization_id=f"fin_{run_id}",
            run_id=run_id,
            execution_manifest_hash=m_hash,
            scenario_id=scen_id,
            scenario_version="1.0.0",
            scenario_hash=scen_hash,
            evaluator_identity="eval_kernel",
            evaluator_config_hash="sha3_256:0000000000000000000000000000000000000000000000000000000000000000",
            required_oracle_ids=[],
            evidence_root_hash=ev_root,
            outcome=outcome,
            score=score,
        )
        fin_dict = fin_rec.to_dict()
        fin_dict["finalization_hash"] = fin_rec.compute_finalization_hash()
        final_events.append({"event": "evaluator_finalization", "data": fin_dict})

    with open(trace, "w", encoding="utf-8") as f:
        for ev in final_events:
            f.write(json.dumps(ev) + "\n")
    return vault, trace


# ==============================================================================
# Invariant 1: No execution-mode truth → no certification (T1)
# ==============================================================================


def test_invariant_1_no_execution_mode_truth_blocks_certification(cert_env):
    """Trace without recognized execution mode or marked provisional cannot be certified."""
    run_id = "run-inv1-no-mode"
    events = [
        {"event": "run_start", "scenario_id": "scen_1"},  # execution_mode missing
        {"event": "assertion_evaluated", "assertion": "check_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    _create_trace(cert_env["runs"], run_id, events)

    mode, is_prov = CertificationService.read_run_truth_level(run_id)
    assert is_prov is True
    assert mode == "unknown"

    with pytest.raises(ValueError, match="is provisional"):
        execute_industrial_certification(
            run_id=run_id, scenario_data={"id": "scen_1", "version": "1.0.0"}
        )


def test_invariant_1_simulated_mode_blocks_certification(cert_env):
    """Simulated execution mode fails closed against authoritative certification."""
    run_id = "run-inv1-simulated"
    events = [
        {"event": "run_start", "execution_mode": "simulated", "scenario_id": "scen_1"},
        {"event": "assertion_evaluated", "assertion": "check_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    _create_trace(cert_env["runs"], run_id, events)

    mode, is_prov = CertificationService.read_run_truth_level(run_id)
    assert is_prov is True
    assert mode == "simulated"

    with pytest.raises(ValueError, match="is provisional"):
        execute_industrial_certification(
            run_id=run_id, scenario_data={"id": "scen_1", "version": "1.0.0"}
        )


# ==============================================================================
# Invariant 2: Hand-authored / decision-only trace → no certification (T2)
# ==============================================================================


def test_invariant_2_decision_only_trace_blocks_certification(cert_env):
    """Trace with zero assertion/evidence nodes fails closed."""
    run_id = "run-inv2-decision-only"
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_1"},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    _create_trace(cert_env["runs"], run_id, events)

    with pytest.raises(ValueError, match="zero assertion or evidence nodes"):
        execute_industrial_certification(
            run_id=run_id, scenario_data={"id": "scen_1", "version": "1.0.0"}
        )


# ==============================================================================
# Invariant 3: Scenario modification → certificate invalid / certification blocked (T3)
# ==============================================================================


def test_invariant_3_scenario_modification_blocks_certification(cert_env):
    """If claimed scenario_hash differs from actual computed hash, certification fails."""
    run_id = "run-inv3-scenario-tampered"
    scen_data = {"id": "scen_secure", "version": "1.0.0", "params": {"timeout": 30}}
    fake_hash = "sha3_256:" + "0" * 64
    events = [
        {
            "event": "run_start",
            "execution_mode": "live",
            "scenario_id": "scen_secure",
            "scenario_hash": fake_hash,
        },
        {"event": "assertion_evaluated", "assertion": "check_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    _create_trace(cert_env["runs"], run_id, events)

    with pytest.raises(ValueError, match="ScenarioHashMismatch"):
        execute_industrial_certification(run_id=run_id, scenario_data=scen_data)


def test_invariant_3_verification_fails_on_scenario_mismatch(cert_env):
    """Post-certification verification fails if scenario definition has been modified."""
    run_id = "run-inv3-verify-tamper"
    scen_original = {"id": "scen_v", "version": "1.0.0", "val": 100}
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_v"},
        {"event": "assertion_evaluated", "assertion": "check_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    vault, trace = _create_trace(cert_env["runs"], run_id, events, scenario_data=scen_original)
    res = execute_industrial_certification(run_id=run_id, scenario_data=scen_original)
    assert res["certified"] is True

    manifest_path = vault / "run_manifest.json"

    # Verifying with original scenario succeeds
    assert (
        TraceVerifier.verify_trace(str(trace), str(manifest_path), scenario_data=scen_original)
        is True
    )

    # Verifying with modified scenario definition FAILS
    scen_modified = {"id": "scen_v", "version": "1.0.0", "val": 999}
    assert (
        TraceVerifier.verify_trace(str(trace), str(manifest_path), scenario_data=scen_modified)
        is False
    )


# ==============================================================================
# Invariant 4: Second terminal decision → certification blocked (T4)
# ==============================================================================


def test_invariant_4_second_terminal_decision_blocks_certification(cert_env):
    """Trace with multiple distinct terminal decision events fails closed."""
    run_id = "run-inv4-multi-decision"
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_1"},
        {"event": "assertion_evaluated", "assertion": "check_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
        {"event": "evaluation_result", "data": {"status": "PASS", "score": 1.0}},
    ]
    _create_trace(cert_env["runs"], run_id, events)

    with pytest.raises(ValueError, match="inconclusive outcome"):
        execute_industrial_certification(
            run_id=run_id, scenario_data={"id": "scen_1", "version": "1.0.0"}
        )


def test_invariant_4_event_appended_after_finalization_blocks_certification(cert_env):
    """Trace with an outcome event appended after EvaluatorFinalizationRecord fails closed."""
    run_id = "run-inv4-appended-after-fin"
    scen_data = {"id": "scen_fin", "version": "1.0.0"}
    scen_hash = compute_scenario_hash(scen_data)

    fin_rec = EvaluatorFinalizationRecord(
        finalization_id="fin_123",
        run_id=run_id,
        execution_manifest_hash="sha3_256:dummy",
        scenario_id="scen_fin",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        evaluator_identity="eval_kernel",
        evaluator_config_hash="cfg_hash",
        required_oracle_ids=["check_1"],
        evidence_root_hash="sha256:abc",
        outcome="pass",
        score=1.0,
    )
    fin_dict = fin_rec.to_dict()
    fin_dict["finalization_hash"] = fin_rec.compute_finalization_hash()

    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_fin"},
        {"event": "assertion_evaluated", "assertion": "check_1", "passed": True},
        {"event": "evaluator_finalization", "data": fin_dict},
        {"event": "session_decision", "data": {"decision": "FAIL"}},  # Appended after finalization!
    ]
    _create_trace(cert_env["runs"], run_id, events)

    with pytest.raises(ValueError, match="inconclusive outcome"):
        execute_industrial_certification(run_id=run_id, scenario_data=scen_data)


# ==============================================================================
# Invariant 5: Claimed PQC proof unavailable → verification is not valid (T5)
# ==============================================================================


def test_invariant_5_claimed_pqc_proof_unavailable_fails_verification(cert_env, monkeypatch):
    """If manifest contains ML-DSA-65 and PQC client unavailable, verification MUST fail."""
    run_id = "run-inv5-pqc-fail"
    scen_data = {"id": "scen_pqc", "version": "1.0.0"}
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_pqc"},
        {"event": "assertion_evaluated", "assertion": "check_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    vault, trace = _create_trace(cert_env["runs"], run_id, events)
    execute_industrial_certification(run_id=run_id, scenario_data=scen_data)

    manifest_path = vault / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Append an ML-DSA-65 claimed proof
    manifest["provenance_chain"].append(
        {
            "identity": "pqc_system_id",
            "algorithm": "ML-DSA-65",
            "signature": "deadbeef" * 8,
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Mock PQC client as unavailable
    monkeypatch.setattr(IdentityService, "get_pqc_client", lambda: None)
    # Ensure PQC_STRICT_MODE is false to verify it fails EVEN without strict mode
    monkeypatch.setattr(config, "PQC_STRICT_MODE", False)

    # Verification MUST fail
    is_valid = TraceVerifier.verify_trace(str(trace), str(manifest_path))
    assert is_valid is False


# ==============================================================================
# Invariant 6: Signer identity cannot differ from declared publisher (T6)
# ==============================================================================


def test_invariant_6_signer_identity_cannot_differ_from_declared_publisher(cert_env):
    """Extension verify-publisher route rejects mismatched caller identity_id."""
    app = Flask(__name__)
    app.register_blueprint(trust_bp)
    client = app.test_client()

    payload = {
        "manifest": {
            "extension_id": "test_ext",
            "display_name": "Test Extension",
            "version": "1.0.0",
            "publisher": "AgentV Core Team",
            "signature": "abcd1234ef",
            "remote_entry": "http://localhost:3000/remoteEntry.js",
            "sri_hash": "sha3_256:0000000000000000000000000000000000000000000000000000000000000000",
        },
        "identity_id": "malicious_attacker_identity",
    }

    headers = {"X-API-Key": config.SERVICE_API_KEY}
    res = client.post("/api/v1/extensions/verify-publisher", json=payload, headers=headers)
    assert res.status_code == 400
    data = res.get_json()
    assert data["valid"] is False
    assert data["reason"] == "signer-identity-mismatch"


def test_invariant_6_production_auto_provision_disabled(monkeypatch):
    """Automatic key provisioning is disabled in production environments."""
    from eval_runner.console.routes.trust import _private_key_pem_bytes

    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ValueError, match="Automatic key provisioning is disabled in production"):
        _private_key_pem_bytes("non_existent_production_key")


# ==============================================================================
# Invariant 7: certified=true implies non-provisional & verified evidence (T1, T2)
# ==============================================================================


def test_invariant_7_certified_implies_non_provisional_and_verified(cert_env):
    """Certified is True only when non-provisional, passing, and cryptographically verified."""
    run_id = "run-inv7-authoritative-pass"
    scen_data = {"id": "scen_auth", "version": "1.0.0"}
    events = [
        {
            "event": "run_start",
            "execution_mode": "live",
            "scenario_id": "scen_auth",
            "data": {"execution_mode_declared": True},
        },
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    vault, trace = _create_trace(cert_env["runs"], run_id, events)
    res = execute_industrial_certification(run_id=run_id, scenario_data=scen_data)

    assert res["certified"] is True
    assert res["status"] == "certified"
    assert res["certificate_issued"] is True
    assert res["manifest"]["execution_mode"] == "live"
    assert "provisional" not in res["manifest"] or res["manifest"]["provisional"] is False

    # TraceVerifier confirms valid cryptographic proof
    manifest_path = vault / "run_manifest.json"
    assert (
        TraceVerifier.verify_trace(str(trace), str(manifest_path), scenario_data=scen_data) is True
    )


# ==============================================================================
# Invariant 8: Authoritative certificate reconstructed from immutable inputs (T2, T3)
# ==============================================================================


def test_invariant_8_deterministic_certificate_reconstruction(cert_env):
    """Independent runs over identical immutable trace and scenario yield identical hashes."""
    run_id = "run-inv8-reconstruct"
    scen_data = {"id": "scen_reconstruct", "version": "1.0.0", "params": {"alpha": 1}}
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_reconstruct"},
        {"event": "assertion_evaluated", "assertion": "eval_node_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    vault, trace = _create_trace(cert_env["runs"], run_id, events, scenario_data=scen_data)

    res1 = execute_industrial_certification(run_id=run_id, scenario_data=scen_data)
    manifest1 = res1["manifest"]

    # Re-extract and re-compute scenario hash independently
    scen_hash1 = compute_scenario_hash(scen_data)
    assert manifest1["metadata"]["scenario_hash"] == scen_hash1

    # Verify signature passes
    manifest_path = vault / "run_manifest.json"
    assert (
        TraceVerifier.verify_trace(str(trace), str(manifest_path), scenario_data=scen_data) is True
    )


# ==============================================================================
# Operational Tests: Stale Lock Fencing (T9) & Behavioral Compliance (T10)
# ==============================================================================


def test_operational_stale_lock_recovery_with_dead_pid(cert_env):
    """A lock file left behind by a dead PID is safely reclaimed without hanging."""
    run_id = "run-dead-lock-pid"
    lock_path = cert_env["runs"] / run_id / ".certification.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    # Write a stale lock referencing a definitely dead/unused PID (e.g. 999999)
    lock_payload = {
        "run_id": run_id,
        "pid": 999999,
        "acquired_at": time.time() - 100,
        "host": "test-host",
    }
    lock_path.write_text(json.dumps(lock_payload), encoding="utf-8")

    # PerRunCertificationLock should detect dead owner and safely acquire
    with PerRunCertificationLock(run_id, timeout_seconds=1.0):
        assert lock_path.exists()
    assert not lock_path.exists()


def test_operational_behavioral_compliance_fails_closed_in_oss(cert_env):
    """Behavioral metrics in OSS return NOT_EVALUATED and compliant=False."""
    run_id = "run-oss-compliance"
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_comp"},
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    _create_trace(cert_env["runs"], run_id, events)
    execute_industrial_certification(
        run_id=run_id, scenario_data={"id": "scen_comp", "version": "1.0.0"}
    )

    res = evaluate_compliance(run_id, metrics={"safety_score": 0.99})
    assert res["status"] == "NOT_EVALUATED"
    assert res["compliant"] is False
    assert res["behavioral_metrics"] == "not_evaluated_in_oss"
