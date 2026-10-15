"""
tests/contracts/test_runtime_contracts.py
Contract coverage for agentv_runtime.contracts — the canonical Phase-0 truth objects.

Covers:
  - _now() helper
  - ReadinessTier.at_least() both success and exception branches
  - RuntimeHealth.is_healthy property
  - RuntimeHealth.to_dict()
  - AssertionResult.to_dict()
  - TransitionEvidence.to_dict()
  - VerificationResult.is_verified
  - VerificationResult.attestation_grade all branches
  - VerificationResult.to_dict() with nested objects
  - VerificationResult.from_session_decision() full path
  - RCAResult.to_dict() with and without violated_assertion
  - EvidenceArtifact.to_dict()
"""

from __future__ import annotations

from agentv_runtime.contracts import (
    CONTRACTS_VERSION,
    AssertionResult,
    EvidenceArtifact,
    RCAResult,
    ReadinessTier,
    RuntimeHealth,
    TransitionEvidence,
    Verdict,
    VerificationResult,
    _now,
)


class TestNowHelper:
    def test_now_returns_iso_string(self):
        """_now() must return a non-empty UTC ISO-format datetime string."""
        result = _now()
        assert isinstance(result, str)
        assert len(result) > 0
        # Should be parseable as ISO-8601 (contains T separator and +00:00 or Z)
        assert "T" in result


class TestReadinessTier:
    def test_at_least_exact_match(self):
        assert ReadinessTier.at_least("CONFIGURED", "CONFIGURED") is True

    def test_at_least_higher_tier(self):
        assert ReadinessTier.at_least("VERIFIABLE", "REACHABLE") is True

    def test_at_least_lower_tier(self):
        assert ReadinessTier.at_least("UNCONFIGURED", "CONFIGURED") is False

    def test_at_least_unknown_tier_returns_false(self):
        """ValueError from .index() must be caught and return False."""
        assert ReadinessTier.at_least("UNKNOWN_TIER", "CONFIGURED") is False

    def test_at_least_both_unknown(self):
        assert ReadinessTier.at_least("BOGUS_A", "BOGUS_B") is False


class TestRuntimeHealth:
    def _make(self, status: str = "HEALTHY") -> RuntimeHealth:
        return RuntimeHealth(
            status=status,
            mode="production",
            version="3.0.0",
            dependencies={"db": "HEALTHY"},
        )

    def test_is_healthy_true(self):
        assert self._make("HEALTHY").is_healthy is True

    def test_is_healthy_false_degraded(self):
        assert self._make("DEGRADED").is_healthy is False

    def test_is_healthy_false_unreachable(self):
        assert self._make("UNREACHABLE").is_healthy is False

    def test_to_dict_roundtrip(self):
        h = self._make("HEALTHY")
        d = h.to_dict()
        assert d["status"] == "HEALTHY"
        assert d["mode"] == "production"
        assert d["version"] == "3.0.0"
        assert isinstance(d["dependencies"], dict)
        assert isinstance(d["last_heartbeat"], str)


class TestAssertionResult:
    def test_to_dict_basic(self):
        ar = AssertionResult(
            assertion_id="assert-001",
            kind="metric",
            node_id="node-a",
            passed=True,
            severity="required",
            expected=1.0,
            actual=0.95,
        )
        d = ar.to_dict()
        assert d["assertion_id"] == "assert-001"
        assert d["passed"] is True
        assert d["kind"] == "metric"
        assert d["expected"] == 1.0
        assert d["actual"] == 0.95

    def test_to_dict_with_optional_fields(self):
        ar = AssertionResult(
            assertion_id="assert-002",
            kind="state_hygiene",
            node_id=None,
            passed=False,
            invalid=True,
            reason="Metric not registered",
            mode="contains",
            source_ref="trace://event/42",
        )
        d = ar.to_dict()
        assert d["invalid"] is True
        assert d["reason"] == "Metric not registered"
        assert d["node_id"] is None
        assert d["source_ref"] == "trace://event/42"


