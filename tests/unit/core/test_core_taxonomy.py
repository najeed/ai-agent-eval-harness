import importlib
from unittest.mock import patch

import pytest

from eval_runner import taxonomy
from eval_runner.taxonomy import (
    BaseForensicAnalyzer,
    CausalChain,
    DiagnosticResult,
    FailureCategory,
    FailureTaxonomy,
)

importlib.reload(taxonomy)

# --- 1. Base Classification & Category Behavior ---


def test_failure_category_behavior():
    assert str(FailureCategory.SUCCESS) == "success"
    assert FailureCategory.INFRA_OOM.value == "infra_oom"


@pytest.mark.parametrize(
    "signal, metric, expected",
    [
        ({"status": "error", "error": "request timeout"}, "general", FailureCategory.INFRA_TIMEOUT),
        (
            {"status": "error", "error": "connection refused"},
            "general",
            FailureCategory.INFRA_CONNECTION_FAILED,
        ),
        ({"status": "error", "error": "out of memory"}, "general", FailureCategory.INFRA_OOM),
        (
            {"status": "error", "error": "disk quota exceeded"},
            "general",
            FailureCategory.INFRA_DISK_QUOTA,
        ),
        (
            {"status": "error", "error": "docker daemon failure"},
            "general",
            FailureCategory.INFRA_SANDBOX_FAILURE,
        ),
        ("I cannot comply with policy", "general", FailureCategory.LOGIC_REFUSAL),
        ("My SSN is 123-45-6789", "general", FailureCategory.SECURITY_PII_LEAK),
        ({"status": "unauthorized"}, "general", FailureCategory.SECURITY_UNAUTHORIZED_ACCESS),
        ("invalid tool detected", "general", FailureCategory.POLICY_HALLUCINATION),
        ("divergence", "parity_audit", FailureCategory.PARITY_STATE_DIVERGENCE),
        ("mismatch", "state_verification_check", FailureCategory.LOGIC_STATE_MISMATCH),
    ],
)
def test_taxonomy_base_classify(signal, metric, expected):
    metrics = [{"success": False, "metric": metric}]
    history = []
    if isinstance(signal, dict):
        history.append({"identity": "env_id", "content": signal})
    else:
        history.append({"role": "agent", "content": signal})

    result = {"metrics": metrics, "conversation_history": history}
    assert FailureTaxonomy.classify(result) == expected


# --- 2. Advanced Heuristics (Stalls, Loops, Hallucinations) ---


def test_taxonomy_loops_and_stalls():
    # Fuzzy Loop (Near-duplicate)
    h_loop = [
        {"role": "agent", "content": "I will check the file."},
        {"role": "agent", "content": "I will now check the file."},
    ]
    res_loop = {"metrics": [{"success": False}], "conversation_history": h_loop}
    assert FailureTaxonomy.classify(res_loop) == FailureCategory.LOGIC_PLANNING_ERROR

    # Cyclical Loop A -> B -> A
    h_cycle = [
        {"role": "agent", "content": "Action A"},
        {"role": "agent", "content": "Action B"},
        {"role": "agent", "content": "Action A"},
    ]
    res_cycle = {"metrics": [{"success": False}], "conversation_history": h_cycle}
    assert FailureTaxonomy.classify(res_cycle) == FailureCategory.LOGIC_PLANNING_ERROR

    # State Stall (Use unique messages to avoid loop detection)
    res_stall = {
        "metrics": [{"success": False}],
        "conversation_history": [{"role": "agent", "content": f"msg {i}"} for i in range(4)],
        "state_snapshots": ["hash1"] * 4,
    }
    assert FailureTaxonomy.classify(res_stall) == FailureCategory.LOGIC_STATE_STALL


