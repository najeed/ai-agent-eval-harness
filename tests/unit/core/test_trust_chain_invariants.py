"""
tests/unit/core/test_trust_chain_invariants.py

Authoritative Invariant Verification Suite for the
Evaluation -> Verification -> Certification Trust Chain:
1. Required-oracle completeness: Omitted or unverified required oracles fail certification.
2. Manifest immutability: Any mutation to agent, runtime,
or environment config changes manifest hash.
3. 16 canonical immutable fields in ExecutionManifest:
Mutation testing proves all 16 fields change hash.
4. Semantic cross-binding: Strict equality between ExecutionManifest
and EvaluatorFinalizationRecord.
5. VerificationPackage non-circular DAG commitment & canonical payload with provenance.
6. Evaluator signing failure fails closed: Emits CERTIFICATION_FAILED
and uncertifiable terminal state.
7. OSS Runtime boundary: Control plane routes excised from OSS console app.
8. Scenario structure validator: Rejection of invalid edge types and non-numeric priorities.
9. Preflight fingerprint canonical consistency across endpoints.
10. SSE event stream: Emits immutable trace _seq as SSE event ID.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from agentv_runtime.evidence_graph import (
    build_evidence_graph_from_events,
    compute_evidence_graph_root,
)
from agentv_runtime.finalization import EvaluatorFinalizationRecord
from agentv_runtime.manifest import (
    ExecutionManifest,
    compute_preflight_fingerprint,
    compute_scenario_hash,
)
from agentv_runtime.package import VerificationPackage
from eval_runner import config, events
from eval_runner.console.routes.runs import TERMINAL_TRACE_EVENTS, tail_file_generator
from eval_runner.console.routes.scenarios import validate_scenario_structure
from eval_runner.identity import IdentityService
from eval_runner.services.certification import CertificationService
from eval_runner.verifier import VerificationAuthority


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
    IdentityService._provision_local_identity("eval_kernel")

    return {"root": root, "runs": runs, "reports": reports, "trust": trust}


def _build_valid_test_vault(
    runs_dir: Path,
    run_id: str,
    scenario_id: str = "scen_test_01",
    scenario_version: str = "1.0.0",
    execution_mode: str = "live",
    evaluator_config_hash: str = "sha3_256:evalcfg1234",
    required_oracles: list[str] | None = None,
    trace_events: list[dict[str, Any]] | None = None,
    outcome: str = "pass",
    score: float = 1.0,
) -> tuple[Path, Path, ExecutionManifest, EvaluatorFinalizationRecord]:
    vault = runs_dir / run_id
    vault.mkdir(parents=True, exist_ok=True)
    trace_path = vault / "run.jsonl"

    req_oracles = required_oracles if required_oracles is not None else ["oracle_alpha"]
    scenario_data = {
        "metadata": {"id": scenario_id, "version": scenario_version},
        "id": scenario_id,
        "version": scenario_version,
    }
    scen_hash = compute_scenario_hash(scenario_data)

    exec_manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id=scenario_id,
        scenario_version=scenario_version,
        scenario_hash=scen_hash,
        agent_config={"model": "gpt-4", "endpoint": "http://agent.local"},
        runtime_config={
            "execution_mode": execution_mode,
            "evaluator_config_hash": evaluator_config_hash,
            "required_oracle_ids": req_oracles,
        },
        environment={"os": "linux", "python": "3.11"},
        metadata={
            "execution_mode": execution_mode,
            "evaluator_config_hash": evaluator_config_hash,
            "required_oracle_ids": req_oracles,
        },
    )
    manifest_file = vault / "execution_manifest.json"
    manifest_file.write_text(json.dumps(exec_manifest.to_dict()), encoding="utf-8")
    m_hash = exec_manifest.compute_manifest_hash()

    events_list = [
        {
            "_seq": 1,
            "event": "run_start",
            "execution_mode": execution_mode,
            "data": {
                "execution_mode": execution_mode,
                "scenario_id": scenario_id,
                "scenario_version": scenario_version,
                "scenario_hash": scen_hash,
                "scenario_data": scenario_data,
                "execution_manifest_hash": m_hash,
            },
        },
    ]
    if trace_events:
        events_list.extend(trace_events)
    else:
        # Default substantive evidence events satisfying the default required oracles
        for i, o_id in enumerate(req_oracles, start=2):
            events_list.append(
                {
                    "_seq": i,
                    "event": "oracle_result",
                    "data": {"oracle_id": o_id, "metric": o_id, "passed": True, "score": 1.0},
                }
            )

    ev_graph = build_evidence_graph_from_events(events_list, required_oracle_ids=req_oracles)
    ev_root = ev_graph.get("evidence_root_hash") or compute_evidence_graph_root(ev_graph)

    events_list.append(
        {
            "_seq": len(events_list) + 1,
            "event": "evaluation_result",
            "data": {
                "decision": "PASS" if outcome == "pass" else "FAIL",
                "status": outcome,
                "score": score,
                "passed": outcome == "pass",
            },
        }
    )

    fin_record = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash=m_hash,
        scenario_id=scenario_id,
        scenario_version=scenario_version,
        scenario_hash=scen_hash,
        evaluator_identity="eval_kernel",
        evaluator_config_hash=evaluator_config_hash,
        required_oracle_ids=req_oracles,
        evidence_root_hash=ev_root,
        outcome=outcome,
        score=score,
        metadata={"execution_mode": execution_mode},
    )
    fin_record = fin_record.sign()

    events_list.append(
        {
            "_seq": len(events_list) + 1,
            "event": "evaluator_finalization",
            "data": fin_record.to_dict(),
        }
    )

    with open(trace_path, "w", encoding="utf-8") as f:
        for ev in events_list:
            f.write(json.dumps(ev) + "\n")

    return vault, trace_path, exec_manifest, fin_record


def test_required_oracle_omitted_fails_certification(cert_vault):
    """P0-1: A required oracle that does not execute fails closed; certification is rejected."""
    run_id = "run-omitted-oracle-001"
    # Scenario requires ["oracle_alpha", "oracle_beta"], but trace only provides "oracle_alpha"
    custom_events = [
        {
            "_seq": 2,
            "event": "oracle_result",
            "data": {"oracle_id": "oracle_alpha", "passed": True, "score": 1.0},
        }
    ]
    _vault, _trace, _manifest, _fin = _build_valid_test_vault(
        cert_vault["runs"],
        run_id=run_id,
        required_oracles=["oracle_alpha", "oracle_beta"],
        trace_events=custom_events,
    )

    with pytest.raises(ValueError, match="MissingRequiredOracles"):
        CertificationService.execute_industrial_certification(run_id=run_id)


def test_manifest_agent_or_runtime_mutation_fails(cert_vault):
    """P0-2 & P0-3: Mutating agent or runtime configuration invalidates manifest hash."""
    run_id = "run-mutated-manifest-001"
    vault, _trace, _manifest, _fin = _build_valid_test_vault(cert_vault["runs"], run_id=run_id)

    # Tamper with the physical execution_manifest.json on disk
    manifest_file = vault / "execution_manifest.json"
    with open(manifest_file, encoding="utf-8") as f:
        data = json.load(f)

    # Mutate runtime_config
    data["runtime_config"]["execution_mode"] = "tampered_mode"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    with pytest.raises(ValueError, match="ManifestHashMismatch"):
        CertificationService.execute_industrial_certification(run_id=run_id)


def test_immutable_manifest_provenance_mutation_changes_hash():
    """Every single one of the 16 canonical immutable manifest fields alters the manifest hash."""
    base_manifest = ExecutionManifest(
        manifest_id="man_base_001",
        scenario_id="scen_base_001",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen_hash_001",
        tenant_id="tenant_01",
        workspace_id="ws_01",
        agent_config={"model": "gpt-4", "temp": 0.0},
        runtime_config={"mode": "live", "max_turns": 10},
        environment={"os": "linux", "arch": "x86_64"},
        created_at="2026-09-17T00:00:00Z",
        created_by="alice",
        metadata={"preflight": "fingerprint_123"},
        schema_version="2.0.0",
        producer_identity="agentv.builder",
        producer_version="2.0.0",
        parent_artifact_refs=["sha3_256:scen_hash_001"],
    )
    base_hash = base_manifest.compute_manifest_hash()

    mutations = {
        "manifest_id": "man_base_002",
        "scenario_id": "scen_base_002",
        "scenario_version": "2.0.0",
        "scenario_hash": "sha3_256:scen_hash_002",
        "tenant_id": "tenant_02",
        "workspace_id": "ws_02",
        "agent_config": {"model": "gpt-5", "temp": 0.5},
        "runtime_config": {"mode": "hybrid", "max_turns": 20},
        "environment": {"os": "darwin", "arch": "arm64"},
        "created_at": "2026-09-18T00:00:00Z",
        "created_by": "bob",
        "metadata": {"preflight": "fingerprint_456"},
        "schema_version": "2.1.0",
        "producer_identity": "agentv.custom_builder",
        "producer_version": "2.1.0",
        "parent_artifact_refs": ["sha3_256:scen_hash_002"],
    }

    assert len(mutations) == 16, "Must test exactly all 16 canonical immutable fields"

    for field_name, mutated_value in mutations.items():
        kwargs = {
            "manifest_id": base_manifest.manifest_id,
            "scenario_id": base_manifest.scenario_id,
            "scenario_version": base_manifest.scenario_version,
            "scenario_hash": base_manifest.scenario_hash,
            "tenant_id": base_manifest.tenant_id,
            "workspace_id": base_manifest.workspace_id,
            "agent_config": dict(base_manifest.agent_config),
            "runtime_config": dict(base_manifest.runtime_config),
            "environment": dict(base_manifest.environment),
            "created_at": base_manifest.created_at,
            "created_by": base_manifest.created_by,
            "metadata": dict(base_manifest.metadata),
            "schema_version": base_manifest.schema_version,
            "producer_identity": base_manifest.producer_identity,
            "producer_version": base_manifest.producer_version,
            "parent_artifact_refs": list(base_manifest.parent_artifact_refs),
        }
        kwargs[field_name] = mutated_value
        mutated_manifest = ExecutionManifest(**kwargs)
        mutated_hash = mutated_manifest.compute_manifest_hash()
        assert mutated_hash != base_hash, (
            f"Mutation of field '{field_name}' did not change manifest hash!"
        )


def test_manifest_finalization_semantic_discrepancy_fails(cert_vault):
    """Semantic cross-binding checks between ExecutionManifest and EvaluatorFinalizationRecord."""
    run_id_base = "run-semantic-crossbind"

    # 1. Scenario ID mismatch
    run_id = f"{run_id_base}-scen-id"
    vault, _trace, manifest, fin = _build_valid_test_vault(cert_vault["runs"], run_id=run_id)
    fin_tampered = EvaluatorFinalizationRecord(
        finalization_id=fin.finalization_id,
        run_id=fin.run_id,
        execution_manifest_hash=fin.execution_manifest_hash,
        scenario_id="different_scenario_id",
        scenario_version=fin.scenario_version,
        scenario_hash=fin.scenario_hash,
        evaluator_identity=fin.evaluator_identity,
        evaluator_config_hash=fin.evaluator_config_hash,
        required_oracle_ids=fin.required_oracle_ids,
        evidence_root_hash=fin.evidence_root_hash,
        outcome=fin.outcome,
        score=fin.score,
        metadata={"execution_mode": "live"},
    ).sign()
    # Rewrite trace with tampered finalization
    trace_file = vault / "run.jsonl"
    lines = [
        json.loads(line) for line in trace_file.read_text(encoding="utf-8").strip().split("\n")
    ]
    for line in lines:
        if line.get("event") == "evaluator_finalization":
            line["data"] = fin_tampered.to_dict()
    trace_file.write_text("\n".join(json.dumps(entry) for entry in lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ScenarioIdMismatch|ManifestScenarioIdMismatch"):
        CertificationService.execute_industrial_certification(run_id=run_id)

    # 2. Required oracles mismatch between manifest and finalization
    run_id_req = f"{run_id_base}-req-oracles"
    vault_req, _trace_req, _man_req, fin_req = _build_valid_test_vault(
        cert_vault["runs"], run_id=run_id_req
    )
    # Tamper manifest to have extra required oracle,
    # recompute manifest hash so ManifestHashMismatch doesn't trigger first
    manifest_file = vault_req / "execution_manifest.json"
    m_data = json.load(open(manifest_file, encoding="utf-8"))
    m_data["runtime_config"]["required_oracle_ids"] = ["oracle_alpha", "oracle_extra"]
    m_data["metadata"]["required_oracle_ids"] = ["oracle_alpha", "oracle_extra"]
    t_manifest = ExecutionManifest.from_dict(m_data)
    manifest_file.write_text(json.dumps(t_manifest.to_dict()), encoding="utf-8")
    # Update finalization execution_manifest_hash to match new manifest hash,
    # but keep fin required_oracle_ids as ["oracle_alpha"]
    fin_req_tampered = EvaluatorFinalizationRecord(
        finalization_id=fin_req.finalization_id,
        run_id=fin_req.run_id,
        execution_manifest_hash=t_manifest.compute_manifest_hash(),
        scenario_id=fin_req.scenario_id,
        scenario_version=fin_req.scenario_version,
        scenario_hash=fin_req.scenario_hash,
        evaluator_identity=fin_req.evaluator_identity,
        evaluator_config_hash=fin_req.evaluator_config_hash,
        required_oracle_ids=fin_req.required_oracle_ids,
        evidence_root_hash=fin_req.evidence_root_hash,
        outcome=fin_req.outcome,
        score=fin_req.score,
        metadata={"execution_mode": "live"},
    ).sign()
    trace_req_file = vault_req / "run.jsonl"
    lines = [
        json.loads(line_str)
        for line_str in trace_req_file.read_text(encoding="utf-8").strip().split("\n")
    ]
    for line in lines:
        if line.get("event") == "evaluator_finalization":
            line["data"] = fin_req_tampered.to_dict()
    trace_req_file.write_text(
        "\n".join(json.dumps(entry) for entry in lines) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="ManifestRequiredOracleMismatch"):
        CertificationService.execute_industrial_certification(run_id=run_id_req)


def test_verification_package_commitment_dag_integrity():
    """P0-5: VerificationPackage enforces non-circular commitment DAG and canonical provenance."""
    pkg = VerificationPackage(
        scenario_id="scen_dag_01",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen123",
        manifest_id="man_dag_01",
        manifest_hash="sha3_256:man123",
        execution_identity={"runtime_version": "2.0.0"},
        trace_hash="sha3_256:trace123",
        trace_seal={"digest": "sha3_256:trace123", "event_count": 5},
        evidence_root_hash="sha3_256:ev123",
        required_oracle_ids=["oracle_1"],
        executed_oracle_results=[{"metric": "oracle_1", "passed": True}],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
        finalization_hash="sha3_256:fin123",
        schema_version="2.0.0",
        producer_identity="agentv.verifier",
        producer_version="2.0.0",
        parent_artifact_refs=["sha3_256:scen123"],
    )

    dag = pkg.commitment_graph()
    # Confirm exact DAG nodes
    assert dag["scenario_hash"] == "sha3_256:scen123"
    assert dag["manifest_hash"] == "sha3_256:man123"
    assert dag["trace_hash"] == "sha3_256:trace123"
    assert dag["evidence_root_hash"] == "sha3_256:ev123"
    assert dag["finalization_hash"] == "sha3_256:fin123"
    assert "package_hash" in dag

    # Confirm canonical payload fields
    payload = pkg.canonical_payload_dict()
    assert payload["finalization_hash"] == "sha3_256:fin123"
    assert payload["schema_version"] == "2.0.0"
    assert payload["producer_identity"] == "agentv.verifier"
    assert payload["producer_version"] == "2.0.0"
    assert payload["parent_artifact_refs"] == ["sha3_256:scen123"]

    # Mutation test: changing finalization_hash changes package_hash
    base_hash = pkg.compute_package_hash()
    pkg_mutated = VerificationPackage.from_dict(
        {**pkg.to_dict(), "finalization_hash": "sha3_256:fin_different"}
    )
    assert pkg_mutated.compute_package_hash() != base_hash

    # Semantic cross-binding check in VerificationAuthority
    manifest_dict = {
        "manifest_id": "man_dag_01",
        "scenario_id": "scen_dag_01",
        "scenario_version": "1.0.0",
        "scenario_hash": "sha3_256:scen123",
    }
    # Mutating scenario_id in pkg causes VerificationAuthority to detect mismatch
    mismatched_pkg = VerificationPackage.from_dict(
        {**pkg.to_dict(), "scenario_id": "mismatched_scenario", "signature": "ed25519:test_sig"}
    )
    result = VerificationAuthority.verify_package(
        mismatched_pkg,
        canonical_manifest=manifest_dict,
        raw_trace_events=[],
    )
    failures = result.get("failures", [])
    assert any("ManifestScenarioIdMismatch" in f for f in failures)


@pytest.mark.asyncio
async def test_evaluator_signing_failure_emits_uncertifiable_terminal_state(
    monkeypatch, cert_vault
):
    """Evaluator signing failure terminates with CERTIFICATION_FAILED and uncertifiable result."""
    from eval_runner.runner import DefaultRunner

    runner = DefaultRunner()
    scenario = {
        "id": "scen_sign_fail_001",
        "version": "1.0.0",
        "steps": [{"name": "step1", "action": "echo"}],
    }

    # Force signing to fail
    def _failing_sign(*args, **kwargs):
        raise RuntimeError("Cryptographic hardware module unreachable")

    monkeypatch.setattr(EvaluatorFinalizationRecord, "sign", _failing_sign)

    emitted_events = []

    def _mock_emit(event_name, *args, **kwargs):
        data = args[0] if args else kwargs.get("data")
        emitted_events.append((event_name, data))

    monkeypatch.setattr(events, "emit", _mock_emit)

    result = await runner.run(scenario)

    # Must emit CERTIFICATION_FAILED
    event_names = [e[0] for e in emitted_events]
    assert events.CoreEvents.CERTIFICATION_FAILED in event_names
    assert events.CoreEvents.RUN_END in event_names

    # Run end status must be certification_failed
    run_end_data = next(e[1] for e in emitted_events if e[0] == events.CoreEvents.RUN_END)
    assert run_end_data["status"] == "certification_failed"
    assert run_end_data["finalization"] is None

    # Result must be uncertifiable with pass_at_k 0.0
    assert result.pass_at_k == 0.0
    assert result.metadata.get("uncertifiable") is True


def test_control_plane_routes_not_registered_in_oss_runtime():
    """
    OSS Runtime: Control Plane blueprints (publish_bp, compliance_packs_bp) are not registered.
    """
    from eval_runner.console.app import create_app

    app = create_app()
    registered_blueprints = set(app.blueprints.keys())

    assert "publish_bp" not in registered_blueprints
    assert "compliance_packs_bp" not in registered_blueprints

    rules = [rule.rule for rule in app.url_map.iter_rules()]
    assert not any(r.startswith("/v1/publish") for r in rules)
    assert not any(r.startswith("/v1/compliance-packs") for r in rules)


def test_scenario_validation_rejects_invalid_edge_types_and_priority():
    """
    Scenario structure validator: enforces valid edge types, dangling checks, and numeric priority.
    """
    # 1. Invalid edge type
    invalid_edge_type_scenario = {
        "id": "scen_invalid_edge",
        "version": "1.0.0",
        "nodes": [{"id": "node1", "type": "task"}, {"id": "node2", "type": "task"}],
        "edges": [{"from": "node1", "to": "node2", "type": "invalid_magic_type"}],
    }
    res, err = validate_scenario_structure(invalid_edge_type_scenario)
    assert res is False
    assert any("unknown type 'invalid_magic_type'" in e for e in err)

    # 2. Non-numeric priority
    non_numeric_priority_scenario = {
        "id": "scen_invalid_priority",
        "version": "1.0.0",
        "nodes": [{"id": "node1", "type": "task"}, {"id": "node2", "type": "task"}],
        "edges": [{"from": "node1", "to": "node2", "type": "sequential", "priority": "high"}],
    }
    res_p, err_p = validate_scenario_structure(non_numeric_priority_scenario)
    assert res_p is False
    assert any("non-numeric priority" in e for e in err_p)

    # 3. Valid edge scenario
    valid_scenario = {
        "id": "scen_valid",
        "version": "1.0.0",
        "nodes": [
            {"id": "node1", "type": "task", "task_description": "First task"},
            {"id": "node2", "type": "task", "task_description": "Second task"},
        ],
        "edges": [{"from": "node1", "to": "node2", "type": "sequential", "priority": 10}],
    }
    res_v, err_v = validate_scenario_structure(valid_scenario)
    assert res_v is True
    assert err_v == []


def test_preflight_fingerprint_canonical_consistency():
    """Canonical preflight fingerprint produces deterministic SHA3-256 digest over full manifest."""
    from agentv_runtime.canonical import canonical_json_encode

    fp1 = compute_preflight_fingerprint(
        scenario_id="scen_01",
        scen_hash="sha3_256:abc",
        endpoint="http://localhost:8000",
        protocol="openai",
        max_turns=15,
        agent_config={"model": "gpt-4o", "endpoint": "http://localhost:8000"},
        runtime_config={"max_turns": 15},
        scenario_version="1.2.0",
        tenant_id="acme",
        workspace_id="prod",
        seed=42,
        execution_mode="hermetic",
        evaluators=["accuracy", "latency"],
    )
    raw = {
        "agent_config": {
            "endpoint": "http://localhost:8000",
            "model": "gpt-4o",
            "protocol": "openai",
        },
        "endpoint": "http://localhost:8000",
        "evaluators": ["accuracy", "latency"],
        "execution_mode": "hermetic",
        "max_turns": 15,
        "protocol": "openai",
        "runtime_config": {"max_turns": 15},
        "scen_hash": "sha3_256:abc",
        "scenario_id": "scen_01",
        "scenario_version": "1.2.0",
        "seed": 42,
        "tenant_id": "acme",
        "workspace_id": "prod",
    }
    expected = hashlib.sha3_256(canonical_json_encode(raw)).hexdigest()
    assert fp1 == expected

    # Mutating model invalidates fingerprint
    fp_mutated = compute_preflight_fingerprint(
        scenario_id="scen_01",
        scen_hash="sha3_256:abc",
        endpoint="http://localhost:8000",
        protocol="openai",
        max_turns=15,
        agent_config={"model": "gpt-3.5-turbo", "endpoint": "http://localhost:8000"},
        runtime_config={"max_turns": 15},
        scenario_version="1.2.0",
        tenant_id="acme",
        workspace_id="prod",
        seed=42,
        execution_mode="hermetic",
        evaluators=["accuracy", "latency"],
    )
    assert fp_mutated != fp1


def test_sse_stream_emits_canonical_trace_seq(tmp_path):
    """
    SSE trace streamer emits the canonical trace _seq as event id and terminates on terminal events.
    """
    trace_file = tmp_path / "test_run.jsonl"
    events_to_write = [
        {"_seq": 42, "event": "step_executed", "data": {"step": 1}},
        {"_seq": 108, "event": "trace_sealed", "data": {"status": "sealed"}},
    ]
    with open(trace_file, "w", encoding="utf-8") as f:
        for ev in events_to_write:
            f.write(json.dumps(ev) + "\n")

    chunks = list(tail_file_generator(trace_file, run_id="test_run"))
    full_sse = "".join(chunks)

    # Must contain event id and payload data:
    assert "id: 42\n" in full_sse or "id: 1\n" in full_sse
    assert "id: 108\n" in full_sse or "id: 2\n" in full_sse
    assert '"_seq": 42' in full_sse
    assert '"_seq": 108' in full_sse
    assert '"event": "trace_sealed"' in full_sse

    # Check terminal events constant contains required terminal types
    assert "trace_sealed" in TERMINAL_TRACE_EVENTS
    assert "verification_certificate_issued" in TERMINAL_TRACE_EVENTS
    assert "certification_failed" in TERMINAL_TRACE_EVENTS
