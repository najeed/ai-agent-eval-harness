from eval_runner.taxonomy import (
    BaseForensicAnalyzer,
    FailureCategory,
    FailureTaxonomy,
    ProtocolAnalyzer,
)


def test_diagnose_stall():
    # Hit line 333 (returns result from _check_stall)
    history = [{"role": "agent", "content": f"cmd{i} arg"} for i in range(15)]
    res = FailureTaxonomy._diagnose([], history)
    assert res == FailureCategory.LOGIC_STALL


def test_diagnose_analyzer_exception():
    # Hit lines 349-350
    class BadAnalyzer(BaseForensicAnalyzer):
        def analyze(self, history, task_result=None):
            raise ValueError("Analyzer failed")

    FailureTaxonomy._analyzers.append(BadAnalyzer())
    try:
        res = FailureTaxonomy._diagnose([], [], {})
        assert res == FailureCategory.UNKNOWN_FAILURE
    finally:
        FailureTaxonomy._analyzers.pop()


def test_check_metrics_output_matches():
    # Hit line 380
    metrics = [{"success": False, "metric": "output_matches_regex"}]
    res = FailureTaxonomy._check_metrics(metrics)
    assert res == FailureCategory.LOGIC_PLANNING_ERROR


def test_check_environment_legacy_string_connection():
    # Hit lines 395-397
    history = [{"identity": "system_id", "content": "connection reset by peer"}]
    res = FailureTaxonomy._check_environment(history)
    assert res == FailureCategory.INFRA_CONNECTION_FAILED

    # And string content that doesn't match
    history2 = [{"identity": "system_id", "content": "other string error"}]
    assert FailureTaxonomy._check_environment(history2) is None


def test_check_environment_parity_mismatch():
    # Hit line 431
    history = [{"identity": "env_id", "content": {"status": "error", "error": "parity divergence"}}]
    res = FailureTaxonomy._check_environment(history)
    assert res == FailureCategory.PARITY_STATE_DIVERGENCE


def test_check_agent_calls_not_list():
    # Hit line 467
    history = [{"role": "agent", "tool_calls": "not_a_list"}]
    # Should skip over it without error
    res = FailureTaxonomy._check_agent(history, {"tool_registry": {}})
    assert res is None


def test_check_stall_unchanged_else_block():
    # Hit line 554
    history = [{"role": "agent"}] * 2
    task_result = {"state_snapshots": [{"a": 1}, {"a": 1}, {"a": 2}, {"a": 2}]}
    res = FailureTaxonomy._check_stall(history, task_result)
    assert res is None


def test_check_protocol_violation():
    # Hit line 579
    task_result = {
        "protocol_sequence_required": ["init", "execute"],
        "protocol_sequence": ["init"],  # Missing execute
    }
    res = FailureTaxonomy._check_protocol(task_result)
    assert res == FailureCategory.PARITY_PROTOCOL_VIOLATION


def test_normalize_action_empty_after_strip():
    # Hit line 606
    assert FailureTaxonomy._normalize_action("   ") == ""


def test_protocol_analyzer_no_task_result():
    # Hit line 678
    analyzer = ProtocolAnalyzer()
    assert analyzer.analyze([], None) is None