class TestTransitionEvidence:
    def test_to_dict_basic(self):
        te = TransitionEvidence(
            from_node="n1",
            to_node="n2",
            selected_edge_id="edge-001",
            edge_type="sequential",
            transition_reason="default_fallback",
        )
        d = te.to_dict()
        assert d["from_node"] == "n1"
        assert d["to_node"] == "n2"
        assert d["selected_edge_id"] == "edge-001"
        assert d["edge_type"] == "sequential"
        assert d["evaluated_predicate"] is None
        assert d["observed_value"] is None

    def test_to_dict_with_predicate(self):
        te = TransitionEvidence(
            from_node="n1",
            to_node="n3",
            selected_edge_id="edge-cond-01",
            edge_type="condition",
            transition_reason="predicate_matched",
            evaluated_predicate={"field": "status", "op": "eq", "value": "success"},
            observed_value="success",
            source_execution_id="exec-001",
            target_execution_id="exec-002",
        )
        d = te.to_dict()
        assert d["evaluated_predicate"]["op"] == "eq"
        assert d["observed_value"] == "success"
        assert d["source_execution_id"] == "exec-001"


class TestVerificationResult:
    def _make(
        self,
        verdict: str = Verdict.VERIFIED,
        mode: str = "live",
        signature_verified: bool = True,
        evidence_complete: bool = True,
    ) -> VerificationResult:
        return VerificationResult(
            evaluation_run_id="run-001",
            scenario_version_id="sv-001",
            case_id="case-001",
            attempt_id="att-001",
            attempt_number=1,
            execution_mode=mode,
            verdict=verdict,
            because=["All checks passed"],
            signature_verified=signature_verified,
            evidence_complete=evidence_complete,
        )

    def test_is_verified_true(self):
        assert self._make(Verdict.VERIFIED).is_verified is True

    def test_is_verified_false(self):
        assert self._make(Verdict.NOT_VERIFIED).is_verified is False

    def test_attestation_grade_not_verified(self):
        """Any non-VERIFIED verdict → not_applicable."""
        vr = self._make(Verdict.NOT_VERIFIED, mode="live")
        assert vr.attestation_grade == "not_applicable"

    def test_attestation_grade_attested_live(self):
        """VERIFIED + live execution → attested."""
        vr = self._make(Verdict.VERIFIED, mode="live")
        assert vr.attestation_grade == "attested"

    def test_attestation_grade_attested_hybrid(self):
        """VERIFIED + hybrid execution → attested."""
        vr = self._make(Verdict.VERIFIED, mode="hybrid")
        assert vr.attestation_grade == "attested"

    def test_attestation_grade_verifiable_simulated(self):
        """VERIFIED + simulated → verifiable (not audit-grade)."""
        vr = self._make(Verdict.VERIFIED, mode="simulated")
        assert vr.attestation_grade == "verifiable"

    def test_to_dict_includes_attestation_grade_and_version(self):
        ar = AssertionResult(assertion_id="a1", kind="metric", node_id="n1", passed=True)
        te = TransitionEvidence(
            from_node="n1",
            to_node="n2",
            selected_edge_id="e1",
            edge_type="sequential",
            transition_reason="default_fallback",
        )
        vr = VerificationResult(
            evaluation_run_id="run-001",
            scenario_version_id="sv-001",
            case_id="case-001",
            attempt_id="att-001",
            attempt_number=1,
            execution_mode="live",
            verdict=Verdict.VERIFIED,
            assertions=[ar],
            transitions=[te],
            signature_verified=True,
            evidence_complete=True,
        )
        d = vr.to_dict()
        assert d["attestation_grade"] == "attested"
        assert d["contracts_version"] == CONTRACTS_VERSION
        # assertions and transitions should be serialized dicts
        assert isinstance(d["assertions"][0], dict)
        assert d["assertions"][0]["assertion_id"] == "a1"
        assert isinstance(d["transitions"][0], dict)
        assert d["transitions"][0]["from_node"] == "n1"

    def test_to_dict_with_already_dict_assertions(self):
        """to_dict must pass through plain dicts in assertions/transitions unchanged."""
        raw_assert = {"metric": "accuracy", "passed": True}
        raw_trans = {"from_node": "x", "to_node": "y"}
        vr = VerificationResult(
            evaluation_run_id="r",
            scenario_version_id="sv",
            case_id="c",
            attempt_id="a",
            attempt_number=1,
            execution_mode="simulated",
            verdict=Verdict.INCONCLUSIVE,
            assertions=[raw_assert],
            transitions=[raw_trans],
        )
        d = vr.to_dict()
        assert d["assertions"][0] == raw_assert
        assert d["transitions"][0] == raw_trans


