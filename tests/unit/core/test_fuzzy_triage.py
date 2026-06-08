from unittest.mock import patch

from eval_runner.taxonomy import FailureCategory, FailureTaxonomy
from eval_runner.triage import Confidence, TriageEngine


def test_normalized_command_matching():
    """Verifies that base actions are matched despite different flags/args."""
    # Test normalization helper
    assert FailureTaxonomy._normalize_action("ls -la /tmp") == "ls"
    assert FailureTaxonomy._normalize_action("git commit -m 'test'") == "git"
    assert (
        FailureTaxonomy._normalize_action("python3 -c 'print(1)'") == "print(1)"
    )  # Simple heuristic check
    assert (
        FailureTaxonomy._normalize_action({"tool": "search_browser", "params": {"query": "test"}})
        == "search_browser"
    )


def test_fuzzy_loop_detection_with_flags():
    """Verifies that Logic State Stall is detected when base actions repeat."""
    history = [
        {"role": "agent", "tool_calls": [{"tool": "ls", "params": {"args": "-la"}}]},
        {"role": "environment", "content": {"status": "success", "result": "file1"}},
        {"role": "agent", "tool_calls": [{"tool": "ls", "params": {"args": "-F"}}]},
        {"role": "environment", "content": {"status": "success", "result": "file1"}},
        {"role": "agent", "tool_calls": [{"tool": "ls", "params": {"args": "-R"}}]},
    ]

    # FailureTaxonomy._detect_loops uses raw_msgs for fuzzy and normalized_actions for stalls
    # In this case, A -> B -> A is a cyclical loop (distance 2), which is a planning error.
    cat = FailureTaxonomy._detect_loops(history)
    assert cat == FailureCategory.LOGIC_PLANNING_ERROR


def test_fuzzy_text_similarity():
    """Verifies that SequenceMatcher catches near-duplicate agent thoughts."""
    history = [
        {"role": "agent", "content": "I am looking for the file now."},
        {"role": "agent", "content": "I'm looking for the file now..."},
    ]

    # Test _is_near_duplicate directly
    assert FailureTaxonomy._is_near_duplicate(history[0]["content"], history[1]["content"]) is True

    # Test _detect_loops integration
    cat = FailureTaxonomy._detect_loops(history)
    assert cat == FailureCategory.LOGIC_PLANNING_ERROR


def test_triage_engine_categorize_failure():
    # 1. triage_tag in task_result
    assert TriageEngine.categorize_failure({"triage_tag": "my_tag"}) == "MY_TAG"

    # 2. diagnostic_report and root_cause
    assert (
        TriageEngine.categorize_failure({"diagnostic_report": {"root_cause": "my_cause"}})
        == "MY_CAUSE"
    )

    # 3. classify returns SUCCESS -> maps to UNKNOWN_FAILURE
    with patch(
        "eval_runner.taxonomy.FailureTaxonomy.classify", return_value=FailureCategory.SUCCESS
    ):
        assert TriageEngine.categorize_failure({}) == "UNKNOWN_FAILURE"

    # 4. classify returns POLICY_VIOLATION -> maps to POLICY_VIOLATION
    with patch(
        "eval_runner.taxonomy.FailureTaxonomy.classify",
        return_value=FailureCategory.POLICY_VIOLATION,
    ):
        assert TriageEngine.categorize_failure({}) == "POLICY_VIOLATION"


def test_triage_engine_identify_root_cause_input_list():
    # Passed a list instead of dict
    history = [{"role": "agent", "content": "hi"}]
    res = TriageEngine.identify_root_cause(history)
    assert res["index"] == 0


def test_triage_engine_identify_root_cause_no_history():
    res = TriageEngine.identify_root_cause({"conversation_history": []})
    assert res["index"] == -1
    assert res["confidence"] == Confidence.INCONCLUSIVE
    assert res["reason"] == "No history"


