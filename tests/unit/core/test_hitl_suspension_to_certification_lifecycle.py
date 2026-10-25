"""
tests/unit/core/test_hitl_suspension_to_certification_lifecycle.py

Contract-Level Invariant Tests: Full-Lifecycle Suspension-to-Certification E2E.
Verifies the end-to-end cryptographic and runtime invariants across:
  1. Initial Execution Launch (execution_mode="live")
  2. Durable HITL Pause (RunSuspendedForApproval, PAUSED_FOR_APPROVAL)
  3. Execution Manifest Serialization Invariants (scope, canonical hash)
  4. Approval Store 4-Way Invariant Binding (manifest_id, scope, scope_digest)
  5. Approval Resolution & Resumption without Vault Collision
  6. Contiguous Monotonic Trace Appending & Single EvaluatorFinalizationRecord Emission
  7. Authoritative Certification Issuance (CertificationService.issue_certification)
  8. End-to-End Cryptographic Envelope Verification (TraceVerifier)
  9. Fail-Closed Invariant Protection against Serialization Drift or Tampering
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agentv_runtime.manifest import ExecutionManifest
from agentv_runtime.scope import ScopeToken
from eval_runner import config
from eval_runner.exceptions import RunSuspendedForApproval
from eval_runner.reference.approval_store import (
    get_default_approval_store,
    reset_default_approval_store,
)
from eval_runner.run_lifecycle import (
    RunLifecycleState,
    get_run_lifecycle_state,
)
from eval_runner.runner import DefaultRunner
from eval_runner.services.certification import (
    CertificationService,
    issue_certification,
)
from eval_runner.verifier import TraceVerifier


@pytest.fixture(autouse=True)
def isolated_lifecycle_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate runtime config, run vaults, and approval stores to clean temporary directories."""
    from agentv_runtime.discovery import reset_extensions

    reset_default_approval_store()
    reset_extensions()
    test_runs = tmp_path / "runs"
    test_runs.mkdir(parents=True, exist_ok=True)
    test_reports = tmp_path / "reports"
    test_reports.mkdir(parents=True, exist_ok=True)
    test_config = tmp_path / ".agentv"
    test_config.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "RUN_LOG_DIR", test_runs)
    monkeypatch.setattr(config, "REPORTS_DIR", test_reports)
    monkeypatch.setenv("AGENTV_CONFIG_DIR", str(test_config))
    monkeypatch.setenv("AGENTV_CLI_HITL_SUSPEND", "1")
    yield
    reset_default_approval_store()
    reset_extensions()