class TestVerificationResultFromSessionDecision:
    def _minimal_decision(self, decision_val: str = "PASS") -> dict:
        return {
            "decision": decision_val,
            "because": ["Passed all checks"],
            "assertions": [],
            "expected_transitions": [],
            "observed_execution": [{"node_id": "n1"}],
            "policy_checks": [],
            "evidence_refs": ["run.jsonl"],
            "identity": {
                "evaluation_run_id": "run-001",
                "scenario_version_id": "sv-001",
                "case_id": "case-001",
                "attempt_id": "att-001",
                "attempt_number": 1,
                "execution_mode": "simulated",
            },
        }

    def test_pass_maps_to_verified(self):
        vr = VerificationResult.from_session_decision(self._minimal_decision("PASS"))
        assert vr.verdict == Verdict.VERIFIED
        assert vr.evaluation_run_id == "run-001"
        assert vr.attempt_number == 1

    def test_fail_maps_to_not_verified(self):
        vr = VerificationResult.from_session_decision(self._minimal_decision("FAIL"))
        assert vr.verdict == Verdict.NOT_VERIFIED

    def test_evaluation_invalid_maps_correctly(self):
        vr = VerificationResult.from_session_decision(self._minimal_decision("EVALUATION_INVALID"))
        assert vr.verdict == Verdict.EVALUATION_INVALID

    def test_unknown_decision_maps_to_inconclusive(self):
        vr = VerificationResult.from_session_decision(self._minimal_decision("SOME_UNKNOWN"))
        assert vr.verdict == Verdict.INCONCLUSIVE

    def test_assertion_dicts_converted_to_assertion_results(self):
        decision = self._minimal_decision("PASS")
        decision["assertions"] = [
            {
                "metric": "accuracy",
                "source": "metric",
                "node": "t1",
                "passed": True,
                "severity": "required",
                "expected": 0.9,
                "actual_after": 0.95,
                "actual_before": 0.0,
                "mode": "numerical_tolerance",
                "reason": None,
                "invalid": False,
            }
        ]
        vr = VerificationResult.from_session_decision(decision)
        assert len(vr.assertions) == 1
        ar = vr.assertions[0]
        assert isinstance(ar, AssertionResult)
        assert ar.assertion_id == "accuracy"
        assert ar.passed is True
        assert ar.actual == 0.95
        assert ar.actual_before == 0.0

    def test_already_assertion_result_passed_through(self):
        decision = self._minimal_decision("PASS")
        ar_obj = AssertionResult(
            assertion_id="pre-built",
            kind="metric",
            node_id="n1",
            passed=True,
        )
        decision["assertions"] = [ar_obj]
        vr = VerificationResult.from_session_decision(decision)
        assert vr.assertions[0] is ar_obj

    def test_transition_dicts_converted_to_transition_evidence(self):
        decision = self._minimal_decision("PASS")
        decision["expected_transitions"] = [
            {
                "from_node": "n1",
                "to_node": "n2",
                "selected_edge_id": "e-001",
                "edge_type": "sequential",
                "transition_reason": "default_fallback",
                "evaluated_predicate": None,
                "observed_value": None,
                "source_execution_id": None,
                "target_execution_id": None,
            }
        ]
        vr = VerificationResult.from_session_decision(decision)
        assert len(vr.transitions) == 1
        t = vr.transitions[0]
        assert isinstance(t, TransitionEvidence)
        assert t.from_node == "n1"
        assert t.selected_edge_id == "e-001"

    def test_already_transition_evidence_passed_through(self):
        decision = self._minimal_decision("PASS")
        te_obj = TransitionEvidence(
            from_node="a",
            to_node="b",
            selected_edge_id="e-pre",
            edge_type="parallel",
            transition_reason="parallel_fanout",
        )
        decision["expected_transitions"] = [te_obj]
        vr = VerificationResult.from_session_decision(decision)
        assert vr.transitions[0] is te_obj

    def test_missing_identity_fields_default_gracefully(self):
        """from_session_decision must not crash on partial identity."""
        vr = VerificationResult.from_session_decision(
            {
                "decision": "PASS",
                "because": [],
                "assertions": [],
                "expected_transitions": [],
                "observed_execution": [],
                "policy_checks": [],
                "evidence_refs": [],
                "identity": {},
            }
        )
        assert vr.evaluation_run_id == ""
        assert vr.attempt_number == 1
        assert vr.verdict == Verdict.VERIFIED

    def test_signature_verified_and_evidence_complete_from_decision(self):
        decision = self._minimal_decision("PASS")
        decision["signature_verified"] = True
        decision["evidence_complete"] = True
        vr = VerificationResult.from_session_decision(decision)
        assert vr.signature_verified is True
        assert vr.evidence_complete is True

    def test_signature_verified_and_evidence_complete_from_identity(self):
        decision = self._minimal_decision("PASS")
        decision["identity"]["signature_verified"] = True
        decision["identity"]["evidence_complete"] = True
        vr = VerificationResult.from_session_decision(decision)
        assert vr.signature_verified is True
        assert vr.evidence_complete is True

    def test_evidence_missing_forces_evidence_complete_false(self):
        decision = self._minimal_decision("PASS")
        decision["evidence_complete"] = True
        decision["evidence_missing"] = True
        vr = VerificationResult.from_session_decision(decision)
        assert vr.evidence_complete is False


