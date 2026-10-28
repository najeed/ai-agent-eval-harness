from unittest.mock import MagicMock

from eval_runner.explainer import explain_events, explain_run


def test_explain_events_returns_triage_diagnosis(monkeypatch):
    mock_engine = MagicMock()
    mock_engine.identify_root_cause.return_value = {
        "index": 5,
        "confidence": 0.9,
        "reason": "Policy violation detected",
        "suggestion": "Review safety policies.",
    }

    # Patch the module-level reference in explainer
    monkeypatch.setattr("eval_runner.explainer.triage.TriageEngine", mock_engine)
    result = explain_events([{"name": "test_event"}])

    assert result["index"] == 5
    assert result["confidence"] == 0.9
    assert "Policy" in result["root_cause"]
    assert "Review" in result["suggestion"]


def test_explain_events_uses_authoritative_events(monkeypatch):
    mock_engine = MagicMock()
    mock_engine.identify_root_cause.return_value = {
        "index": 0,
        "confidence": 0.9,
        "reason": "policy violation",
        "suggestion": "Review safety policies.",
    }
    monkeypatch.setattr("eval_runner.explainer.triage.TriageEngine", mock_engine)
    events = [{"event": "policy_rejected", "_seq": 1}]

    result = explain_events(events)

    assert result["root_cause"] == "policy violation"
    mock_engine.identify_root_cause.assert_called_once_with(events)


def test_explain_run_reads_events_from_the_provider(monkeypatch):
    mock_engine = MagicMock()
    mock_engine.identify_root_cause.return_value = {"reason": "failure", "suggestion": "fix"}
    monkeypatch.setattr("eval_runner.explainer.triage.TriageEngine", mock_engine)
    provider = MagicMock()
    provider.get_events.return_value = [{"event": "failure"}]

    result = explain_run("run-1", run_store=provider, context={"tenant_id": "tenant"})

    assert result["root_cause"] == "failure"
    provider.get_events.assert_called_once_with(
        "run-1", offset=0, limit=10_000_000, context={"tenant_id": "tenant"}
    )


def test_explain_events_no_suggestion_high_confidence(monkeypatch):
    mock_engine = MagicMock()
    mock_engine.identify_root_cause.return_value = {
        "index": 10,
        "confidence": 0.9,
        "reason": "system error",
        "suggestion": "No specific suggestion found.",
    }

    monkeypatch.setattr("eval_runner.explainer.triage.TriageEngine", mock_engine)
    result = explain_events([])
    # The suggestion should be overridden by explainer logic for "system" reason
    assert "Check the tool implementation" in result["suggestion"]


def test_explain_events_policy_suggestion(monkeypatch):
    mock_engine = MagicMock()
    mock_engine.identify_root_cause.return_value = {
        "index": 2,
        "confidence": 0.88,
        "reason": "policy violation",
        "suggestion": "No specific suggestion found.",
    }
    monkeypatch.setattr("eval_runner.explainer.triage.TriageEngine", mock_engine)
    result = explain_events([])
    assert "safety policies" in result["suggestion"]


def test_explain_events_low_confidence_fallback(monkeypatch):
    mock_engine = MagicMock()
    mock_engine.identify_root_cause.return_value = {
        "index": 0,
        "confidence": 0.2,
        "reason": "something weird",
        "suggestion": "No specific suggestion found.",
    }
    monkeypatch.setattr("eval_runner.explainer.triage.TriageEngine", mock_engine)
    result = explain_events([])
    assert "Visual Debugger" in result["suggestion"]