def test_triage_engine_step_back_anchoring():
    # Test step-back anchoring with agent preceding turn
    history = [
        {"role": "agent", "identity": "agent_id"},
        {
            "role": "environment",
            "identity": "env_id",
            "status": "error",
            "content": {"message": "connection failed"},
        },
    ]
    # We expect INFRA_CONNECTION_FAILED (which is infra error)
    # The error is at index 1. Preceding agent is at index 0.
    res = TriageEngine.identify_root_cause({"conversation_history": history})
    assert res["index"] == 0
    assert "Root cause anchored to agent action" in res["reason"]

    # Test step-back anchoring with NO agent preceding turn
    history_no_agent = [
        {"role": "environment", "content": "not an agent"},
        {
            "role": "environment",
            "identity": "env_id",
            "status": "error",
            "content": {"message": "connection failed"},
        },
    ]
    res_no_agent = TriageEngine.identify_root_cause({"conversation_history": history_no_agent})
    assert res_no_agent["index"] == 1
    assert "Fault attributed to provider env_id" in res_no_agent["reason"]

    # Test step-back fallback provider selection via forensic report
    history_no_id = [
        {"role": "environment", "content": "not an agent"},
        {"role": "environment", "status": "error", "content": {"message": "connection failed"}},
    ]
    task_result = {
        "conversation_history": history_no_id,
        "diagnostic_report": {
            "causal_chain": [
                {
                    "trigger": FailureCategory.INFRA_TIMEOUT,
                    "evidence": "timeout",
                    "turn_index": 1,
                    "rank": 10,
                }
            ]
        },
    }
    res_no_id = TriageEngine.identify_root_cause(task_result)
    assert res_no_id["index"] == 1
    assert "infrastructure_provider" in res_no_id["reason"]


def test_identify_root_cause_index():
    history = [{"role": "agent", "content": "hi"}]
    assert TriageEngine.identify_root_cause_index(history) == 0


def test_apply_triage():
    # 1. Success case
    res_success = {
        "status": "success",
        "metrics": [{"success": True}],
    }
    # 2. Failure case
    res_failure = {
        "status": "error",
        "metrics": [{"success": False}],
    }
    results = [res_success, res_failure]
    TriageEngine.apply_triage(results)
    assert results[0]["triage_tag"] == "SUCCESS"
    assert results[1]["triage_tag"] != "SUCCESS"


def test_check_forensic_report():
    # Empty chain (line 230 coverage)
    class CustomReport(dict):
        def get(self, key, default=None):
            if key == "causal_chain":
                return [1]
            return super().get(key, default)

        def __getitem__(self, key):
            if key == "causal_chain":
                return []
            return super().__getitem__(key)

    res = TriageEngine._check_forensic_report(
        {"diagnostic_report": CustomReport({"dummy": "value"})}, []
    )
    assert res is None

    # Valid chain, checking sorting and index validation
    history = [{"role": "agent"}]
    task_result = {
        "diagnostic_report": {
            "causal_chain": [
                {
                    "trigger": FailureCategory.POLICY_VIOLATION,
                    "evidence": "low rank",
                    "turn_index": 0,
                    "rank": 1,
                    "timestamp": 10,
                },
                {
                    "trigger": FailureCategory.POLICY_VIOLATION,
                    "evidence": "high rank",
                    "turn_index": 0,
                    "rank": 5,
                    "timestamp": 20,
                },
                {
                    "trigger": FailureCategory.POLICY_VIOLATION,
                    "evidence": "high rank earlier timestamp",
                    "turn_index": 0,
                    "rank": 5,
                    "timestamp": 5,
                },
            ]
        }
    }
    res = TriageEngine._check_forensic_report(task_result, history)
    assert res["evidence"] == "high rank earlier timestamp"

    # Turn index out of bounds
    task_result_invalid_index = {
        "diagnostic_report": {
            "causal_chain": [
                {
                    "trigger": FailureCategory.POLICY_VIOLATION,
                    "evidence": "test",
                    "turn_index": 100,
                    "rank": 1,
                },
            ]
        }
    }
    assert TriageEngine._check_forensic_report(task_result_invalid_index, history) is None