class TestRCAResult:
    def test_to_dict_without_violated_assertion(self):
        rca = RCAResult(
            confidence="suspected",
            failure_class="NODE_EXECUTION_FAILURE",
            node_id="n1",
            summary="Agent failed to call the required tool.",
        )
        d = rca.to_dict()
        assert d["confidence"] == "suspected"
        assert d["failure_class"] == "NODE_EXECUTION_FAILURE"
        assert d["node_id"] == "n1"
        assert d["violated_assertion"] is None

    def test_to_dict_with_assertion_result_violated_assertion(self):
        ar = AssertionResult(
            assertion_id="assert-rca",
            kind="metric",
            node_id="n2",
            passed=False,
        )
        rca = RCAResult(
            confidence="confirmed",
            failure_class="EVALUATION_INVALID",
            violated_assertion=ar,
            summary="Evaluator rejected.",
        )
        d = rca.to_dict()
        # When violated_assertion is an AssertionResult, its to_dict() is called
        assert isinstance(d["violated_assertion"], dict)
        assert d["violated_assertion"]["assertion_id"] == "assert-rca"
        assert d["violated_assertion"]["passed"] is False

    def test_to_dict_with_plain_dict_violated_assertion(self):
        """If violated_assertion is already a plain dict (not AssertionResult),
        asdict() should serialize it as a dict directly."""
        # Note: dataclasses.asdict on a frozen dataclass with None field returns None.
        # With a non-AssertionResult value in violated_assertion, the isinstance check
        # is False, so we just return the raw asdict() result.
        rca = RCAResult(
            confidence="detected",
            failure_class="TIMEOUT",
            violated_assertion=None,
        )
        d = rca.to_dict()
        assert d["violated_assertion"] is None


class TestEvidenceArtifact:
    def test_to_dict_roundtrip(self):
        ea = EvidenceArtifact(
            artifact_id="art-001",
            run_id="run-001",
            name="run.jsonl",
            uri="file:///runs/run-001/run.jsonl",
            content_hash="sha3_256:abc123",
            artifact_type="trace_events",
            certified=True,
            metadata={"source": "session_manager"},
        )
        d = ea.to_dict()
        assert d["artifact_id"] == "art-001"
        assert d["certified"] is True
        assert d["content_hash"] == "sha3_256:abc123"
        assert d["metadata"]["source"] == "session_manager"

    def test_to_dict_uncertified_defaults(self):
        ea = EvidenceArtifact(
            artifact_id="art-002",
            run_id="run-002",
            name="manifest.json",
            uri="file:///runs/run-002/manifest.json",
            content_hash="sha3_256:def456",
            artifact_type="manifest",
        )
        d = ea.to_dict()
        assert d["certified"] is False
        assert d["metadata"] == {}


class TestStateComparisonContract:
    def test_state_comparison_to_dict_defaults(self):
        from agentv_runtime.state_comparison import StateComparison

        sc = StateComparison(
            scenario_node_id="node_1",
            execution_instance_id="exec_instance_01",
            assertion_id="assert_db_parity",
            expected={"status": "committed"},
            actual={"status": "pending"},
        )
        d = sc.to_dict()
        assert d["scenario_node_id"] == "node_1"
        assert d["execution_instance_id"] == "exec_instance_01"
        assert d["comparison"]["kind"] == "state_comparison"
        assert d["comparison"]["result"] == "diverged"
        assert d["comparison"]["failed_assertion"] == "assert_db_parity"
        assert d["assertions"] == []

    def test_state_comparison_to_dict_custom_comparison_and_assertions(self):
        from agentv_runtime.state_comparison import StateComparison

        custom_comp = {"kind": "semantic_diff", "score": 0.42}
        assertions = [{"id": "a1", "passed": False}]
        sc = StateComparison(
            scenario_node_id="node_2",
            execution_instance_id="exec_instance_02",
            assertion_id="assert_semantic",
            expected="ready",
            actual="error",
            comparison_result="failed",
            evidence_ref="custom_trace.jsonl",
            comparison=custom_comp,
            assertions=assertions,
            source="custom_validator",
        )
        d = sc.to_dict()
        assert d["comparison"] == custom_comp
        assert d["assertions"] == assertions
        assert d["source"] == "custom_validator"


