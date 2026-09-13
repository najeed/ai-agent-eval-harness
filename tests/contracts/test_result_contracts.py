"""
tests/contracts/test_result_contracts.py
Contract Test Suite for First-Class Product Result Contracts (v2.0.0).

Validates:
  1. ExecutionResult contract schema, immutability, and serialization.
  2. EvaluationResult contract schema, pass@k aggregation,
  and backward-compatible sequence indexing.
  3. VerificationResult NIST AI-100-1 7-dimension scoring and safety floor enforcement.
  4. Attestation / VerificationCertificate cryptographic certificate schemas.
"""

from __future__ import annotations

import dataclasses

import pytest

from agentv_runtime.results import (
    Attestation,
    EvaluationResult,
    ExecutionResult,
    VerificationCertificate,
    VerificationResult,
)


class TestResultContracts:
    """
    Contract tests for all first-class product result models.
    """

    def test_execution_result_immutability_and_serialization(self):
        """Contract: ExecutionResult is immutable and round-trips via to_dict / from_dict."""
        exec_res = ExecutionResult(
            task_id="task_calc_01",
            status="success",
            output={"result": 42},
            metrics=[{"name": "latency", "value": 0.05}],
            tokens={"prompt": 100, "completion": 20},
            cost=0.002,
            latency=0.05,
        )

        # 1. Immutability
        with pytest.raises(dataclasses.FrozenInstanceError):
            exec_res.status = "failed"  # type: ignore

        # 2. Serialization round-trip
        data = exec_res.to_dict()
        assert data["task_id"] == "task_calc_01"
        assert data["output"]["result"] == 42
        assert data["tokens"]["prompt"] == 100

        reconstructed = ExecutionResult.from_dict(data)
        assert reconstructed.task_id == exec_res.task_id
        assert reconstructed.status == exec_res.status
        assert reconstructed.cost == exec_res.cost

    def test_evaluation_result_sequence_indexing_and_backward_compatibility(self):
        """
        Contract: EvaluationResult supports list-like indexing (result[0]) and iteration
        so legacy callers expecting list[list[dict]] operate seamlessly.
        """
        attempt1 = [{"task_id": "t1", "status": "success"}]
        attempt2 = [{"task_id": "t1", "status": "success"}]

        eval_res = EvaluationResult(
            run_id="run_eval_001",
            scenario_id="scen_math",
            pass_at_k=1.0,
            successful_attempts=2,
            total_attempts=2,
            attempts_results=[attempt1, attempt2],
            metadata={"environment": "production"},
            config_hash="abc123hash",
        )

        # 1. Sequence behavior
        assert len(eval_res) == 2
        assert eval_res[0] == attempt1
        assert eval_res[1] == attempt2
        assert [a for a in eval_res] == [attempt1, attempt2]

        # 2. Immutability
        with pytest.raises(dataclasses.FrozenInstanceError):
            eval_res.pass_at_k = 0.5  # type: ignore

        # 3. Serialization
        data = eval_res.to_dict()
        assert data["run_id"] == "run_eval_001"
        assert data["pass_at_k"] == 1.0

        reconstructed = EvaluationResult.from_dict(data)
        assert reconstructed.run_id == "run_eval_001"
        assert reconstructed.pass_at_k == 1.0
        assert len(reconstructed) == 2

    def test_verification_result_wsm_and_safety_floor(self):
        """
        Contract: VerificationResult implements NIST AI-100-1 7-dimension scoring and
        strictly enforces the Safety Floor (score capped at 0.49 if safety or security < 0.5).
        """
        # Normal score calculation
        vr_ok = VerificationResult(
            success=True,
            message="Verification passed",
            metrics={
                "safety": 1.0,
                "security": 1.0,
                "reliability": 1.0,
                "fairness": 1.0,
                "explainability": 1.0,
                "privacy": 1.0,
                "resilience": 1.0,
            },
        )
        assert vr_ok.aggregate_score == 1.0

        # Safety floor triggered: Safety = 0.3
        vr_unsafe = VerificationResult(
            success=False,
            message="Safety threshold breach",
            metrics={
                "safety": 0.3,
                "security": 1.0,
                "reliability": 1.0,
                "fairness": 1.0,
                "explainability": 1.0,
                "privacy": 1.0,
                "resilience": 1.0,
            },
        )
        assert vr_unsafe.aggregate_score <= 0.49

        # Security floor triggered: Security = 0.4
        vr_insecure = VerificationResult(
            success=False,
            message="Security threshold breach",
            metrics={
                "safety": 1.0,
                "security": 0.4,
                "reliability": 1.0,
                "fairness": 1.0,
                "explainability": 1.0,
                "privacy": 1.0,
                "resilience": 1.0,
            },
        )
        assert vr_insecure.aggregate_score <= 0.49

        # Immutability
        with pytest.raises(dataclasses.FrozenInstanceError):
            vr_ok.success = False  # type: ignore

    def test_attestation_certificate_contract(self):
        """Contract: Attestation and VerificationCertificate schemas
        are versioned, aligned with runtime certificate schema version, and serializable."""
        import agentv_runtime

        att = Attestation(
            run_id="run_att_001",
            manifest_hash="sha3_manifest_hash_123",
            signature="ed25519_signature_hex",
            signing_algorithm="Ed25519",
            key_id="vault/keys/eval-key-1",
        )

        assert isinstance(att, VerificationCertificate)
        assert att.certificate_schema_version == agentv_runtime.__certificate_schema_version__
        data = att.to_dict()
        assert data["run_id"] == "run_att_001"
        assert data["signing_algorithm"] == "Ed25519"
        assert data["verifier_version"] == "3.0.0"
        assert data["certificate_schema_version"] == "3.0.0"

    def test_lifecycle_artifact_contracts_uniform_envelope(self):
        """
        Contract: Every artifact in the 6-stage lifecycle:
          compose -> execute -> evaluate -> verify -> certify -> package
        implements the content-addressed envelope:
          schema_version, producer_identity, producer_version, content_hash, parent_artifact_refs.
        """
        from agentv_runtime.manifest import ExecutionManifest
        from agentv_runtime.package import VerificationPackage
        from agentv_runtime.results import (
            Attestation,
            EvaluationResult,
            RunTrace,
            VerificationResult,
        )
        from agentv_runtime.scenario import CanonicalScenarioIR, ScenarioDefinition

        # 1. COMPOSE stage: ScenarioDefinition & CanonicalScenarioIR
        scen_def = ScenarioDefinition(
            scenario_id="scen_math_01",
            scenario_version="1.0.0",
            definition={
                "id": "scen_math_01",
                "workflow": {
                    "nodes": [
                        {
                            "id": "step1",
                            "success_criteria": [
                                {"id": "sc1", "metric": "latency", "threshold": 1.0}
                            ],
                        },
                        {
                            "id": "step2",
                            "success_criteria": [
                                {"id": "sc2", "metric": "accuracy", "threshold": 0.9}
                            ],
                        },
                    ],
                    "edges": [
                        {
                            "id": "e_step1_step2",
                            "from": "step1",
                            "to": "step2",
                            "type": "condition",
                            "predicate": {"op": "truthy", "path": "output.result"},
                        }
                    ],
                },
            },
        )
        assert scen_def.schema_version == "2.0.0"
        assert scen_def.producer_identity == "agentv.scenario_composer"
        assert scen_def.content_hash.startswith("sha3_256:")
        assert scen_def.to_dict()["content_hash"] == scen_def.content_hash

        scen_ir = scen_def.compile()
        assert isinstance(scen_ir, CanonicalScenarioIR)
        assert scen_ir.schema_version == "2.0.0"
        assert scen_ir.producer_identity == "agentv.execution_ir"
        assert scen_ir.content_hash.startswith("sha3_256:")
        assert scen_def.content_hash in scen_ir.parent_artifact_refs

        # 2. EXECUTE stage: ExecutionManifest & RunTrace
        manifest = ExecutionManifest(
            manifest_id="man_001",
            scenario_id="scen_math_01",
            scenario_version="1.0.0",
            scenario_hash=scen_def.content_hash,
        )
        assert manifest.schema_version == "2.0.0"
        assert manifest.producer_identity == "agentv.manifest_builder"
        assert manifest.content_hash.startswith("sha3_256:")
        assert scen_def.content_hash in manifest.parent_artifact_refs

        trace = RunTrace(
            run_id="run_001",
            scenario_id="scen_math_01",
            trace_hash="sha3_256:trace123",
            evidence_root_hash="sha3_256:evroot123",
            event_count=42,
            parent_artifact_refs=[manifest.content_hash],
        )
        assert trace.schema_version == "2.0.0"
        assert trace.producer_identity == "agentv.execution_runtime"
        assert trace.content_hash.startswith("sha3_256:")
        assert manifest.content_hash in trace.parent_artifact_refs

        task_exec = ExecutionResult(
            task_id="step1",
            status="success",
            output={"result": 42},
            parent_artifact_refs=[manifest.content_hash],
        )
        assert task_exec.schema_version == "2.0.0"
        assert task_exec.producer_identity == "agentv.execution_runtime"
        assert task_exec.content_hash.startswith("sha3_256:")
        assert manifest.content_hash in task_exec.parent_artifact_refs

        # 3. EVALUATE stage: EvaluationResult
        eval_res = EvaluationResult(
            run_id="run_001",
            scenario_id="scen_math_01",
            pass_at_k=1.0,
            successful_attempts=1,
            total_attempts=1,
            attempts_results=[
                [{"task_id": "step1", "metrics": [{"metric": "score", "score": 1.0}]}]
            ],
            config_hash=manifest.content_hash,
            parent_artifact_refs=[manifest.content_hash, trace.evidence_root_hash],
        )
        assert eval_res.schema_version == "2.0.0"
        assert eval_res.producer_identity == "agentv.evaluation_engine"
        assert eval_res.content_hash.startswith("sha3_256:")
        assert manifest.content_hash in eval_res.parent_artifact_refs

        # 4. VERIFY stage: VerificationResult
        verif_res = VerificationResult(
            success=True,
            message="All requirements satisfied",
            metrics={"safety": 1.0, "security": 1.0, "reliability": 1.0},
            parent_artifact_refs=[eval_res.content_hash, trace.evidence_root_hash],
        )
        assert verif_res.schema_version == "2.0.0"
        assert verif_res.producer_identity == "agentv.verification_engine"
        assert verif_res.content_hash.startswith("sha3_256:")
        assert eval_res.content_hash in verif_res.parent_artifact_refs

        # 5. CERTIFY stage: Attestation (VerificationCertificate)
        cert = Attestation(
            run_id="run_001",
            manifest_hash=manifest.content_hash,
            signature="mock_sig_hex",
            signing_algorithm="ed25519",
            key_id="k1",
            parent_artifact_refs=[verif_res.content_hash, manifest.content_hash],
        )
        assert cert.schema_version == "3.0.0"
        assert cert.producer_identity == "agentv.certification_engine"
        assert cert.content_hash.startswith("sha3_256:")
        assert verif_res.content_hash in cert.parent_artifact_refs

        # 6. PACKAGE stage: VerificationPackage
        pkg = VerificationPackage(
            scenario_id="scen_math_01",
            scenario_version="1.0.0",
            scenario_hash=scen_def.content_hash,
            manifest_id=manifest.manifest_id,
            manifest_hash=manifest.content_hash,
            execution_identity={"run_id": "run_001"},
            trace_hash=trace.trace_hash,
            trace_seal={"event_count": 42},
            evidence_root_hash=trace.evidence_root_hash,
            required_oracle_ids=["score"],
            executed_oracle_results=[{"metric": "score", "passed": True}],
            decision={"decision": "PASS", "verdict": "VERIFIED"},
            evaluation_hash=eval_res.content_hash,
            verification_hash=verif_res.content_hash,
            certificate_hash=cert.content_hash,
        )
        assert pkg.schema_version == "1.0.0"
        assert pkg.producer_identity == "agentv.packaging_engine"
        assert len(pkg.content_hash) == 64

        # Cryptographic commitment graph check
        graph = pkg.commitment_graph()
        assert graph["scenario_hash"] == scen_def.content_hash
        assert graph["manifest_hash"] == manifest.content_hash
        assert graph["trace_hash"] == trace.trace_hash
        assert graph["evidence_root_hash"] == trace.evidence_root_hash
        assert graph["evaluation_hash"] == eval_res.content_hash
        assert graph["verification_hash"] == verif_res.content_hash
        assert graph["certificate_hash"] == cert.content_hash
        assert graph["package_hash"] == pkg.compute_package_hash()

    def test_artifact_serialization_roundtrip_and_edge_coverage(self):
        """Covers all serialization and error branch paths for artifact contracts."""
        from unittest.mock import patch

        from agentv_runtime.manifest import ExecutionManifest
        from agentv_runtime.package import VerificationPackage
        from agentv_runtime.results import (
            Attestation,
            EvaluationResult,
            ExecutionResult,
            RunTrace,
            VerificationResult,
        )
        from agentv_runtime.scenario import CanonicalScenarioIR, ScenarioDefinition

        # 1. Manifest compute_content_hash
        m = ExecutionManifest(
            manifest_id="m1",
            scenario_id="s1",
            scenario_version="1.0.0",
            scenario_hash="h1",
        )
        assert m.compute_content_hash() == m.content_hash

        # 2. Package compute_content_hash
        pkg = VerificationPackage(
            scenario_id="s1",
            scenario_version="1.0.0",
            scenario_hash="h1",
            manifest_id="m1",
            manifest_hash="mh1",
            execution_identity={"run_id": "r1"},
            trace_hash="th1",
            trace_seal={"event_count": 1},
            evidence_root_hash="eh1",
            required_oracle_ids=[],
            executed_oracle_results=[],
            decision={"decision": "PASS"},
        )
        assert pkg.compute_content_hash() == pkg.compute_package_hash()

        # 3. RunTrace serialization & error branch
        trace = RunTrace(
            run_id="r1",
            scenario_id="s1",
            trace_hash="th1",
            evidence_root_hash="eh1",
            event_count=10,
        )
        d_trace = trace.to_dict()
        rehydrated_trace = RunTrace.from_dict(d_trace)
        assert rehydrated_trace.run_id == trace.run_id
        with pytest.raises(TypeError):
            RunTrace.from_dict("not-a-dict")  # type: ignore

        # 4. ExecutionResult error branch
        with pytest.raises(TypeError):
            ExecutionResult.from_dict("not-a-dict")  # type: ignore

        # 5. EvaluationResult to_list
        eval_res = EvaluationResult(
            run_id="r1",
            scenario_id="s1",
            pass_at_k=1.0,
            successful_attempts=1,
            total_attempts=1,
            attempts_results=[[{"status": "ok"}]],
        )
        assert eval_res.to_list() == [[{"status": "ok"}]]

        # 6. VerificationResult compute_content_hash & from_dict
        vr = VerificationResult(success=True, message="ok")
        assert vr.compute_content_hash() == vr.content_hash
        vr_rehydrated = VerificationResult.from_dict(vr.to_dict())
        assert vr_rehydrated.success == vr.success
        with pytest.raises(TypeError):
            VerificationResult.from_dict("not-a-dict")  # type: ignore

        # 7. Attestation error branch
        att = Attestation(
            run_id="r1",
            manifest_hash="mh1",
            signature="sig",
            signing_algorithm="ed25519",
            key_id="k1",
        )
        att_rehydrated = Attestation.from_dict(att.to_dict())
        assert att_rehydrated.run_id == att.run_id
        with pytest.raises(TypeError):
            Attestation.from_dict("not-a-dict")  # type: ignore

        # 8. ScenarioDefinition empty definition compute_content_hash and from_dict
        scen_empty = ScenarioDefinition(scenario_id="s_empty", definition={})
        assert scen_empty.content_hash.startswith("sha3_256:")
        scen_rehydrated = ScenarioDefinition.from_dict(scen_empty.to_dict())
        assert scen_rehydrated.scenario_id == scen_empty.scenario_id

        # 9. CanonicalScenarioIR to_dict and from_dict
        scen_ir = CanonicalScenarioIR(scenario_id="s1")
        ir_rehydrated = CanonicalScenarioIR.from_dict(scen_ir.to_dict())
        assert ir_rehydrated.scenario_id == scen_ir.scenario_id

        # 10. Scenario compile fallback paths (when execution_ir is bypassed)
        with patch.dict("sys.modules", {"eval_runner.execution_ir": None}):
            # Dict workflow fallback
            scen_dict = {
                "id": "dict_scen",
                "workflow": {
                    "nodes": [{"id": "n1"}, {"id": "n2"}],
                    "edges": [{"from": "n1", "to": "n2"}],
                },
            }
            ir_dict = CanonicalScenarioIR.from_scenario(scen_dict)
            assert "n1" in ir_dict.nodes
            assert len(ir_dict.edges) == 1

            # List workflow fallback
            scen_list = {
                "id": "list_scen",
                "workflow": [{"id": "a"}, {"id": "b"}],
            }
            ir_list = CanonicalScenarioIR.from_scenario(scen_list)
            assert "a" in ir_list.nodes
            assert len(ir_list.edges) == 1
