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
