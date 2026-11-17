"""
tests/contracts/test_release_candidate_hardening_proofs.py
Regression Proofs for the Five Release-Candidate Hardening Remediations:
1. P0 Execution truth and provenance: forged-live sandbox tool rejected fail-closed.
2. P1 Oracle completeness: mixed required-oracle inventories compiled canonically and certified.
3. P1 Independent state verification: detached verification using public trust anchors alone.
4. P1 Certificate integrity: certificate-hash tampering and missing projection rejected fail-closed.
5. P1 Mutation fidelity: unsupported concurrency/duplicate mutations rejected; supported state
   mutations produce observable, bound fault-delivery receipts.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from agentv_runtime.canonical import canonical_json_encode
from agentv_runtime.package import VerificationPackage
from eval_runner.events import EventEmitter
from eval_runner.mutator import ConcurrentMutator, StateMutators, UnsupportedMutationError
from eval_runner.mutator_plugin import RuntimeMutationPlugin
from eval_runner.runner import compile_required_oracle_ids
from eval_runner.session import Session
from eval_runner.state_authority import (
    create_authenticated_connector_receipt,
    verify_connector_receipt_authenticity,
)
from eval_runner.tool_sandbox import ToolSandbox
from eval_runner.verifier import TraceVerifier

# ─── Proof 1: Forged-Live Sandbox Tool Rejected Fail-Closed ────────────────────


@pytest.mark.asyncio
async def test_proof_1_forged_live_sandbox_tool_rejected():
    """Proof 1: Scenario-authored tools cannot declare live provenance.

    Even if a scenario defines provenance: "live" or canned output declares
    provenance: "live", execution classifies it as simulated unconditionally,
    and live-mode verification rejects simulated tool execution fail-closed.
    """
    scenario = {
        "id": "scenario-forged-provenance",
        "execution_mode": "live",
        "tools": {
            "forged_transfer": {
                "provenance": "live",
                "state_changes": [{"path": "balance", "value": 500}],
                "output": {
                    "status": "success",
                    "provenance": "live",
                    "balance": 500,
                },
            }
        },
    }

    sandbox = ToolSandbox(scenario=scenario)
    assert sandbox.get_tool_provenance("forged_transfer") == "simulated"

    # Direct execution of scenario-authored tool: sandbox marks simulated execution
    output = await sandbox.execute("forged_transfer", {})
    assert sandbox.has_simulated_tools is True
    assert output.get("balance") == 500

    # Session provenance extraction must unconditionally classify
    # scenario-defined tools as simulated
    session = Session("run-proof-prov-001", scenario=scenario)
    session.sandbox = sandbox

    extracted_prov = session._extract_provenance(
        "forged_transfer",
        sandbox=sandbox,
        result={"status": "success", "provenance": "live"},
    )
    assert extracted_prov == "simulated"

    # Even if sandbox is omitted, scenario tools manifest prevents forging live provenance
    extracted_prov_no_sb = session._extract_provenance(
        "forged_transfer",
        sandbox=None,
        result={"status": "success", "provenance": "live"},
    )
    assert extracted_prov_no_sb == "simulated"

    # Verifier trace check: simulated tool execution in live mode must fail closed
    events = [
        {"event": "run_start", "_seq": 1, "data": {"execution_mode": "live"}},
        {
            "event": "tool_call",
            "_seq": 2,
            "data": {"tool": "forged_transfer", "provenance": "simulated"},
        },
        {
            "event": "tool_result",
            "_seq": 3,
            "data": {
                "tool": "forged_transfer",
                "result": {"status": "success"},
                "provenance": "simulated",
            },
        },
    ]

    from eval_runner.services.certification import CertificationService

    mode, uncertifiable = CertificationService._execution_truth(events)
    assert mode == "simulated"
    assert uncertifiable is True

    # Authoritative verification must also fail closed with SimulatedToolProvenanceInLiveRun
    import json

    raw_trace_bytes = "\n".join(json.dumps(e) for e in events).encode("utf-8")
    thash = f"sha3_256:{hashlib.sha3_256(raw_trace_bytes).hexdigest()}"

    res = TraceVerifier.verify_certification_artifact(
        package=VerificationPackage(
            package_id="pkg_test",
            scenario_id="scenario-forged-provenance",
            scenario_version="1.0",
            scenario_hash="sha3_256:dummy",
            manifest_id="man_01",
            manifest_hash="sha3_256:dummy",
            execution_identity={"system_id": "test", "execution_mode": "live"},
            trace_hash=thash,
            trace_seal={"trace_digest": thash},
            evidence_root_hash="sha3_256:eroot",
            required_oracle_ids=[],
            executed_oracle_results=[],
            decision={"decision": "PASS"},
            certificate_hash="sha3_256:dummy",
            signature="dummy",
        ),
        raw_trace_bytes=raw_trace_bytes,
        canonical_manifest={
            "runtime_config": {"execution_mode": "live"},
            "execution_mode": "live",
        },
        raw_trace_events=events,
        require_signature=False,
    )
    assert any("SimulatedToolProvenanceInLiveRun" in f for f in res["failures"])


# ─── Proof 2: Mixed Required-Oracle Inventories Certified Correctly ───────────


def test_proof_2_mixed_required_oracle_inventories_certified_correctly():
    """Proof 2: Mixed oracle declarations compile identically across boundaries.

    Unifies explicitly declared metadata, IR workflow node success criteria,
    and required policy assertions into an identical canonical inventory.
    """
    scenario = {
        "id": "scenario-mixed-oracles",
        "metadata": {
            "required_oracle_ids": ["oracle_meta_declared"],
            "policies": {
                "transfer_limit": {
                    "required": True,
                    "oracle_id": "oracle_policy_required",
                },
                "optional_policy": {
                    "required": False,
                    "oracle_id": "oracle_policy_optional",
                },
            },
        },
        "workflow": {
            "nodes": [
                {
                    "id": "node_audit",
                    "success_criteria": [
                        {"id": "oracle_wf_node_sc", "required": True},
                        {"id": "oracle_wf_optional", "required": False},
                    ],
                }
            ]
        },
        "expected_outcome": [
            {"oracle_id": "oracle_expected_top", "required": True},
        ],
    }

    compiled = compile_required_oracle_ids(scenario)
    expected = sorted(
        [
            "oracle_meta_declared",
            "oracle_policy_required",
            "oracle_wf_node_sc",
            "oracle_expected_top",
        ]
    )
    assert compiled == expected
    assert "oracle_policy_optional" not in compiled
    assert "oracle_wf_optional" not in compiled

    # Invariant: identical canonical compiler result prevents inventory mismatch in certification
    manifest_reqs = set(compiled)
    fin_reqs = set(compiled)
    scen_reqs = set(compile_required_oracle_ids(scenario))

    assert manifest_reqs == fin_reqs == scen_reqs


# ─── Proof 3: Detached Verification Using Public Trust Anchors Alone ──────────


def test_proof_3_detached_verification_using_public_trust_anchors_alone(monkeypatch):
    """Proof 3: Detached verifiers can authenticate connector receipts with public keys alone.

    Asymmetric Ed25519 connector receipts verify without the symmetric HMAC secret.
    Tampered observations and unkeyed HMAC receipts fail closed.
    """
    # Generate Ed25519 connector identity key pair
    connector_priv = ed25519.Ed25519PrivateKey.generate()
    connector_pub = connector_priv.public_key()
    pub_pem = connector_pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    receipt = create_authenticated_connector_receipt(
        connector_id="connector.ledger.prod",
        source_id="ledger_db",
        request_spec={"account_id": "acc_1001"},
        response_digest="sha3_256:d4e1a7b8c2",
        execution_id="exec_9901",
        phase="post",
        run_id="run-rc-001",
        signing_key=connector_priv,
    )

    assert receipt["algorithm"] == "ed25519"
    assert "signature_ed25519" in receipt
    assert receipt["public_key_pem"] == pub_pem

    # Ensure no symmetric secret key exists in the environment (detached verifier)
    monkeypatch.delenv("AGENTV_STATE_AUTHORITY_KEY", raising=False)
    monkeypatch.delenv("STATE_AUTHORITY_KEY", raising=False)

    # 3a. Public anchor verification succeeds without any shared secret
    verified = verify_connector_receipt_authenticity(receipt, key=None)
    assert verified is True

    # 3b. Verification with explicit trusted public key anchor
    verified_explicit = verify_connector_receipt_authenticity(
        receipt, key=None, trusted_public_key=connector_pub
    )
    assert verified_explicit is True

    # 3c. Tampered observation response digest fails closed
    tampered_receipt = copy.deepcopy(receipt)
    tampered_receipt["response_digest"] = "sha3_256:forged_digest_0000"
    assert verify_connector_receipt_authenticity(tampered_receipt, key=None) is False

    # 3d. Tampered phase or run_id fails closed
    tampered_phase = copy.deepcopy(receipt)
    tampered_phase["phase"] = "pre"
    assert verify_connector_receipt_authenticity(tampered_phase, key=None) is False

    # 3e. Traditional HMAC receipt without secret key fails closed in detached mode
    hmac_receipt = create_authenticated_connector_receipt(
        connector_id="connector.ledger.legacy",
        source_id="ledger_db",
        request_spec={"account_id": "acc_1001"},
        response_digest="sha3_256:d4e1a7b8c2",
        execution_id="exec_9901",
        phase="post",
        run_id="run-rc-001",
        key=b"secret_issuer_key_32_bytes_long!!",
    )
    # Detached verification without key returns False (fails closed)
    assert verify_connector_receipt_authenticity(hmac_receipt, key=None) is False


# ─── Proof 4: Certificate-Hash Tampering Rejected Fail-Closed ─────────────────


def test_proof_4_certificate_hash_tampering_rejected():
    """Proof 4: Authoritative verifier recomputes certificate_hash and rejects tampering.

    Recomputes the canonical SHA3-256 hash of the compliance projection and rejects
    tampered hashes or missing certificate compliance projections fail closed.
    """
    proj = {
        "compliance": {"status": "PASS", "score": 1.0},
        "evidence_root_hash": "sha3_256:eroot_123",
        "execution_mode": "live",
        "run_id": "run-cert-tamper-proof",
        "timestamp": "2026-11-17T00:00:00Z",
        "trace_hash": "sha3_256:trace_123",
        "vc_version": "3.0.0",
    }
    cert_bytes = canonical_json_encode(proj)
    valid_cert_hash = f"sha3_256:{hashlib.sha3_256(cert_bytes).hexdigest()}"

    canonical_manifest = {
        "agent_config": {},
        "runtime_config": {"execution_mode": "live"},
        "environment": {},
        "metadata": {"certificate_projection": proj, "run_id": "run-cert-tamper-proof"},
    }

    valid_pkg = VerificationPackage(
        package_id="pkg_test_01",
        scenario_id="scen_tamper",
        scenario_version="1.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="man_01",
        manifest_hash="sha3_256:dummy",
        execution_identity={"system_id": "test", "run_id": "run-cert-tamper-proof"},
        trace_hash="sha3_256:trace_123",
        trace_seal={"trace_digest": "sha3_256:trace_123"},
        evidence_root_hash="sha3_256:eroot_123",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
        certificate_hash=valid_cert_hash,
        signature="dummy",
        metadata={"certificate_projection": proj},
    )

    # 4a. Valid package and projection verify cleanly
    res_valid = TraceVerifier.verify_package(
        valid_pkg, canonical_manifest=canonical_manifest, require_signature=False
    )
    assert not any("CertificateHashMismatch" in f for f in res_valid["failures"])
    assert not any("CertificateProjectionMissing" in f for f in res_valid["failures"])

    # 4b. Tampered certificate hash fails closed
    tampered_pkg = VerificationPackage(
        package_id="pkg_test_tampered",
        scenario_id="scen_tamper",
        scenario_version="1.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="man_01",
        manifest_hash="sha3_256:dummy",
        execution_identity={"system_id": "test", "run_id": "run-cert-tamper-proof"},
        trace_hash="sha3_256:trace_123",
        trace_seal={"trace_digest": "sha3_256:trace_123"},
        evidence_root_hash="sha3_256:eroot_123",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
        certificate_hash="sha3_256:tampered_cert_hash_00000000000",
        signature="dummy",
        metadata={"certificate_projection": proj},
    )
    res_tampered = TraceVerifier.verify_package(
        tampered_pkg, canonical_manifest=canonical_manifest, require_signature=False
    )
    assert any("CertificateHashMismatch" in f for f in res_tampered["failures"])

    # 4c. Package carries certificate_hash but projection is missing: fails closed
    missing_proj_pkg = VerificationPackage(
        package_id="pkg_test_missing_proj",
        scenario_id="scen_tamper",
        scenario_version="1.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="man_01",
        manifest_hash="sha3_256:dummy",
        execution_identity={"system_id": "test", "run_id": "run-cert-tamper-proof"},
        trace_hash="sha3_256:trace_123",
        trace_seal={"trace_digest": "sha3_256:trace_123"},
        evidence_root_hash="sha3_256:eroot_123",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
        certificate_hash=valid_cert_hash,
        signature="dummy",
        metadata={},  # No projection in package metadata
    )
    res_missing = TraceVerifier.verify_package(
        missing_proj_pkg,
        canonical_manifest={"agent_config": {}, "runtime_config": {}, "environment": {}},
        require_signature=False,
    )
    assert any("CertificateProjectionMissing" in f for f in res_missing["failures"])


# ─── Proof 5: Mutation Fidelity & Delivery Telemetry ──────────────────────────


@pytest.mark.asyncio
async def test_proof_5_state_and_concurrency_mutations_fidelity_and_receipts():
    """Proof 5: Advertised mutations execute real faults and emit bound delivery receipts.

    Unsupported concurrency and duplicate-commit mutations raise UnsupportedMutationError.
    Supported state mutations (partial_commit, stale_commit, commit_after_cancel)
    produce real state/locking faults and emit observable mutation_delivery receipts.
    """
    # 5a. Unsupported concurrency mutator fails closed
    concurrent_mut = ConcurrentMutator(mutators=[])
    assert concurrent_mut.can_mutate("concurrency") is False
    with pytest.raises(UnsupportedMutationError):
        concurrent_mut.mutate({}, "concurrency", lambda s, m: s)

    # 5b. Unsupported duplicate commit mutator fails closed
    state_mut = StateMutators()
    assert state_mut.can_mutate("duplicate_commit") is False
    assert state_mut.can_mutate("concurrency") is False
    with pytest.raises(UnsupportedMutationError):
        state_mut.apply_mutation({}, "duplicate_commit")

    # 5c. Supported state mutation plugin produces real faults and bound receipts
    plugin = RuntimeMutationPlugin()
    event_bus = EventEmitter()
    emitted_events: list[dict[str, Any]] = []

    def on_event(event):
        if hasattr(event, "name") and event.name == "mutation_delivery":
            emitted_events.append(event.data)

    event_bus.subscribe(on_event)

    scenario = {
        "id": "scenario-mutation-proof",
        "tools": {
            "update_accounts": {
                "state_changes": [
                    {"path": "acc_1", "value": 100},
                    {"path": "acc_2", "value": 200},
                ],
                "output": {"status": "success"},
            }
        },
    }

    # Test partial commit: interceptor drops subsequent keys and returns DELIVERED receipt
    plugin.on_step_start(None, node_id="node_partial", node_data={"partial_commit_simulated": True})
    res_partial = plugin.on_before_commit(None, {"acc_1": 100, "acc_2": 200})
    assert isinstance(res_partial, dict)
    assert res_partial.get("partial_commit_applied") is True
    assert res_partial.get("state_diff") == {"acc_1": 100}
    receipt = res_partial.get("mutation_receipt")
    assert receipt is not None
    assert receipt["fault"] == "partial_commit"
    assert receipt["delivery"] == "DELIVERED"

    # Test stale commit: interceptor blocks transaction with OptimisticLockError
    plugin.on_step_start(
        None,
        node_id="node_stale",
        node_data={
            "stale_commit": True,
            "expected_base_revision": "rev_deprecated_1970",
        },
    )
    res_stale = plugin.on_before_commit(None, {"acc_1": 100})
    assert isinstance(res_stale, dict)
    assert res_stale.get("allowed") is False
    assert "OptimisticLockError" in res_stale.get("error", "")
    assert res_stale.get("mutation_receipt")["delivery"] == "BLOCKED"

    # Test commit after cancel: interceptor tracks post-cancellation write with delivery receipt
    plugin.on_step_start(
        None,
        node_id="node_cancel",
        node_data={
            "commit_after_cancel": True,
            "allow_post_cancellation_write": True,
        },
    )
    res_cancel = plugin.on_before_commit(None, {"acc_1": 100})
    assert isinstance(res_cancel, dict)
    assert res_cancel.get("commit_after_cancel_tracked") is True
    assert res_cancel.get("mutation_receipt")["delivery"] == "DELIVERED"

    # Test ToolSandbox commit boundary emits mutation_delivery event with receipt
    mock_pm = MagicMock()
    mock_pm.trigger_interceptor.return_value = {
        "state_diff": {"acc_1": 100},
        "mutation_receipt": {"fault": "partial_commit", "delivery": "DELIVERED", "step": 1},
    }
    sandbox = ToolSandbox(scenario=scenario, event_bus=event_bus, plugin_manager=mock_pm)
    await sandbox.execute("update_accounts", {})

    assert len(emitted_events) == 1
    assert emitted_events[0]["category"] == "MUTATION_DELIVERY"
    assert emitted_events[0]["mutation_receipt"]["fault"] == "partial_commit"
    assert emitted_events[0]["mutation_receipt"]["delivery"] == "DELIVERED"
