"""
tests/unit/core/test_certification_service_and_trust_boundary.py

Comprehensive test suite verifying the authoritative CertificationService domain service
and hardened trust boundary contracts:
1. Inconclusive evaluation outcome fails closed (cannot be overridden by caller).
2. Prior run_manifest.json is never used as source of truth (no circular trust).
3. Failed evaluation outcome produces a failure attestation, never a compliance pass.
4. Provisional/simulated execution modes fail closed against authoritative certification.
5. Verification independently verifies cryptographic validity and evaluation verdict.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.routes.trust import trust_bp
from eval_runner.identity import IdentityService
from eval_runner.services.certification import (
    CertificationService,
    execute_industrial_certification,
)


@pytest.fixture
def cert_vault(tmp_path, monkeypatch):
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
) -> tuple[Path, Path]:
    vault = runs_dir / run_id
    vault.mkdir(parents=True, exist_ok=True)
    trace = vault / "run.jsonl"
    with open(trace, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
    return vault, trace


def test_inconclusive_run_cannot_be_certified(cert_vault):
    """Missing or ambiguous terminal evaluation outcome must hard-fail certification."""
    run_id = "run-inconclusive-001"
    events = [
        {"event": "run_start", "execution_mode": "live", "data": {"execution_mode_declared": True}},
        {"event": "step_executed", "data": {"step": 1}},
    ]
    _create_trace(cert_vault["runs"], run_id, events)

    # Calling execute_industrial_certification without terminal outcome must raise ValueError
    with pytest.raises(ValueError, match="inconclusive outcome"):
        CertificationService.execute_industrial_certification(run_id=run_id)


def test_inconclusive_run_cannot_be_certified_with_caller_status_override(cert_vault):
    """Caller supplying status='pass' cannot bypass fail-closed inconclusive outcome check."""
    run_id = "run-inconclusive-override"
    events = [
        {"event": "run_start", "execution_mode": "live", "data": {"execution_mode_declared": True}},
        {"event": "step_executed", "data": {"step": 1}},
    ]
    _create_trace(cert_vault["runs"], run_id, events)

    with pytest.raises(ValueError, match="inconclusive outcome"):
        execute_industrial_certification(run_id=run_id, status="pass", score=1.0)


def test_previous_run_manifest_cannot_circularly_influence_certification(cert_vault):
    """A prior run_manifest.json with fake PASS status must NOT influence new certification."""
    run_id = "run-no-circular-trust"
    # Raw trace indicates an authoritative FAIL
    events = [
        {"event": "run_start", "execution_mode": "live"},
        {"event": "session_decision", "data": {"decision": "FAIL", "score": 0.2}},
        {"event": "run_end", "data": {"status": "FAILED", "score": 0.2}},
    ]
    vault, trace = _create_trace(cert_vault["runs"], run_id, events)

    # Write a malicious / stale manifest in the vault claiming "certified" and score 1.0
    stale_manifest = vault / "run_manifest.json"
    stale_manifest.write_text(
        json.dumps(
            {
                "compliance_status": "pass",
                "compliance_score": 1.0,
                "status": "certified",
            }
        ),
        encoding="utf-8",
    )

    # Certification must derive outcome from the trace, recognizing FAIL
    res = CertificationService.execute_industrial_certification(run_id=run_id)
    assert res["certified"] is False
    assert res["status"] == "attested_failed"
    assert res["compliance_status"] == "fail"
    assert res["score"] == 0.2


def test_failed_evaluation_cannot_produce_pass_certificate(cert_vault):
    """Even if caller asks for status='pass', a failed evaluation fails closed."""
    run_id = "run-fail-closed-test"
    events = [
        {"event": "run_start", "execution_mode": "live"},
        {"event": "evaluation_result", "data": {"status": "FAIL", "score": 0.0}},
        {"event": "run_end", "data": {"verdict": "FAIL"}},
    ]
    _create_trace(cert_vault["runs"], run_id, events)

    res = execute_industrial_certification(run_id=run_id, status="pass", score=1.0)
    assert res["certified"] is False
    assert res["status"] == "attested_failed"
    assert res["compliance_status"] == "fail"
    assert res["score"] == 0.0


def test_provisional_simulated_mode_rejected_for_authoritative_certification(cert_vault):
    """Simulated or undeclared provisional runs cannot issue authoritative certificates."""
    run_id = "run-simulated-provisional"
    events = [
        {"event": "run_start", "execution_mode": "simulated", "data": {"provisional": True}},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
        {"event": "run_end", "data": {"status": "PASSED"}},
    ]
    _create_trace(cert_vault["runs"], run_id, events)

    with pytest.raises(ValueError, match="is provisional"):
        execute_industrial_certification(run_id=run_id)


def test_passing_authoritative_run_certified_successfully(cert_vault):
    """Passing live run is properly certified with genuine signature."""
    run_id = "run-passing-live"
    events = [
        {"event": "run_start", "execution_mode": "live", "data": {"execution_mode_declared": True}},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
        {"event": "run_end", "data": {"status": "PASSED", "score": 1.0}},
    ]
    _create_trace(cert_vault["runs"], run_id, events)

    res = execute_industrial_certification(
        run_id=run_id,
        identity_id="system_id",
        policy_ref="NIST-AI-100",
    )
    assert res["certified"] is True
    assert res["status"] == "certified"
    assert res["compliance_status"] == "pass"
    assert res["score"] == 1.0
    assert "trace_hash" in res["manifest"]


def test_public_verification_endpoint_semantics(cert_vault):
    """GET /v1/verify/<run_id> independently reports cryptographic and evaluation compliance."""
    app = Flask(__name__)
    app.register_blueprint(trust_bp)

    client = app.test_client()

    run_id = "run-verify-endpoint"
    events = [
        {"event": "run_start", "execution_mode": "live"},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 0.98}},
        {"event": "run_end", "data": {"status": "PASSED", "score": 0.98}},
    ]
    _create_trace(cert_vault["runs"], run_id, events)

    execute_industrial_certification(run_id=run_id, identity_id="system_id")

    res = client.get(f"/api/v1/verify/{run_id}")
    assert res.status_code == 200
    data = res.get_json()
    assert data["verified"] is True
    assert data["cryptographically_valid"] is True
    assert data["evaluation_passed"] is True
    assert data["certificate_authoritative"] is True


def test_invalid_run_ids_rejected(cert_vault):
    """Verify invalid and path-traversal run IDs are rejected with ValueError."""
    for bad_id in ("", 123, "../escape", "run/nested", "run\\slashes"):
        with pytest.raises(ValueError, match="Invalid or unsafe run_id"):
            execute_industrial_certification(run_id=bad_id)  # type: ignore


def test_metadata_binding_with_corrupt_lines_and_attributes(cert_vault):
    """Verify metadata extraction extracts bound scenario and agent identity attributes."""
    run_id = "run-meta-binding"
    vault = cert_vault["runs"] / run_id
    vault.mkdir(parents=True, exist_ok=True)
    trace = vault / "run.jsonl"
    trace.write_text(
        '{"event": "run_start", "execution_mode": "live", '
        '"scenario_id": "scen_1", "agent_id": "ag_1"}\n'
        "\n"
        '{"event": "step_executed", "data": {"step": 1}}\n'
        '{"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}}\n'
        '{"event": "run_end", "data": {"status": "PASSED"}}\n',
        encoding="utf-8",
    )

    res = execute_industrial_certification(run_id=run_id, identity_id="system_id")
    assert res["certified"] is True
    assert res["manifest"]["metadata"]["scenario_id"] == "scen_1"
    assert res["manifest"]["metadata"]["agent_id"] == "ag_1"
