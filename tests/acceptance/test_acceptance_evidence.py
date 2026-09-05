"""
tests.acceptance.test_acceptance_evidence
Independent Multi-Phase Evidence Acceptance Lifecycle Certification.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from tests.acceptance.support.assertions import (
    assert_certificate_artifacts,
    assert_gate_failed,
    assert_gate_passed,
    assert_sealed_run_immutable,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.mark.acceptance
@pytest.mark.acceptance_release
def test_acceptance_evidence_full_lifecycle(isolated_acceptance_env):
    """
    Certifies the complete independent evidence lifecycle:
    1. Scenario execution -> run.jsonl created
    2. Certification pipeline -> run_manifest.json and <run_id>_vc.json generated
    3. Vault sealing -> .sealed sentinel present and immutable
    4. Independent verification -> agentv verify and agentv gate succeed
    5. Sidecar evidence tampering -> agentv gate detects modification and rejects
    """
    env = isolated_acceptance_env
    runner = env["runner"]
    run_id = f"at-evid-{uuid.uuid4().hex[:8]}"

    scenario_path = (
        REPO_ROOT / "industries" / "finance" / "scenarios" / "unauthorized_transfer.json"
    )
    agent_path = (
        REPO_ROOT / "tests" / "acceptance" / "fixtures" / "agents" / "compliant_transfer_agent.py"
    )

    # Phase 1: Scenario execution
    run_res = runner.run(
        scenario_path=scenario_path,
        agent=str(agent_path),
        protocol="local",
        run_id=run_id,
        run_log_dir=env["runs_dir"],
    )
    assert run_res.exit_code == 0, f"Scenario execution failed: {run_res.stderr}"

    trace_file = env["runs_dir"] / run_id / "run.jsonl"
    assert trace_file.exists() and trace_file.stat().st_size > 0

    # Phase 2: Transactional Certification
    cert_res = runner.certify(run_id=run_id)
    assert cert_res.exit_code == 0, f"Certification failed: {cert_res.stderr}"

    # Phase 3: Artifact and Vault Immutability Assertions
    artifacts = assert_certificate_artifacts(
        run_id=run_id,
        repo_root=REPO_ROOT,
        custom_run_dir=env["runs_dir"],
        custom_reports_dir=env["reports_dir"],
    )
    assert_sealed_run_immutable(artifacts.run_vault_dir)

    # Phase 4: Independent Verification via CLI
    manifest_file = env["runs_dir"] / run_id / "run_manifest.json"
    verify_res = runner.verify(
        trace_path=trace_file,
        manifest_path=manifest_file,
        verify_ledger=True,
    )
    assert verify_res.exit_code == 0, f"Verify CLI failed: {verify_res.stderr}"

    gate_res = runner.gate(run_id=run_id, verify_ledger=True)
    assert_gate_passed(gate_res)

    # Phase 5: Tamper Detection (Modify Manifest and Certificate)
    original_manifest = manifest_file.read_text(encoding="utf-8")
    manifest_data = json.loads(original_manifest)
    manifest_data["trace_hash"] = "0" * 64
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    vc_file = env["reports_dir"] / "certificates" / f"{run_id}_vc.json"
    if vc_file.exists():
        vc_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    # Phase 6: Independent Verification Fails after Tamper
    tampered_gate_res = runner.gate(run_id=run_id, verify_ledger=True)
    assert_gate_failed(tampered_gate_res)