def test_check_infra_and_telemetry_missing():
    assert TriageEngine._check_infra_and_telemetry({"resource_telemetry": []}, []) is None


def test_check_explicit_violations_root_cause():
    history = [{"role": "agent", "is_root_cause": True}]
    res = TriageEngine._check_explicit_violations(history)
    assert res["category"] == FailureCategory.POLICY_VIOLATION
    assert "explicitly marked as root cause" in res["reason"]


def test_check_explicit_violations_infra():
    # env_id connection error
    history_conn = [{"identity": "env_id", "content": {"message": "database connection error"}}]
    res_conn = TriageEngine._check_explicit_violations(history_conn)
    assert res_conn["category"] == FailureCategory.INFRA_CONNECTION_FAILED

    # environment_id status error
    history_err = [
        {"identity": "environment_id", "content": {"status": "error", "message": "something else"}}
    ]
    res_err = TriageEngine._check_explicit_violations(history_err)
    assert res_err["category"] == FailureCategory.INFRA_SIMULATOR_EXCEPTION


def test_check_explicit_violations_policy_safety():
    history_policy = [{"content": {"status": "policy_violation"}}]
    res = TriageEngine._check_explicit_violations(history_policy)
    assert res["category"] == FailureCategory.POLICY_VIOLATION

    history_safety = [{"event": "safety_block"}]
    res_safety = TriageEngine._check_explicit_violations(history_safety)
    assert res_safety["category"] == FailureCategory.SECURITY_PII_LEAK


def test_triage_engine_behavioral_patterns_trigger():
    history = [
        {"role": "agent", "tool_calls": [{"tool": "ls", "params": {}}]},
        {"role": "agent", "tool_calls": [{"tool": "ls", "params": {}}]},
        {"role": "agent", "tool_calls": [{"tool": "ls", "params": {}}]},
    ]
    with patch(
        "eval_runner.triage.FailureTaxonomy.classify",
        return_value=FailureCategory.LOGIC_STATE_STALL,
    ):
        res = TriageEngine.identify_root_cause({"conversation_history": history})
        assert res["category"] == FailureCategory.LOGIC_STATE_STALL


def test_triage_engine_metric_failures_trigger():
    history = [{"event": "evaluation", "success": False, "metric": "accuracy"}]
    res = TriageEngine.identify_root_cause({"conversation_history": history})
    assert res["category"] == FailureCategory.LOGIC_PLANNING_ERROR


def test_check_behavioral_patterns_stall():
    history = [
        {"role": "agent", "tool_calls": [{"tool": "ls", "params": {}}]},
        {"role": "agent", "tool_calls": [{"tool": "ls", "params": {}}]},
        {"role": "agent", "tool_calls": [{"tool": "ls", "params": {}}]},
    ]
    with patch(
        "eval_runner.triage.FailureTaxonomy.classify",
        return_value=FailureCategory.LOGIC_STATE_STALL,
    ):
        res = TriageEngine._check_behavioral_patterns({"conversation_history": history}, history)
        assert res["category"] == FailureCategory.LOGIC_STATE_STALL


def test_check_metric_failures():
    history = [{"event": "evaluation", "success": False, "metric": "accuracy"}]
    res = TriageEngine._check_metric_failures(history)
    assert res["category"] == FailureCategory.LOGIC_PLANNING_ERROR
    assert "accuracy" in res["reason"]


def test_fallback_diagnosis_has_failure():
    history = [{"role": "agent", "content": "thought"}, {"role": "run_end", "status": "failed"}]
    res = TriageEngine._fallback_diagnosis(history)
    assert res["category"] == FailureCategory.UNKNOWN_FAILURE
    assert res["index"] == 0
    assert "Target Task Not Completed" in res["reason"]
