from eval_runner.taxonomy import FailureCategory
from eval_runner.triage import TriageEngine


def test_resource_aware_triage():
    """Verifies that tool errors are correlated with resource spikes."""
    history = [
        {"role": "agent", "tool": "process_video", "event": "tool_call"},
        {"role": "environment", "event": "tool_result", "status": "error", "result": "Signal 9"},
    ]

    # Simulate telemetry showing a memory spike
    result = {
        "conversation_history": history,
        "resource_telemetry": [
            {"timestamp": 12345.6, "cpu_percent": 10, "memory_percent": 98}  # Spike!
        ],
    }

    diagnosis = TriageEngine.identify_root_cause(result)

    # Should identify it as INFRA_RESOURCE_EXHAUSTED because of the telemetry match
    assert diagnosis["category"] == FailureCategory.INFRA_RESOURCE_EXHAUSTED
    assert "Resource Exhaustion" in diagnosis["reason"]
    assert "MEM: 98%" in diagnosis["reason"]


def test_no_false_positive_telemetry():
    """Verifies that normal telemetry doesn't trigger resource exhaustion tag."""
    history = [
        {"role": "agent", "tool": "ls", "event": "tool_call"},
        {
            "role": "environment",
            "event": "tool_result",
            "status": "error",
            "error": "file not found",
        },
    ]

    result = {
        "conversation_history": history,
        "resource_telemetry": [
            {"timestamp": 12345.6, "cpu_percent": 5, "memory_percent": 10}  # Normal
        ],
    }

    diagnosis = TriageEngine.identify_root_cause(result)

    # Should NOT be resource exhausted
    assert diagnosis["category"] != FailureCategory.INFRA_RESOURCE_EXHAUSTED
    # Should be diagnosed as unknown or tool error depending on other analyzers
