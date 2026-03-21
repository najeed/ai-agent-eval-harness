import pytest
import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from eval_runner import explainer, plugins, triage, mutator, doctor
from eval_runner.console import demo_traces
from eval_runner.adapters import socket_adapter

# ==============================================================================
# EXPLAINER.PY COVERAGE (Target: Lines 33, 40, 41, 45)
# ==============================================================================

def test_explain_trace_empty_file(tmp_path):
    trace_path = tmp_path / "empty.jsonl"
    trace_path.write_text("")
    with patch("eval_runner.trace_utils.load_events", return_value=[]):
        result = explainer.explain_trace(trace_path)
        assert result["confidence"] == 0
        assert "No history" in result["root_cause"]

def test_explain_trace_malformed_event(tmp_path):
    trace_path = tmp_path / "error.jsonl"
    trace_path.write_text('bad json')
    # Trigger line 13-16 in explainer.py (Error reading trace)
    with patch("eval_runner.trace_utils.load_events", side_effect=Exception("Read error")):
        result = explainer.explain_trace(trace_path)
        assert "Error reading trace" in result["root_cause"]
        assert "suggestion" in result

# ==============================================================================
# PLUGINS.PY COVERAGE (Target: Lifecycle Hooks & Error Handling)
# ==============================================================================

@pytest.mark.asyncio
async def test_plugin_manager_hook_error():
    manager = plugins.PluginManager()
    
    class BrokenPlugin(plugins.BaseEvalPlugin):
        def before_evaluation(self, context):
             raise RuntimeError("Crash")
             
    manager.plugins.append(BrokenPlugin())
    # Line 181-183: Error handling in trigger()
    manager.trigger("before_evaluation", {"data": "test"})
    # Should not raise exception, but print error

def test_plugin_manager_interceptor_error():
    manager = plugins.PluginManager()
    class BadInterceptor(plugins.BaseEvalPlugin):
        def on_register_commands(self, registry):
            raise RuntimeError("Interceptor Crash")
    
    manager.plugins.append(BadInterceptor())
    # Line 198-199: Error handling in trigger_interceptor()
    result = manager.trigger_interceptor("on_register_commands", {})
    assert result is True

# ==============================================================================
# TRIAGE.PY COVERAGE (Target: Decision Tree & Edge Cases)
# ==============================================================================

def test_triage_engine_no_failures():
    engine = triage.TriageEngine()
    events = [{"event": "run_start"}, {"event": "run_end", "status": "success"}]
    # Line 275-276: Execution succeeded
    result = engine.identify_root_cause(events)
    assert result["reason"] == "Execution succeeded"
    assert result["confidence"] == 1.0

def test_triage_engine_inconclusive():
    engine = triage.TriageEngine()
    events = [{"event": "run_start"}] # No end event
    # Line 277-281: Inconclusive
    result = engine.identify_root_cause(events)
    assert "Inconclusive" in result["reason"]

def test_triage_engine_safety_block():
    engine = triage.TriageEngine()
    events = [
        {"event": "run_start"},
        {"event": "safety_block", "status": "safety_block", "content": {"message": "Blocked"}}
    ]
    # Line 110-119: Safety block
    result = engine.identify_root_cause(events)
    assert "Safety block" in result["reason"]
    assert result["confidence"] == 1.0

# ==============================================================================
# MUTATOR.PY COVERAGE (Target: Mutation Types & Validation)
# ==============================================================================

def test_mutator_all_types():
    scenario = {
        "scenario_id": "test_id",
        "title": "Test Title",
        "tasks": [{"description": "Check the status."}]
    }
    # Lines 77, 79: scenario_id and title updates
    mutated = mutator.mutate_scenario(scenario, "typo")
    assert "_mutated_typo" in mutated["scenario_id"]
    assert "(Mutated: typo)" in mutated["title"]

def test_mutator_empty_text():
    # Line 15: Handling of empty text in typo mutator
    res = mutator.mutate_text_with_typos("")
    assert res == ""

# ==============================================================================
# DOCTOR.PY COVERAGE (Target: Diagnostics & Failures)
# ==============================================================================

@pytest.mark.asyncio
async def test_doctor_agent_unreachable():
    # Line 18-19: check_agent_reachable failure handling
    with patch("aiohttp.ClientSession.post", side_effect=Exception("Conn error")):
        reachable = await doctor.check_agent_reachable("http://localhost:9999")
        assert reachable is False

# ==============================================================================
# DEMO_TRACES.PY COVERAGE (Target: Scenario Specifics)
# ==============================================================================

def test_get_demo_trace_handling():
    # Line 7: run-loan-risk-fail
    res_fail = demo_traces.get_demo_trace("run-loan-risk-fail")
    assert res_fail[0]["run_id"] == "run-loan-risk-fail"
    
    # Line 61: run-loan-risk-pass
    res_pass = demo_traces.get_demo_trace("run-loan-risk-pass")
    assert res_pass[0]["run_id"] == "run-loan-risk-pass"
    
    # Line 109: None
    assert demo_traces.get_demo_trace("unknown") is None

# ==============================================================================
# SOCKET ADAPTER COVERAGE (Target: adapters/__init__.py edge cases)
# ==============================================================================

@pytest.mark.asyncio
async def test_socket_adapter_empty_response():
    # Line 78: Handling of empty response_data
    mock_reader = AsyncMock()
    mock_reader.readline.return_value = b""
    mock_writer = AsyncMock()
    
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        result = await socket_adapter({"task": "test"}, "tcp:localhost:1234")
        assert result == {}

@pytest.mark.asyncio
async def test_socket_adapter_close_error():
    # Lines 84, 85: Exception handling in finally block
    mock_reader = AsyncMock()
    mock_reader.readline.return_value = b'{"status": "ok"}\n'
    mock_writer = AsyncMock()
    mock_writer.wait_closed.side_effect = Exception("Socket error")
    
    with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
        result = await socket_adapter({"task": "test"}, "tcp:localhost:1234")
        assert result == {"status": "ok"}