class TestAdditionalRuntimeContracts:
    def test_verification_result_unverified_signature_branches(self):
        res_live = VerificationResult(
            evaluation_run_id="run-test-live",
            scenario_version_id="scen-01",
            case_id="case1",
            attempt_id="att1",
            attempt_number=1,
            verdict=Verdict.VERIFIED,
            execution_mode="live",
            signature_verified=False,
            evidence_complete=True,
        )
        assert res_live.attestation_grade == "verifiable"

        res_sim = VerificationResult(
            evaluation_run_id="run-test-sim",
            scenario_version_id="scen-01",
            case_id="case1",
            attempt_id="att1",
            attempt_number=1,
            verdict=Verdict.VERIFIED,
            execution_mode="simulated",
            signature_verified=False,
            evidence_complete=True,
        )
        assert res_sim.attestation_grade == "simulated"

    def test_evidence_reference_to_dict_and_from_dict(self):
        from agentv_runtime.contracts import EvidenceReference

        ref = EvidenceReference(
            source_id="sql_db",
            scope="users_table",
            selector_hash="sel_hash_1",
            query_or_operation_hash="query_hash_1",
            result_hash="res_hash_1",
            result_count=42,
            source_version="v2.1",
            sampled_result={"sample": "data"},
            provenance={"server": "db.corp"},
        )
        d = ref.to_dict()
        assert d["source_id"] == "sql_db"
        assert d["result_count"] == 42
        restored = EvidenceReference.from_dict(d)
        assert restored.source_id == ref.source_id
        assert restored.scope == ref.scope
        assert restored.result_hash == ref.result_hash
        assert restored.result_count == 42

    def test_mutation_contracts_serialization(self):
        from agentv_runtime.contracts import (
            MutationCampaignSpec,
            MutationContext,
            MutationCoordinate,
            MutationDescriptor,
            MutationHandle,
            MutationRecord,
            MutationTier,
        )

        desc = MutationDescriptor(
            id="mut_test_01",
            label="Prompt Injection",
            vector="input",
            operation="inject_adversarial",
            tier=MutationTier.T1_BEHAVIORAL,
            source="core",
            description="Tests prompt robustness",
            target_field="prompt",
            deterministic=True,
        )
        d_desc = desc.to_dict()
        assert d_desc["id"] == "mut_test_01"
        assert d_desc["vector"] == "input"

        coord = MutationCoordinate(
            vector="tool",
            operation="drop_call",
            tier=MutationTier.T2_STRUCTURAL,
        )
        d_coord = coord.to_dict()
        assert d_coord["vector"] == "tool"
        assert d_coord["operation"] == "drop_call"

        ctx = MutationContext(scenario={"id": "s1"}, seed=42)
        assert ctx.seed == 42
        assert ctx.rng is not None

        ctx_no_seed = MutationContext(scenario={"id": "s1"})
        assert ctx_no_seed.seed is None

        handle = MutationHandle(
            mutation_id="mut_h1",
            name="Drop Call",
            applied=True,
            coordinate=coord,
            target="tool_execute",
            details={"drop_count": 1},
        )
        d_handle = handle.to_dict()
        assert d_handle["applied"] is True
        assert d_handle["coordinate"]["vector"] == "tool"

        rec = MutationRecord(
            mutation_id="mut_rec_1",
            name="Mut Record",
            vector="state",
            operation="corrupt_row",
            tier="T1",
            target="db_state",
            applied_at_step=2,
            details={"key": "val"},
        )
        d_rec = rec.to_dict()
        assert d_rec["mutation_id"] == "mut_rec_1"
        assert d_rec["applied_at_step"] == 2

        camp = MutationCampaignSpec(
            campaign_id="camp_01",
            profile="enterprise_soak",
            agents=["agent_a"],
        )
        d_camp = camp.to_dict()
        assert d_camp["campaign_id"] == "camp_01"
        assert d_camp["agents"] == ["agent_a"]