def test_taxonomy_hallucination_registry():
    tool_reg = {"valid_tool": {"parameters": ["p1"]}}
    # Unknown tool
    h1 = [{"role": "agent", "tool_calls": [{"name": "fake", "arguments": {}}]}]
    assert (
        FailureTaxonomy.classify(
            {"metrics": [{"success": False}], "conversation_history": h1, "tool_registry": tool_reg}
        )
        == FailureCategory.POLICY_HALLUCINATION
    )

    # Invalid param
    h2 = [{"role": "agent", "tool_calls": [{"name": "valid_tool", "arguments": {"bad": 1}}]}]
    assert (
        FailureTaxonomy.classify(
            {"metrics": [{"success": False}], "conversation_history": h2, "tool_registry": tool_reg}
        )
        == FailureCategory.POLICY_HALLUCINATION
    )


# --- 3. Forensic Objects (Chain & Result) ---


def test_causal_chain_mechanics():
    chain = CausalChain()
    chain.add(FailureCategory.LOGIC_STALL, "Evidence", turn_index=5, severity="high")
    assert len(chain) == 1
    assert chain[0]["trigger"] == FailureCategory.LOGIC_STALL
    assert chain[0]["severity"] == "high"


def test_diagnostic_result_serialization():
    diag = DiagnosticResult(FailureCategory.SECURITY_PII_LEAK, FailureCategory.SECURITY_PII_LEAK)
    d = diag.to_dict()
    assert d["root_cause"] == "security_pii_leak"
    assert "DiagnosticResult" in repr(diag)


# --- 4. Protocol & Analyzer Extension ---


def test_taxonomy_protocol_enforcement():
    res = {
        "metrics": [{"success": False}],
        "protocol_sequence_required": ["init", "auth"],
        "protocol_sequence": ["init"],  # Missing auth
    }
    assert FailureTaxonomy.classify(res) == FailureCategory.PARITY_PROTOCOL_VIOLATION


def test_taxonomy_custom_analyzer_registration():
    class CustomAnalyzer(BaseForensicAnalyzer):
        def analyze(self, h, res=None):
            return FailureCategory.INFRA_SIMULATOR_EXCEPTION

    with patch.object(FailureTaxonomy, "_analyzers", []):
        FailureTaxonomy.register_analyzer(CustomAnalyzer())
        assert FailureTaxonomy._diagnose([], []) == FailureCategory.INFRA_SIMULATOR_EXCEPTION


# --- 5. Global Entry Points ---


def test_classify_from_events():
    events = [
        {"event": "agent_response", "content": "My SSN is 000-00-0000"},
        {"event": "evaluation", "success": False},
    ]
    assert FailureTaxonomy.classify_from_events(events) == FailureCategory.SECURITY_PII_LEAK
    assert FailureTaxonomy.classify_from_events([]) == FailureCategory.UNKNOWN_FAILURE


# === Ported edge-case coverage ===


def test_causal_chain_timestamp_and_evidence():
    """Verify causal chain records all fields including timestamp."""
    chain = CausalChain()
    chain.add(FailureCategory.LOGIC_STALL, "Agent stuck in loop", turn_index=5, severity="high")
    assert chain[0]["evidence"] == "Agent stuck in loop"
    assert "timestamp" in chain[0]


def test_diagnostic_result_fallback_diagnosis():
    """Verify diagnostic fallback logic for historical auditability."""
    history = [
        {"role": "user", "content": "hello"},
        {"role": "agent", "content": "I am an agent"},
        {"role": "environment", "content": "error"},
    ]
    diag = DiagnosticResult(FailureCategory.LOGIC_STALL, FailureCategory.UNKNOWN_FAILURE)
    fallback = diag._fallback_diagnosis(history)
    assert fallback["index"] == 1
    assert fallback["root_cause"] == "logic_stall"


def test_diagnostic_result_causal_chain():
    """Test diagnostic with populated causal chain."""
    chain = CausalChain()
    chain.add(FailureCategory.SECURITY_PII_LEAK, "SSN Found")
    res = DiagnosticResult(
        FailureCategory.SECURITY_PII_LEAK, FailureCategory.SECURITY_PII_LEAK, chain
    )
    d = res.to_dict()
    assert len(d["causal_chain"]) == 1


