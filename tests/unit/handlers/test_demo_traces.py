"""
test_demo_traces.py

Unit tests for the get_demo_trace utility.
Verifies that all defined demo IDs return valid trace structures.
"""

from eval_runner.console.demo_traces import get_demo_trace, DEMO_IDS

def test_get_demo_trace_valid_ids():
    """Verifies that all IDs in DEMO_IDS return a list of events."""
    for run_id in DEMO_IDS:
        trace = get_demo_trace(run_id)
        assert isinstance(trace, list)
        assert len(trace) > 0
        # Check for essential event types in a trace
        events = [e["event"] for e in trace]
        assert "run_start" in events
        assert "run_end" in events

def test_get_demo_trace_invalid_id():
    """Verifies that an unknown ID returns None."""
    assert get_demo_trace("unknown-id") is None

def test_demo_trace_content_quality():
    """Verifies that specific demo traces have realistic content (samples)."""
    # run-loan-risk-fail should have a policy_violation
    fail_trace = get_demo_trace("run-loan-risk-fail")
    events = [e["event"] for e in fail_trace]
    assert "policy_violation" in events
    
    # run-loan-risk-pass should be successful
    pass_trace = get_demo_trace("run-loan-risk-pass")
    assert pass_trace[-1]["status"] == "success"