@pytest.fixture
def governance_scenario() -> dict:
    """Industrial-grade clinical scenario requiring human approval for high-risk action."""
    return {
        "id": "agentv-e2e-clinical-um-hitl",
        "version": "1.0.0",
        "description": "Adverse determination clinical governance evaluation with mandatory HITL",
        "environment": {"type": "local"},
        "metadata": {
            "execution_mode": "live",
            "org_id": "org_clinical_governance",
            "tenant_id": "tenant_payer_um",
            "environment": "production",
            "attribution": "Clinical AI Governance & Verification Team",
            "policies": ["interqual_lumbar_spine_v2", "hipaa_minimum_necessary"],
        },
        "workflow": [
            {
                "id": "physician_adverse_review",
                "name": "Physician Adverse Determination Review",
                "interaction_mode": "Manual_Approval",
                "tool": "record_clinical_determination",
                "params": {
                    "case_id": "AUTH-2026-UM-8891",
                    "determination": "DENIED_CONSERVATIVE_THERAPY_INCOMPLETE",
                },
                "success_criteria": [
                    {
                        "metric": "generic_accuracy",
                        "expected_outcome": (
                            "Clinical determination reviewed and approved by Medical Director: "
                            "Adverse notice issued."
                        ),
                        "threshold": 1.0,
                    }
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_full_lifecycle_suspension_to_certification_e2e(
    tmp_path: Path,
    governance_scenario: dict,
):
    """
    Contract Invariant: Full-Lifecycle Suspension-to-Certification E2E.
    Launches a live run, triggers PAUSED_FOR_APPROVAL, verifies physical manifest invariants,
    resolves the durable approval, resumes execution, generates finalization records,
    and issues a cryptographic certificate via CertificationService.issue_certification().
    """
    run_id = "run-e2e-suspension-to-cert-001"
    runs_dir = Path(config.RUN_LOG_DIR)
    vault_dir = runs_dir / run_id

    expected_scope = {
        "org_id": "org_clinical_governance",
        "tenant_id": "tenant_payer_um",
    }
    expected_digest = ScopeToken.from_tags(expected_scope).digest

    runner = DefaultRunner()

    # -----------------------------------------------------------------------
    # Step 1: Launch Execution -> Must Suspend for HITL Approval
    # -----------------------------------------------------------------------
    with pytest.raises(RunSuspendedForApproval) as exc_info:
        await runner.run(
            scenario=governance_scenario,
            run_id=run_id,
            attempts=1,
            metadata={
                "execution_mode": "live",
                "execution_mode_declared": True,
                "runtime_context": expected_scope,
            },
        )

    suspension = exc_info.value
    assert suspension.run_id == run_id
    assert suspension.task_id == "physician_adverse_review"
    assert bool(suspension.approval_token)
    assert len(suspension.approval_token) >= 16
    assert "Manual approval required" in suspension.prompt

    # -----------------------------------------------------------------------
    # Step 2: Invariant Check on Paused Vault & Execution Manifest
    # -----------------------------------------------------------------------
    assert (
        get_run_lifecycle_state(run_id, run_store=runner.run_store)
        == RunLifecycleState.PAUSED_FOR_APPROVAL
    )

    manifest_file = vault_dir / "execution_manifest.json"
    assert manifest_file.exists(), "execution_manifest.json must be written upfront before pause"

    manifest_bytes = manifest_file.read_text(encoding="utf-8")
    raw_manifest_dict = json.loads(manifest_bytes)

    # Invariant: Must NOT contain duplicate legacy field keys
    assert "scope" in raw_manifest_dict, "Canonical 'scope' must be serialized in manifest"
    assert "scope_tags" not in raw_manifest_dict, (
        "Duplicate 'scope_tags' field must NOT be stored in manifest JSON"
    )

    # Invariant: Deserialization via ExecutionManifest.from_dict must pass cleanly
    manifest = ExecutionManifest.from_dict(raw_manifest_dict)
    assert run_id in manifest.manifest_id
    assert manifest.scenario_id == governance_scenario["id"]
    assert manifest.scenario_version == governance_scenario["version"]
    assert manifest.scope == expected_scope
    assert manifest.scope_digest == expected_digest
    assert manifest.runtime_config.get("execution_mode") == "live"

    # Compute canonical manifest hash
    manifest_hash = manifest.compute_manifest_hash()
    assert manifest_hash.startswith("sha3_256:")

    # -----------------------------------------------------------------------
    # Step 3: Invariant Check on Durable Approval Store
    # -----------------------------------------------------------------------
    approval_store = get_default_approval_store()
    pending_request = approval_store.get_request(suspension.approval_token)
    assert pending_request is not None
    assert pending_request.status == "PENDING"
    assert pending_request.run_id == run_id
    assert pending_request.scope == expected_scope
    assert pending_request.scope_digest == expected_digest
    assert pending_request.manifest_id == manifest.manifest_id

    # -----------------------------------------------------------------------
    # Step 4: Resolve Approval & Resume Execution
    # -----------------------------------------------------------------------
    reason_text = (
        "InterQual 2026 Lumbar Spine Criteria 4.2.1 unmet; conservative therapy incomplete."
    )
    resolved_req = approval_store.resolve_request(
        approval_token=suspension.approval_token,
        decision="APPROVED",
        decided_by="dr_elizabeth_vance_md",
        decision_reason=reason_text,
        scope=ScopeToken.from_tags(expected_scope),
    )
    assert resolved_req.status == "APPROVED"

    # Resume the same run using the approved token
    approved_text = (
        "Clinical determination reviewed and approved by Medical Director: Adverse notice issued."
    )
    mock_agent_response = {
        "action": "final_answer",
        "content": approved_text,
    }

    with patch(
        "eval_runner.session.AgentAdapterRegistry.call_agent",
        AsyncMock(return_value=mock_agent_response),
    ):
        result = await runner.run(
            scenario=governance_scenario,
            run_id=run_id,
            attempts=1,
            resumption_token=suspension.approval_token,
            metadata={
                "execution_mode": "live",
                "execution_mode_declared": True,
                "runtime_context": expected_scope,
            },
        )

    assert result is not None
    assert result.successful_attempts == 1
    assert result.total_attempts == 1
    assert result.pass_at_k == 1.0

    # -----------------------------------------------------------------------
    # Step 5: Invariant Check on Post-Resume Monotonic Trace & Finalization
    # -----------------------------------------------------------------------
    trace_path = vault_dir / "run.jsonl"
    assert trace_path.exists()

    events = CertificationService.parse_trace_strict(trace_path, run_id=run_id)
    assert len(events) >= 6

    # Verify strict contiguity and monotonicity of sequence numbers
    seq_numbers = [event["_seq"] for event in events]
    assert seq_numbers == list(range(1, len(events) + 1)), "Sequence numbers must be contiguous"

    # Verify key lifecycle trace events
    event_names = [e.get("event") for e in events]
    assert "hitl_pause" in event_names
    assert "approval_created" in event_names
    assert "run_start" in event_names
    assert "run_end" in event_names

    # Verify authoritative EvaluatorFinalizationRecord was generated and signed
    fin_record = CertificationService.extract_finalization_record(trace_path)
    assert fin_record is not None
    assert fin_record.run_id == run_id
    assert fin_record.outcome == "pass"
    store_manifest = ExecutionManifest.from_dict(
        runner.run_store.get_manifest(run_id)["execution_manifest"]
    )
    assert fin_record.execution_manifest_hash == store_manifest.compute_manifest_hash()
    assert fin_record.scenario_hash == manifest.scenario_hash
    assert fin_record.evaluator_signature is not None

    # Verify run lifecycle state is OPEN after evaluation completes
    assert get_run_lifecycle_state(run_id, run_store=runner.run_store) == RunLifecycleState.OPEN

    # -----------------------------------------------------------------------
    # Step 6: Invoke CertificationService.issue_certification()
    # -----------------------------------------------------------------------
    # If any serialized field in execution_manifest.json or trace breaks the verifier,
    # this call will raise an exception and fail CI immediately.
    cert_res = CertificationService.issue_certification(run_id=run_id, run_store=runner.run_store)

    assert cert_res is not None
    assert cert_res["certified"] is True
    assert cert_res["certificate_issued"] is True
    assert cert_res["status"] == "certified"
    assert cert_res["compliance_status"] == "pass"
    assert cert_res["score"] == 1.0
    assert cert_res["run_id"] == run_id

    # Verify run lifecycle state is sealed post-certification
    assert get_run_lifecycle_state(run_id, run_store=runner.run_store) in (
        RunLifecycleState.FINALIZING,
        RunLifecycleState.SEALED,
    )

    # Verify top-level convenience alias parity
    assert issue_certification is not None

    # Verify verification certificate artifact written to vault sidecar and published reports
    sidecar_file = vault_dir / "run_manifest.json"
    assert sidecar_file.exists(), "Manifest sidecar must exist in run vault"

    vc_data = json.loads(sidecar_file.read_text(encoding="utf-8"))
    assert vc_data["compliance"]["status"] == "pass"
    assert vc_data["compliance"]["score"] == 1.0
    assert vc_data["execution_mode"] == "live"
    assert vc_data["verification_package"]["decision"]["status"] == "pass"
    assert vc_data["verification_package"]["decision"]["score"] == 1.0
    assert vc_data["verification_package"]["execution_identity"]["execution_mode"] == "live"
    assert vc_data["verification_package"]["signature"] is not None

    # -----------------------------------------------------------------------
    # Step 7: Authoritative TraceVerifier End-to-End Audit
    # -----------------------------------------------------------------------
    # Audit 1: Trace verification against manifest sidecar (trace hash, signature, ledger)
    manifest = runner.run_store.get_manifest(run_id)
    assert (
        TraceVerifier.verify_trace(
            runner.run_store.get_trace_bytes(run_id),
            manifest,
            run_store=runner.run_store,
            trace_only=True,
        )
        is True
    )

    # Audit 2: Authoritative certification package artifact verification
    vault_dir / "execution_manifest.json"
    canonical_manifest = ExecutionManifest.from_dict(
        runner.run_store.get_manifest(run_id)["execution_manifest"]
    )

    cert_audit = TraceVerifier.verify_certification_artifact(
        package=vc_data["verification_package"],
        raw_trace_bytes=(vault_dir / "run.jsonl").read_bytes(),
        canonical_manifest=canonical_manifest,
        scenario_data=governance_scenario,
    )
    assert cert_audit["verified"] is True, (
        f"Certification artifact rejected: {cert_audit.get('failures')}"
    )
    assert cert_audit["status"] == "CERTIFIED"
    assert cert_audit["failures"] == []
    assert cert_audit["package_hash"] == vc_data["package_hash"]


@pytest.mark.asyncio
async def test_lifecycle_fails_closed_on_unknown_serialized_field(
    tmp_path: Path,
    governance_scenario: dict,
):
    """
    Contract Invariant: Unknown/Rogue Serialized Fields in ExecutionManifest.
    Proves that if an unauthorized field (e.g. 'untrusted_carrier_data') is injected
    into execution_manifest.json, ExecutionManifest.from_dict fails closed with
    ExecutionManifestUnknownFields and CertificationService.issue_certification refuses to certify.
    """
    run_id = "run-e2e-unknown-field-fail-closed"
    runs_dir = Path(config.RUN_LOG_DIR)
    vault_dir = runs_dir / run_id

    runner = DefaultRunner()

    with pytest.raises(RunSuspendedForApproval) as exc_info:
        await runner.run(
            scenario=governance_scenario,
            run_id=run_id,
            attempts=1,
            metadata={"execution_mode": "live", "execution_mode_declared": True},
        )

    suspension = exc_info.value
    manifest_file = vault_dir / "execution_manifest.json"
    assert manifest_file.exists()

    # Inject an unknown/rogue serialized field into the manifest on disk and in provider sidecar
    m_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    m_data["untrusted_carrier_injection"] = "malicious_payload_or_stale_key"
    manifest_file.write_text(json.dumps(m_data, indent=2), encoding="utf-8")

    sidecar_file = vault_dir / "run_manifest.json"
    if sidecar_file.exists():
        sidecar_data = json.loads(sidecar_file.read_text(encoding="utf-8"))
        sidecar_data.setdefault("execution_manifest", {})["untrusted_carrier_injection"] = (
            "malicious_payload_or_stale_key"
        )
        sidecar_file.write_text(json.dumps(sidecar_data, indent=2), encoding="utf-8")

    # Invariant: ExecutionManifest.from_dict must reject unknown fields immediately
    with pytest.raises(ValueError, match="ExecutionManifestUnknownFields") as parse_err:
        ExecutionManifest.from_dict(m_data)
    assert "untrusted_carrier_injection" in str(parse_err.value)

    # Resolve approval to allow resumption attempt
    approval_store = get_default_approval_store()
    approval_store.resolve_request(
        approval_token=suspension.approval_token,
        decision="APPROVED",
        decided_by="auditor",
        decision_reason="Test approval",
    )

    # Invariant: a corrupted immutable manifest blocks resumption before any
    # further execution can append evidence to the run.
    with pytest.raises(RuntimeError, match="ResumptionManifestInvalid"):
        await runner.run(
            scenario=governance_scenario,
            run_id=run_id,
            attempts=1,
            resumption_token=suspension.approval_token,
            metadata={"execution_mode": "live", "execution_mode_declared": True},
        )

    # The malformed artifact was rejected both by the manifest parser and at
    # the earlier resumption boundary; no post-resume certification path may
    # be reached for this run.


@pytest.mark.asyncio
async def test_lifecycle_fails_closed_on_manifest_hash_mismatch(
    tmp_path: Path,
    governance_scenario: dict,
):
    """
    Contract Invariant: Manifest Hash Mismatch.
    Proves that if execution_manifest.json is modified after EvaluatorFinalizationRecord
    is cryptographically bound and signed, CertificationService.issue_certification
    detects the hash divergence and fails closed.
    """
    run_id = "run-e2e-hash-mismatch-fail-closed"
    runs_dir = Path(config.RUN_LOG_DIR)
    vault_dir = runs_dir / run_id

    runner = DefaultRunner()

    with pytest.raises(RunSuspendedForApproval) as exc_info:
        await runner.run(
            scenario=governance_scenario,
            run_id=run_id,
            attempts=1,
            metadata={"execution_mode": "live", "execution_mode_declared": True},
        )

    suspension = exc_info.value
    get_default_approval_store().resolve_request(
        approval_token=suspension.approval_token,
        decision="APPROVED",
        decided_by="auditor",
        decision_reason="Approved for hash tamper test",
    )

    clinical_pass_content = (
        "Clinical determination reviewed and approved by Medical Director: Adverse notice issued."
    )
    mock_agent = {"action": "final_answer", "content": clinical_pass_content}
    with patch(
        "eval_runner.session.AgentAdapterRegistry.call_agent",
        AsyncMock(return_value=mock_agent),
    ):
        await runner.run(
            scenario=governance_scenario,
            run_id=run_id,
            attempts=1,
            resumption_token=suspension.approval_token,
            metadata={"execution_mode": "live", "execution_mode_declared": True},
        )

    # Tamper with the physical manifest by changing a declared environment parameter
    manifest_file = vault_dir / "execution_manifest.json"
    m_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    m_data.setdefault("metadata", {})["tampered_flag"] = True
    manifest_file.write_text(json.dumps(m_data, indent=2), encoding="utf-8")

    sidecar_file = vault_dir / "run_manifest.json"
    if sidecar_file.exists():
        sidecar_data = json.loads(sidecar_file.read_text(encoding="utf-8"))
        sidecar_data.setdefault("execution_manifest", {}).setdefault("metadata", {})[
            "tampered_flag"
        ] = True
        sidecar_file.write_text(json.dumps(sidecar_data, indent=2), encoding="utf-8")

    # Invariant: CertificationService must fail closed on ManifestHashMismatch
    with pytest.raises(ValueError, match="ManifestHashMismatch"):
        CertificationService.issue_certification(run_id=run_id)
