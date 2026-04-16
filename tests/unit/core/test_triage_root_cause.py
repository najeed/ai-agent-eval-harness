from eval_runner.triage import Confidence, FailureCategory, TriageEngine


def test_categorize_failure_report():
    """Test categorization when a report already exists."""
    res = {"diagnostic_report": {"root_cause": FailureCategory.INFRA_OOM}}
    assert TriageEngine.categorize_failure(res) == "INFRA_OOM"


def test_identify_root_cause_no_history():
    """Test triage with empty history."""
    res = TriageEngine.identify_root_cause({"conversation_history": []})
    assert res["confidence"] == Confidence.INCONCLUSIVE
    assert "No history" in res["reason"]


def test_identify_root_cause_forensic():
    """Test triage with a forensic report causal chain."""
    history = [{"role": "agent"}, {"role": "env"}]
    res = {
        "conversation_history": history,
        "diagnostic_report": {
            "causal_chain": [
                {"trigger": FailureCategory.SECURITY_PII_LEAK, "turn_index": 0, "rank": 5}
            ]
        },
    }
    rc = TriageEngine.identify_root_cause(res)
    assert rc["index"] == 0
    assert rc["category"] == FailureCategory.SECURITY_PII_LEAK
    assert rc["confidence"] == Confidence.CERTAIN


def test_identify_root_cause_telemetry():
    """Test triage with resource telemetry spikes."""
    history = [{"role": "agent"}, {"event": "tool_result", "status": "error"}]
    res = {
        "conversation_history": history,
        "resource_telemetry": [{"cpu_percent": 99, "memory_percent": 50}],
    }
    rc = TriageEngine.identify_root_cause(res)
    assert rc["index"] == 1
    assert rc["category"] == FailureCategory.INFRA_RESOURCE_EXHAUSTED
    assert "Resource Exhaustion" in rc["reason"]


def test_identify_root_cause_explicit_marker():
    """Test triage with explicit is_root_cause marker."""
    history = [{"role": "agent"}, {"role": "env", "is_root_cause": True}]
    rc = TriageEngine.identify_root_cause(history)
    assert rc["index"] == 1
    assert rc["category"] == FailureCategory.POLICY_VIOLATION
    assert rc["confidence"] == Confidence.CERTAIN


def test_identify_root_cause_step_back():
    """Test Step-Back logic: Anchoring infra error to preceding agent action."""
    history = [
        {"role": "user", "content": "hello"},
        {"role": "agent", "content": "I will run a bad tool"},  # Turn 1
        {
            "identity": "system_id",
            "content": {"status": "error", "message": "Connection refused"},
        },  # Turn 2
    ]
    rc = TriageEngine.identify_root_cause(history)

    # It should identify turn 2 as connection failure but STEP-BACK to turn 1 (agent)
    assert rc["index"] == 1
    assert rc["category"] == FailureCategory.INFRA_CONNECTION_FAILED
    assert "anchored to agent action" in rc["reason"]


def test_identify_root_cause_no_anchor():
    """Test triage identifies provider when no agent anchor exists (e.g. turn 1 failure)."""
    history = [
        {"role": "user", "content": "hi"},
        {"identity": "system_id", "content": {"status": "error", "message": "Connection refused"}},
    ]
    rc = TriageEngine.identify_root_cause(history)
    assert rc["index"] == 1
    assert "Fault attributed to provider" in rc["reason"]


def test_identify_root_cause_safety_block():
    """Test triage for safety block / PII leak."""
    history = [
        {"role": "user", "content": "hi"},
        {"identity": "env_id", "status": "safety_block", "is_root_cause": True},
    ]
    rc = TriageEngine.identify_root_cause(history)
    assert rc["index"] == 1
    # is_root_cause marker defaults to POLICY_VIOLATION in triage.py:283
    assert rc["category"] == FailureCategory.POLICY_VIOLATION


def test_identify_root_cause_metric_failure():
    """Test triage for explicit evaluation metric failures."""
    history = [{"role": "user"}, {"event": "evaluation", "success": False, "metric": "factuality"}]
    rc = TriageEngine.identify_root_cause(history)
    assert rc["index"] == 1
    assert "Baseline Metric Failure" in rc["reason"]


def test_fallback_diagnosis_logic():
    """Test fallback diagnosis when no evidence is found."""
    history = [{"role": "agent", "content": "thought"}, {"role": "run_end", "status": "failed"}]
    rc = TriageEngine.identify_root_cause(history)
    # Should point to agent turn as fallback
    assert rc["index"] == 0
    assert rc["category"] == FailureCategory.UNKNOWN_FAILURE
    assert rc["confidence"] == Confidence.LOW


def test_apply_triage_batch():
    """Test batch application of triage tags."""
    results = [
        {"metrics": [{"success": True}]},
        {
            "metrics": [{"success": False}],
            "conversation_history": [
                {"role": "user"},
                {"identity": "system_id", "content": {"status": "safety_block"}},
            ],
        },
    ]
    TriageEngine.apply_triage(results)
    assert results[0]["triage_tag"] == "SUCCESS"
    assert results[1]["triage_tag"] == "SECURITY_PII_LEAK"


def test_identify_root_cause_index_wrapper():
    """Test backwards compatibility index wrapper."""
    idx = TriageEngine.identify_root_cause_index([{"role": "agent", "is_root_cause": True}])
    assert idx == 0
