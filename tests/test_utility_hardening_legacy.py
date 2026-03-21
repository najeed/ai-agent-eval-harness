import pytest
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from eval_runner import explainer, plugins, triage, mutator, doctor
from eval_runner.console import demo_traces
from eval_runner.adapters import socket_adapter

# ==============================================================================
# EXPLAINER.PY COVERAGE
# ==============================================================================

def test_explain_trace_empty_file(tmp_path):
    trace_path = tmp_path / "empty.jsonl"
    trace_path.write_text("")
    with patch("eval_runner.trace_utils.load_events", return_value=[]):
        result = explainer.explain_trace(trace_path)
        assert result["confidence"] == 0
        assert "No history" in result["root_cause"]

def test_explain_trace_malformed_event(tmp_path):
    # Trigger line 13-16 in explainer.py (Error reading trace)
    with patch("eval_runner.trace_utils.load_events", side_effect=Exception("Read error")):
        result = explainer.explain_trace(tmp_path / "any.jsonl")
        assert "Error reading trace" in result["root_cause"]

# ==============================================================================
# PLUGINS.PY COVERAGE
# ==============================================================================

@pytest.mark.asyncio
async def test_plugin_manager_hook_error():
    manager = plugins.PluginManager()
    class BrokenPlugin(plugins.BaseEvalPlugin):
        def before_evaluation(self, context):
             raise RuntimeError("Crash")
    manager.plugins.append(BrokenPlugin())
    manager.trigger("before_evaluation", {"data": "test"})

def test_plugin_manager_interceptor_error():
    manager = plugins.PluginManager()
    class BadInterceptor(plugins.BaseEvalPlugin):
        def on_register_commands(self, registry):
            raise RuntimeError("Interceptor Crash")
    manager.plugins.append(BadInterceptor())
    result = manager.trigger_interceptor("on_register_commands", {})
    assert result is True

# ==============================================================================
# TRIAGE.PY COVERAGE
# ==============================================================================

def test_triage_engine_no_failures():
    engine = triage.TriageEngine()
    events = [{"event": "run_start"}, {"event": "run_end", "status": "success"}]
    result = engine.identify_root_cause(events)
    assert result["reason"] == "Execution succeeded"

def test_triage_engine_inconclusive():
    engine = triage.TriageEngine()
    events = [{"event": "run_start"}]
    result = engine.identify_root_cause(events)
    assert "Inconclusive" in result["reason"]

def test_triage_engine_safety_block():
    engine = triage.TriageEngine()
    events = [{"event": "run_start"}, {"event": "safety_block", "status": "safety_block", "content": {"message": "Blocked"}}]
    result = engine.identify_root_cause(events)
    assert "Safety block" in result["reason"]

# ==============================================================================
# MUTATOR.PY COVERAGE
# ==============================================================================

def test_mutator_all_types():
    scenario = {"scenario_id": "test", "title": "Title", "tasks": [{"description": "X"}]}
    mutated = mutator.mutate_scenario(scenario, "typo")
    assert "_mutated_typo" in mutated["scenario_id"]

def test_mutator_empty_text():
    assert mutator.mutate_text_with_typos("") == ""

# ==============================================================================
# DOCTOR.PY COVERAGE
# ==============================================================================

@pytest.mark.asyncio
async def test_doctor_agent_unreachable():
    with patch("aiohttp.ClientSession.post", side_effect=Exception("Conn error")):
        reachable = await doctor.check_agent_reachable("http://localhost:9999")
        assert reachable is False

@pytest.mark.asyncio
async def test_doctor_full_diagnostics(capsys):
    from collections import namedtuple
    VersionInfo = namedtuple("VersionInfo", ["major", "minor", "micro"])
    mock_ver = VersionInfo(major=3, minor=7, micro=0)
    
    with patch("sys.version_info", mock_ver), \
         patch("builtins.__import__", side_effect=ImportError("Missing")), \
         patch("pathlib.Path.exists", return_value=False), \
         patch("eval_runner.doctor.check_agent_reachable", return_value=False):
        
        await doctor.run_doctor()
        captured = capsys.readouterr().out
        assert "Python version too old" in captured
        assert "Dependency 'aiohttp' missing" in captured

# ==============================================================================
# CLI.PY INTEGRATION
# ==============================================================================
from eval_runner import cli

def test_cli_main_doctor():
    with patch("sys.argv", ["multiagent-eval", "doctor"]), \
         patch("eval_runner.cli.handle_doctor") as mock_handle:
        cli.main()
        assert mock_handle.called

@pytest.mark.asyncio
async def test_cli_cleanup_runs_older_than():
    args = MagicMock()
    args.days = 1
    args.force = True
    with patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.glob", return_value=[Path("runs/old.jsonl")]), \
         patch("pathlib.Path.stat") as mock_stat, \
         patch("pathlib.Path.unlink") as mock_unlink:
        mock_stat_val = MagicMock()
        mock_stat_val.st_mtime = 0
        mock_stat.return_value = mock_stat_val
        cli.handle_cleanup_runs(args)
        assert mock_unlink.called
