import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from eval_runner.explainer import explain_trace

def test_explain_trace_valid(tmp_path):
    trace_file = tmp_path / "run.jsonl"
    trace_file.write_text('{"name": "test_event", "context": {"reason": "policy violation", "index": 5, "confidence": 0.9}}\n')
    
    with patch("eval_runner.trace_utils.load_events") as mock_load:
        mock_load.return_value = [{"name": "test_event", "context": {"reason": "policy violation", "index": 5, "confidence": 0.9}}]
        # Patch the origin module's class to ensure all references are intercepted
        with patch("eval_runner.triage.TriageEngine.identify_root_cause") as mock_triage:
            mock_triage.return_value = {
                "index": 5,
                "confidence": 0.9,
                "reason": "Policy violation detected",
                "suggestion": "Review safety policies."
            }
            result = explain_trace(trace_file)
            
            assert result["index"] == 5
            assert result["confidence"] == 0.9
            assert "Policy" in result["root_cause"]
            assert "Review" in result["suggestion"]

def test_explain_trace_invalid_json(tmp_path):
    trace_file = tmp_path / "broken.jsonl"
    trace_file.write_text("invalid json")
    
    result = explain_trace(trace_file)
    assert "Error reading trace" in result["root_cause"]
    assert "Check" in result["suggestion"]

def test_explain_trace_no_suggestion_high_confidence():
    with patch("eval_runner.trace_utils.load_events") as mock_load:
        mock_load.return_value = []
        # Patch the origin module's class
        with patch("eval_runner.triage.TriageEngine.identify_root_cause") as mock_triage:
            mock_triage.return_value = {
                "index": 10,
                "confidence": 0.9,
                "reason": "system error",
                "suggestion": "No specific suggestion found."
            }
            result = explain_trace(Path("fake.jsonl"))
            assert "Check the tool implementation" in result["suggestion"]
