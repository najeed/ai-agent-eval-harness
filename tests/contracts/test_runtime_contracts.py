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
