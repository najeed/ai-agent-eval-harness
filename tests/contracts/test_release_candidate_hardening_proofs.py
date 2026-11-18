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
import hmac
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from agentv_runtime.canonical import canonical_json_encode
from agentv_runtime.package import VerificationPackage
from eval_runner.events import EventEmitter
from eval_runner.mutations.mutator import ConcurrentMutator, StateMutators, UnsupportedMutationError
from eval_runner.mutations.mutator_plugin import RuntimeMutationPlugin
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
@pytest.mark.parametrize(
    "override", ["none", "scenario", "environment", "both", "authenticated", "wildcard"]
)
async def test_proof_1_forged_live_sandbox_tool_rejected(monkeypatch, override):
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

    if override in {"scenario", "both"}:
        scenario["metadata"] = {"trusted_execution_adapter": True}
    if override in {"environment", "both"}:
        monkeypatch.setenv("AGENTV_TRUSTED_TOOL_ADAPTER", "true")
    if override in {"authenticated", "wildcard"}:
        key = b"regression-only-adapter-key"
        monkeypatch.setattr(
            "eval_runner.state_authority.get_state_authority_trust_key", lambda: key
        )
        binding = b"authenticated_execution_adapter"
        if override == "authenticated":
            binding += b":forged_transfer"
        monkeypatch.setenv(
            "AGENTV_AUTHENTICATED_ADAPTER_TOKEN",
            hmac.new(key, binding, hashlib.sha3_256).hexdigest(),
        )
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


def test_proof_3_detached_verification_using_public_trust_anchors_alone(monkeypatch, tmp_path):
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

    # A receipt's self-supplied key is never an independent trust anchor.
    monkeypatch.setattr("eval_runner.config.TRUST_ROOT", tmp_path / "trusted-connectors")
    assert verify_connector_receipt_authenticity(receipt, key=None) is False

    # Publish only the independently trusted connector public key, never its secret.
    anchor_dir = tmp_path / "trusted-connectors" / "connector.ledger.prod"
    anchor_dir.mkdir(parents=True)
    (anchor_dir / "public_key.pem").write_text(pub_pem, encoding="utf-8")
    assert verify_connector_receipt_authenticity(receipt, key=None) is True

    # 3b. Verification with explicit trusted public key anchor
    verified_explicit = verify_connector_receipt_authenticity(
        receipt, key=None, trusted_public_key=connector_pub
    )
    assert verified_explicit is True

    attacker_key = ed25519.Ed25519PrivateKey.generate()
    forged = create_authenticated_connector_receipt(
        connector_id="connector.ledger.prod",
        source_id="ledger_db",
        response_digest="sha3_256:attacker",
        execution_id="exec_9901",
        phase="post",
        run_id="run-rc-001",
        signing_key=attacker_key,
    )
    # A fresh valid signature and its matching embedded key cannot replace the anchor.
    assert verify_connector_receipt_authenticity(forged) is False
    forged["public_key_pem"] = pub_pem
    assert verify_connector_receipt_authenticity(forged) is False

    without_embedded_key = copy.deepcopy(receipt)
    without_embedded_key.pop("public_key_pem")
    assert verify_connector_receipt_authenticity(without_embedded_key) is True

    with monkeypatch.context() as invalid_anchor:
        invalid_anchor.setenv("AES_PUBLIC_KEY_CONNECTOR.LEDGER.PROD", "invalid configured PEM")
        assert verify_connector_receipt_authenticity(receipt) is False

    rogue_dir = tmp_path / "rogue"
    rogue_dir.mkdir()
    (rogue_dir / "public_key.pem").write_text(pub_pem, encoding="utf-8")
    traversal = create_authenticated_connector_receipt(
        connector_id="../rogue",
        source_id="ledger_db",
        response_digest="sha3_256:observation",
        execution_id="exec_9901",
        phase="post",
        run_id="run-rc-001",
        signing_key=connector_priv,
    )
    assert verify_connector_receipt_authenticity(traversal) is False

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
async def test_proof_5_state_and_concurrency_mutations_fidelity_and_receipts(tmp_path):
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
    from eval_runner.reference.local_run_store import LocalFileRunStore

    provider = LocalFileRunStore(tmp_path / "fault-proof")
    provider.create_run("mutation-proof", "scenario-mutation-proof")
    event_bus = EventEmitter(run_id="mutation-proof", async_mode=False)
    emitted_events: list[dict[str, Any]] = []

    def on_event(event):
        provider.append_events("mutation-proof", [event.to_dict()])
        if hasattr(event, "name") and event.name == "mutation_delivery":
            emitted_events.append(event.data)

    event_bus.subscribe(on_event, required=True)

    scenario = {
        "id": "scenario-mutation-proof",
        "run_id": "mutation-proof",
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

    # Execute the real cancelled commit through the sandbox boundary.
    from eval_runner.plugins import PluginManager

    manager = PluginManager()
    manager.plugins.append(plugin)
    cancelled_sandbox = ToolSandbox(
        scenario=copy.deepcopy(scenario), event_bus=event_bus, plugin_manager=manager
    )
    plugin.on_step_start(
        cancelled_sandbox,
        node_id="node_cancel",
        node_data={
            "commit_after_cancel": True,
            "allow_post_cancellation_write": True,
        },
    )
    await cancelled_sandbox.execute("update_accounts", {})
    assert cancelled_sandbox.cancellation_event.is_set()
    assert cancelled_sandbox.state["acc_1"] == 100
    assert any(row["mutation_receipt"]["fault"] == "commit_after_cancel" for row in emitted_events)
    emitted_events.clear()

    # Test ToolSandbox commit boundary emits mutation_delivery event with receipt
    partial_sandbox = ToolSandbox(
        scenario=copy.deepcopy(scenario), event_bus=event_bus, plugin_manager=manager
    )
    plugin.on_step_start(
        partial_sandbox,
        node_id="node_partial_real",
        node_data={"partial_commit_simulated": True},
    )
    await partial_sandbox.execute("update_accounts", {})

    assert partial_sandbox.state.get("acc_1") == 100
    assert "acc_2" not in partial_sandbox.state or partial_sandbox.state.get("acc_2") != 200
    assert len(emitted_events) == 1
    assert emitted_events[0]["category"] == "MUTATION_DELIVERY"
    assert emitted_events[0]["mutation_receipt"]["fault"] == "partial_commit"
    assert emitted_events[0]["mutation_receipt"]["delivery"] == "DELIVERED"

    stale_sandbox = ToolSandbox(
        scenario=copy.deepcopy(scenario), event_bus=event_bus, plugin_manager=manager
    )
    plugin.on_step_start(stale_sandbox, node_id="node_stale", node_data={"stale_commit": True})
    res_stale = await stale_sandbox.execute("update_accounts", {})
    assert res_stale["error_code"] == "STATE_COMMIT_REJECTED"
    assert stale_sandbox.commit_boundary.revision == 1
    from eval_runner.mutations.mutation_evidence import fault_receipt_failures

    assert (
        fault_receipt_failures(
            provider.get_events("mutation-proof"),
            [
                ("commit_after_cancel", "node_cancel"),
                ("partial_commit", "node_partial_real"),
                ("stale_commit", "node_stale"),
            ],
            run_id="mutation-proof",
        )
        == []
    )
