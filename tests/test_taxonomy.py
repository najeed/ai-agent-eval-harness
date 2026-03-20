import pytest
from eval_runner.taxonomy import FailureTaxonomy


def test_taxonomy_classification_logic():
    """Test that FailureTaxonomy correctly classifies different failure patterns."""

    # 1. Test Partial Pass
    task_res_partial = {
        "metrics": [{"success": True}, {"success": False}],
        "conversation_history": [],
    }
    assert FailureTaxonomy.classify(task_res_partial) == "partial_pass"

    # 2. Test Sandbox Breach
    task_res_breach = {
        "metrics": [{"success": False}],
        "conversation_history": [
            {"role": "environment", "content": {"status": "policy_violation"}}
        ],
    }
    assert FailureTaxonomy.classify(task_res_breach) == "sandbox_breach"

    # 3. Test Tool Error
    task_res_tool = {
        "metrics": [{"success": False}],
        "conversation_history": [
            {
                "role": "environment",
                "content": {"status": "error", "error": "file not found"},
            }
        ],
    }
    assert FailureTaxonomy.classify(task_res_tool) == "tool_call_error"

    # 4. Test Timeout
    task_res_timeout = {
        "metrics": [{"success": False}],
        "conversation_history": [{"role": "agent"}] * 10,
    }
    assert FailureTaxonomy.classify(task_res_timeout) == "timeout"

    # 5. Test Hallucination
    task_res_hallucination = {
        "metrics": [{"success": False}],
        "conversation_history": [
            {"role": "agent", "content": "I cannot find the tool 'super_laser'"}
        ],
    }
    assert FailureTaxonomy.classify(task_res_hallucination) == "hallucination"


def test_taxonomy_fix_verification():
    """Explicitly verify the fix for the previous NameError."""
    task_res = {
        "metrics": [{"success": False}],
        "conversation_history": [{"role": "agent", "content": "test"}],
    }
    # This should no longer raise NameError: name 'tax_result' is not defined
    try:
        FailureTaxonomy.classify(task_res)
    except NameError as e:
        pytest.fail(f"FailureTaxonomy.classify raised NameError: {e}")