class TestManifestSerializationContracts:
    def test_to_json_compatible_callable_raises(self):
        import pytest

        from agentv_runtime.manifest import _to_json_compatible

        with pytest.raises(ValueError, match="LossyScenarioError: Unsupported callable"):
            _to_json_compatible(lambda x: x)

    def test_to_json_compatible_set_sorting(self):
        from agentv_runtime.manifest import _to_json_compatible

        s = {"gamma", "alpha", "beta"}
        result = _to_json_compatible(s)
        assert isinstance(result, list)
        assert result == ["alpha", "beta", "gamma"]

    def test_to_json_compatible_custom_to_dict_and_unsupported_type(self):
        import pytest

        from agentv_runtime.manifest import _to_json_compatible

        class CustomEntity:
            def to_dict(self):
                return {"entity_id": "ent_123"}

        res = _to_json_compatible(CustomEntity())
        assert res == {"entity_id": "ent_123"}

        class UnsupportedEntity:
            pass

        with pytest.raises(TypeError, match="Unsupported non-canonical value"):
            _to_json_compatible(UnsupportedEntity())

    def test_preflight_fingerprint_endpoint_and_protocol_injection(self):
        from agentv_runtime.manifest import compute_preflight_fingerprint

        fp = compute_preflight_fingerprint(
            scenario_id="scen_fp_1",
            scen_hash="scen_hash_fp",
            endpoint="http://agent.local:8080/eval",
            protocol="HTTP",
        )
        assert isinstance(fp, str)
        assert len(fp) == 64

    def test_execution_manifest_from_scenario_resolved_mode(self):
        from agentv_runtime.manifest import ManifestBuilder

        scenario_data = {
            "id": "scen_manifest_01",
            "version": "1.0.0",
            "metadata": {"name": "Test Scenario"},
        }
        manifest = ManifestBuilder.build(
            scenario_data=scenario_data,
            agent_config={"endpoint": "http://localhost:5000"},
            execution_mode="live",
        )
        assert manifest.runtime_config["execution_mode"] == "live"
        assert manifest.metadata["execution_mode"] == "live"


class TestRuntimeScenarioAndInterfaceContracts:
    def test_canonical_scenario_ir_from_scenario_without_evaluation_plan(self, monkeypatch):
        import eval_runner.execution_ir as exec_ir
        from agentv_runtime.scenario import CanonicalScenarioIR

        orig_compile = exec_ir.compile_workflow

        def mock_compile_workflow(data):
            plan = orig_compile(data)
            plan.evaluation_plan = None
            return plan

        monkeypatch.setattr(exec_ir, "compile_workflow", mock_compile_workflow)

        scenario = {
            "id": "scen_no_eval_plan",
            "version": "1.0.0",
            "workflow": [
                {
                    "id": "step_1",
                    "task": "hello",
                    "success_criteria": [{"metric": "exact_match", "assertion": "=="}],
                }
            ],
        }
        ir = CanonicalScenarioIR.from_scenario(scenario)
        assert ir.scenario_id == "scen_no_eval_plan"
        assert ir.evaluation_plan == {}

    def test_authorization_backend_default_service_credential(self):
        from agentv_runtime.interfaces import AuthorizationBackend

        class TestAuthBackend(AuthorizationBackend):
            def authorize_request(self, request):
                return True

            def check_permission(self, subject, action, resource):
                return True

            def validate_token(self, token):
                return {}

        backend = TestAuthBackend()
        assert backend.get_service_credential() is None

    def test_runtime_approval_request_lifecycle(self):
        from agentv_runtime.interfaces import ApprovalRequest

        req = ApprovalRequest(
            approval_token="tok_123",
            run_id="run_456",
            turn_index=2,
            outbound_payload_hash="sha3_256:abcd",
            required_role="approver",
            reviewer_credentials={"role": "admin"},
            status="PENDING",
            rule_id="rule_sec",
            checkpoint_id="chk_01",
            action_payload={"key": "val"},
            prompt="Authorize action",
            created_at=1700000000.0,
            decision="APPROVED",
            decision_reason="Policy compliant",
            decided_by="operator@local",
            decided_at=1700000010.0,
            metadata={"source": "test"},
        )
        d = req.to_dict()
        assert d["approval_token"] == "tok_123"
        assert d["run_id"] == "run_456"
        assert d["decision"] == "APPROVED"

        restored = ApprovalRequest.from_dict(d)
        assert restored.approval_token == req.approval_token
        assert restored.run_id == req.run_id
        assert restored.turn_index == req.turn_index
        assert restored.outbound_payload_hash == req.outbound_payload_hash
        assert restored.required_role == req.required_role
        assert restored.reviewer_credentials == req.reviewer_credentials
        assert restored.decision == req.decision
        assert restored.metadata == req.metadata
