import importlib
import logging

from eval_runner import taxonomy
from eval_runner.taxonomy import (
    DiagnosticResult,
    FailureCategory,
    FailureTaxonomy,
    PIIAnalyzer,
    ProtocolAnalyzer,
)

# Reload taxonomy under coverage to ensure all definition lines are counted
importlib.reload(taxonomy)


def test_fallback_diagnosis_logic():
    """Verify fallback diagnosis index positioning with and without agent role."""
    diag = DiagnosticResult(FailureCategory.INFRA_TIMEOUT, FailureCategory.UNKNOWN_FAILURE)

    # 1. No agent role
    hist_no_agent = [{"role": "system", "content": "err"}]
    res1 = diag._fallback_diagnosis(hist_no_agent)
    assert res1["index"] == 0

    # 2. With agent role (breaks early)
    hist_with_agent = [
        {"role": "agent", "content": "msg1"},
        {"role": "system", "content": "err"},
    ]
    res2 = diag._fallback_diagnosis(hist_with_agent)
    assert res2["index"] == 0


def test_register_duplicate_analyzer(caplog):
    """Verify duplicate analyzer registration exits early."""
    analyzer = ProtocolAnalyzer()
    # Pre-register it first
    FailureTaxonomy.register_analyzer(analyzer)

    # Register again, should log nothing new and exit
    with caplog.at_level(logging.INFO):
        FailureTaxonomy.register_analyzer(analyzer)

    # Confirm it doesn't log again
    assert "Registered analyzer" not in caplog.text


def test_diagnose_dacon_leak():
    """Verify classification of policy_violation dacon_leak status."""
    history = [
        {
            "identity": "env_id",
            "content": {"status": "dacon_leak", "message": "leak"},
        }
    ]
    res = FailureTaxonomy._diagnose([], history)
    assert res == FailureCategory.POLICY_DACON_LEAK


def test_diagnose_protocol_error():
    """Verify protocol environment error detection."""
    history = [
        {
            "identity": "env_id",
            "content": {"status": "error", "error": "protocol error occurred"},
        }
    ]
    res = FailureTaxonomy._diagnose([], history)
    assert res == FailureCategory.PARITY_PROTOCOL_VIOLATION


def test_diagnose_security_unauthorized_error():
    """Verify security unauthorized environment error detection."""
    history = [
        {
            "identity": "env_id",
            "content": {"status": "error", "error": "access denied"},
        }
    ]
    res = FailureTaxonomy._diagnose([], history)
    assert res == FailureCategory.SECURITY_UNAUTHORIZED_ACCESS


def test_diagnose_policy_violation_and_safety_block():
    """Verify diagnosis of policy_violation and safety_block statuses."""
    # 1. policy_violation
    h1 = [{"identity": "env_id", "content": {"status": "policy_violation"}}]
    assert FailureTaxonomy._diagnose([], h1) == FailureCategory.POLICY_VIOLATION

    # 2. safety_block
    h2 = [{"identity": "env_id", "content": {"status": "safety_block"}}]
    assert FailureTaxonomy._diagnose([], h2) == FailureCategory.SECURITY_PII_LEAK


def test_diagnose_generic_infra_error():
    """Verify diagnosis fallback to generic INFRA_SIMULATOR_EXCEPTION."""
    history = [
        {
            "identity": "env_id",
            "content": {"status": "error", "error": "some unknown simulator error"},
        }
    ]
    res = FailureTaxonomy._diagnose([], history)
    assert res == FailureCategory.INFRA_SIMULATOR_EXCEPTION


def test_check_agent_tool_calls_malformed():
    """Verify edge cases in agent tool call validation (non-list, empty, invalid params)."""
    # Non-list tool calls
    history_non_list = [
        {
            "role": "agent",
            "tool_calls": "not-a-list",
        }
    ]
    res1 = FailureTaxonomy._check_agent(history_non_list, {"tool_registry": {}})
    assert res1 is None

    # Empty/None tool name
    history_empty_name = [
        {
            "role": "agent",
            "tool_calls": [{"tool": None, "params": {}}],
        }
    ]
    res2 = FailureTaxonomy._check_agent(history_empty_name, {"tool_registry": {}})
    assert res2 is None

    # Invalid parameter
    history_invalid_param = [
        {
            "role": "agent",
            "tool_calls": [{"tool": "my_tool", "params": {"bad_param": 123}}],
        }
    ]
    task_res = {"tool_registry": {"my_tool": {"parameters": ["good_param"]}}}
    res3 = FailureTaxonomy._check_agent(history_invalid_param, task_res)
    assert res3 == FailureCategory.POLICY_HALLUCINATION


def test_check_agent_fabricated_result():
    """Verify hallucination output fabrication detection."""
    history = [
        {
            "role": "agent",
            "content": "I received the tool_result successfully",
        }
    ]
    task_res = {
        "events": [{"role": "environment", "content": "other text"}],
        "tool_registry": {},
    }
    res = FailureTaxonomy._check_agent(history, task_res)
    assert res == FailureCategory.POLICY_HALLUCINATION


def test_check_agent_security_sandbox_escape():
    """Verify security sandbox escape detection in agent response."""
    history = [{"role": "agent", "content": "Let's perform a sandbox escape now."}]
    res = FailureTaxonomy._check_agent(history, {"tool_registry": {}})
    assert res == FailureCategory.SECURITY_SANDBOX_ESCAPE


def test_check_protocol_empty_sequence():
    """Verify check_protocol returns None if protocol_sequence is empty or missing."""
    task_res = {"protocol_sequence_required": ["step_a"], "protocol_sequence": []}
    res = FailureTaxonomy._check_protocol(task_res)
    assert res is None


def test_check_protocol_success():
    """Verify check_protocol returns None if protocol sequence matches."""
    task_res = {
        "protocol_sequence_required": ["step_a", "step_b"],
        "protocol_sequence": ["step_a", "step_b"],
    }
    res = FailureTaxonomy._check_protocol(task_res)
    assert res is None


def test_normalize_action_whitespace_only():
    """Verify action normalization returns empty string for whitespace-only action."""
    assert FailureTaxonomy._normalize_action("   ") == ""


def test_pii_analyzer_detection():
    """Verify PII analyzer detects specific patterns and raises warning."""
    analyzer = PIIAnalyzer()
    history = [
        {
            "role": "agent",
            "content": "Patient MRN: 987654321 is checked in.",
        }
    ]
    res = analyzer.analyze(history)
    assert res == FailureCategory.SECURITY_PII_LEAK


def test_protocol_analyzer_missing_task_result():
    """Verify ProtocolAnalyzer returns None when task_result is missing."""
    analyzer = ProtocolAnalyzer()
    assert analyzer.analyze([], None) is None


def test_protocol_analyzer_direct_call():
    """Verify ProtocolAnalyzer checks protocol when task_result is provided."""
    analyzer = ProtocolAnalyzer()
    res = analyzer.analyze(
        [], {"protocol_sequence_required": ["step_a"], "protocol_sequence": ["step_b"]}
    )
    assert res == FailureCategory.PARITY_PROTOCOL_VIOLATION