def test_check_success_states():
    """Test full success, partial success, and empty metrics."""
    assert (
        FailureTaxonomy._check_success([{"success": True}, {"success": True}])
        == FailureCategory.SUCCESS
    )
    assert (
        FailureTaxonomy._check_success([{"success": True}, {"success": False}])
        == FailureCategory.PARTIAL_PASS
    )
    assert FailureTaxonomy._check_success([]) is None


def test_check_metrics_keyword_mapping():
    """Test explicit metric keyword detection."""
    assert (
        FailureTaxonomy._check_metrics([{"success": False, "metric": "state_verification_check"}])
        == FailureCategory.LOGIC_STATE_MISMATCH
    )
    assert (
        FailureTaxonomy._check_metrics([{"success": False, "metric": "parity_audit"}])
        == FailureCategory.PARITY_STATE_DIVERGENCE
    )
    assert (
        FailureTaxonomy._check_metrics([{"success": False, "metric": "output_matches_regex"}])
        == FailureCategory.LOGIC_PLANNING_ERROR
    )


def test_check_environment_granular_errors():
    """Test various infrastructure error string mappings via identity."""
    assert (
        FailureTaxonomy._check_environment(
            [{"identity": "env_id", "content": {"status": "error", "message": "Out of memory"}}]
        )
        == FailureCategory.INFRA_OOM
    )
    assert (
        FailureTaxonomy._check_environment(
            [
                {
                    "identity": "env_id",
                    "content": {"status": "error", "message": "disk quota exceeded"},
                }
            ]
        )
        == FailureCategory.INFRA_DISK_QUOTA
    )
    assert (
        FailureTaxonomy._check_environment(
            [
                {
                    "identity": "env_id",
                    "content": {"status": "error", "message": "connection refused"},
                }
            ]
        )
        == FailureCategory.INFRA_CONNECTION_FAILED
    )
    assert (
        FailureTaxonomy._check_environment(
            [{"identity": "system_id", "content": {"status": "unauthorized"}}]
        )
        == FailureCategory.SECURITY_UNAUTHORIZED_ACCESS
    )
    assert (
        FailureTaxonomy._check_environment(
            [{"identity": "env_id", "content": {"status": "error", "error": "parity divergence"}}]
        )
        == FailureCategory.PARITY_STATE_DIVERGENCE
    )


def test_check_environment_string_content():
    """Test string-typed content (legacy format) for connection errors."""
    assert (
        FailureTaxonomy._check_environment(
            [{"identity": "system_id", "content": "connection reset by peer"}]
        )
        == FailureCategory.INFRA_CONNECTION_FAILED
    )
    assert (
        FailureTaxonomy._check_environment(
            [{"identity": "system_id", "content": "other string error"}]
        )
        is None
    )


def test_check_agent_refusal_and_pii():
    """Test agent refusal and PII leak detection."""
    assert (
        FailureTaxonomy._check_agent(
            [{"role": "agent", "content": "I cannot comply with this policy"}]
        )
        == FailureCategory.LOGIC_REFUSAL
    )
    assert (
        FailureTaxonomy._check_agent([{"role": "agent", "content": "My SSN is 123-45-6789"}])
        == FailureCategory.SECURITY_PII_LEAK
    )
    assert (
        FailureTaxonomy._check_agent(
            [{"role": "agent", "content": "I am calling an invalid tool now"}]
        )
        == FailureCategory.POLICY_HALLUCINATION
    )


def test_check_agent_tool_calls_not_list():
    """Verify non-list tool_calls is safely skipped."""
    res = FailureTaxonomy._check_agent(
        [{"role": "agent", "tool_calls": "not_a_list"}], {"tool_registry": {}}
    )
    assert res is None


def test_check_stall_turn_threshold():
    """Verify turn count > STALL_THRESHOLD triggers LOGIC_STALL."""
    h_long = [{"role": "agent"}] * FailureTaxonomy.STALL_THRESHOLD
    assert FailureTaxonomy._check_stall(h_long) == FailureCategory.LOGIC_STALL


