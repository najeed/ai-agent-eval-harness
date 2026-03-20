import pytest
from pathlib import Path
from unittest.mock import MagicMock
from eval_runner.explainer import explain_trace

def test_explain_trace_valid(tmp_path, monkeypatch):
    trace_file = tmp_path / "run.jsonl"
    trace_file.write_text('{"name": "test_event"}\n')
    
    mock_engine = MagicMock()
    mock_engine.identify_root_cause.return_value = {
        "index": 5,
        "confidence": 0.9,
        "reason": "Policy violation detected",
        "suggestion": "Review safety policies."
    }
    
    # Patch the module-level reference in explainer
    monkeypatch.setattr("eval_runner.explainer.triage.TriageEngine", mock_engine)
    monkeypatch.setattr("eval_runner.explainer.trace_utils.load_events", MagicMock(return_value=[{"name": "test_event"}]))
    
    result = explain_trace(trace_file)
    
    assert result["index"] == 5
    assert result["confidence"] == 0.9
    assert "Policy" in result["root_cause"]
    assert "Review" in result["suggestion"]

def test_explain_trace_load_error(tmp_path, monkeypatch):
    trace_file = tmp_path / "broken.jsonl"
    
    mock_load = MagicMock(side_effect=Exception("Read error"))
    monkeypatch.setattr("eval_runner.explainer.trace_utils.load_events", mock_load)
    
    result = explain_trace(trace_file)
    assert "Error reading trace" in result["root_cause"]
    assert "Check" in result["suggestion"]

def test_explain_trace_no_suggestion_high_confidence(monkeypatch):
    mock_engine = MagicMock()
    mock_engine.identify_root_cause.return_value = {
        "index": 10,
        "confidence": 0.9,
        "reason": "system error",
        "suggestion": "No specific suggestion found."
    }
    
    monkeypatch.setattr("eval_runner.explainer.triage.TriageEngine", mock_engine)
    monkeypatch.setattr("eval_runner.explainer.trace_utils.load_events", MagicMock(return_value=[]))
    
    result = explain_trace(Path("fake.jsonl"))
    # The suggestion should be overridden by explainer logic for "system" reason
    assert "Check the tool implementation" in result["suggestion"]