def test_check_stall_state_delta():
    """Verify static state snapshots trigger LOGIC_STATE_STALL."""
    snapshots = ["snap1", "snap1", "snap1", "snap1"]
    assert (
        FailureTaxonomy._check_stall([], {"state_snapshots": snapshots})
        == FailureCategory.LOGIC_STATE_STALL
    )


def test_check_stall_no_stall():
    """Verify that changing state snapshots don't trigger stall."""
    history = [{"role": "agent"}] * 2
    task_result = {"state_snapshots": [{"a": 1}, {"a": 1}, {"a": 2}, {"a": 2}]}
    assert FailureTaxonomy._check_stall(history, task_result) is None


def test_diagnose_long_history_stall():
    """Verify _diagnose detects LOGIC_STALL via many repeated commands."""
    history = [{"role": "agent", "content": f"cmd{i} arg"} for i in range(15)]
    res = FailureTaxonomy._diagnose([], history)
    assert res == FailureCategory.LOGIC_STALL


def test_diagnose_bad_analyzer_exception():
    """Verify that a crashing analyzer is swallowed gracefully."""

    class BadAnalyzer(BaseForensicAnalyzer):
        def analyze(self, history, task_result=None):
            raise ValueError("Analyzer failed")

    FailureTaxonomy._analyzers.append(BadAnalyzer())
    try:
        res = FailureTaxonomy._diagnose([], [], {})
        assert res == FailureCategory.UNKNOWN_FAILURE
    finally:
        FailureTaxonomy._analyzers.pop()


def test_normalize_action_whitespace():
    """Verify _normalize_action returns empty string for all-whitespace input."""
    assert FailureTaxonomy._normalize_action("   ") == ""


def test_check_protocol_violation_out_of_order():
    """Test out-of-order protocol sequence detection."""
    res = {
        "protocol_sequence_required": ["init", "auth"],
        "protocol_sequence": ["auth", "init"],
    }
    assert FailureTaxonomy._check_protocol(res) == FailureCategory.PARITY_PROTOCOL_VIOLATION


def test_detect_loops_repeated_command_stall():
    """Test that repeated normalized commands trigger LOGIC_STATE_STALL."""
    history = [
        {"role": "agent", "content": "ls -l /tmp"},
        {"role": "agent", "content": "ls -la /var"},
        {"role": "agent", "content": "ls ."},
    ]
    assert FailureTaxonomy._detect_loops(history) == FailureCategory.LOGIC_STATE_STALL


def test_protocol_analyzer_no_task_result():
    """ProtocolAnalyzer returns None when task_result is None."""
    from eval_runner.taxonomy import ProtocolAnalyzer

    analyzer = ProtocolAnalyzer()
    assert analyzer.analyze([], None) is None


def test_classify_from_events_tool_result_sandbox():
    """Verify infrastructure failure classification from tool_result events."""
    events = [
        {"event": "run_start", "scenario": "test"},
        {"event": "agent_response", "content": "I call a tool"},
        {
            "event": "tool_result",
            "identity": "system_id",
            "status": "error",
            "result": "Docker socket not found",
        },
    ]
    assert FailureTaxonomy.classify_from_events(events) == FailureCategory.INFRA_SANDBOX_FAILURE


def test_classify_output_fabrication():
    """Verify claimed tool_result not matching env evidence triggers hallucination."""
    history_fail = [{"role": "agent", "content": "The tool_result was 'Access Granted'"}]
    result_fail = {
        "metrics": [{"success": False}],
        "conversation_history": history_fail,
        "events": [{"role": "environment", "content": "Access Denied"}],
    }
    assert FailureTaxonomy.classify(result_fail) == FailureCategory.POLICY_HALLUCINATION


def test_taxonomy_success_full():
    """Verify full success classification."""
    result = {"metrics": [{"success": True}], "conversation_history": []}
    assert FailureTaxonomy.classify(result) == FailureCategory.SUCCESS
