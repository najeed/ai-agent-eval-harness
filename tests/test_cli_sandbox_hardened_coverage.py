import pytest
import asyncio
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from eval_runner import cli, tool_sandbox

# ==============================================================================
# CLI.PY - FINAL COVERAGE BRIDGE
# ==============================================================================

def test_cli_evaluate_bridge():
    # Covers line 308: asyncio.run(run_evaluate(args))
    with patch("sys.argv", ["multiagent-eval", "evaluate", "--path", "test.json"]), \
         patch("eval_runner.cli.run_evaluate", new_callable=AsyncMock) as mock_eval:
        try:
            cli.main()
        except SystemExit:
            pass
        assert mock_eval.called

def test_cli_lint_bridge():
    # Covers line 312: handle_lint(args)
    with patch("sys.argv", ["multiagent-eval", "lint", "--path", "test.json"]), \
         patch("eval_runner.cli.handle_lint") as mock_lint:
        cli.main()
        assert mock_lint.called

def test_cli_init_bridge():
    # Covers line 314: handle_init(args)
    with patch("sys.argv", ["multiagent-eval", "init", "--dir", "tmp_init"]), \
         patch("eval_runner.cli.handle_init") as mock_init:
        cli.main()
        assert mock_init.called

def test_cli_list_metrics_bridge(capsys):
    # Covers lines 316-320: Registered Metrics list
    # The command is 'list-metrics'
    with patch("sys.argv", ["multiagent-eval", "list-metrics"]), \
         patch("eval_runner.metrics.MetricRegistry._metrics", {"test_metric": 1}):
        cli.main()
        captured = capsys.readouterr().out
        assert "Registered Metrics" in captured
        assert "test_metric" in captured

def test_cli_install_bridge():
    # Covers line 380: handle_install(args)
    with patch("sys.argv", ["multiagent-eval", "install", "telecom-pack"]), \
         patch("eval_runner.cli.handle_install") as mock_inst:
        cli.main()
        assert mock_inst.called

def test_cli_calibrate_bridge():
    # Covers line 392: handle_calibrate(args)
    with patch("sys.argv", ["multiagent-eval", "calibrate", "--path", "test.jsonl"]), \
         patch("eval_runner.cli.handle_calibrate") as mock_cal:
        cli.main()
        assert mock_cal.called

# ==============================================================================
# TOOL_SANDBOX.PY - FINAL COVERAGE BRIDGE
# ==============================================================================

def test_sandbox_permission_denied():
    # Covers lines 34, 156 (shared_write permission error)
    scenario = {"agent_topology": {"agent1": {"writes": []}}} # No permissions
    sandbox = tool_sandbox.ToolSandbox(scenario)
    result = sandbox.execute("some_tool", {"shared_write": {"path": "ns:key", "value": "val"}}, agent_name="agent1")
    assert result["status"] == "error"
    assert "no write permission" in result["message"]

def test_sandbox_read_permission_denied():
    # Covers line 166 (shared_read permission error)
    # We need the key to exist in registry first
    scenario = {"agent_topology": {"admin": {"writes": ["*"]}, "user": {"reads": []}}}
    sandbox = tool_sandbox.ToolSandbox(scenario)
    sandbox.shared_state.write("admin", "global:secret", "value")
    
    result = sandbox.execute("some_tool", {"shared_read": {"path": "global:secret"}}, agent_name="user")
    assert result["status"] == "error"
    assert "no read permission" in result["message"]

def test_sandbox_policy_violation_bridge():
    # Covers line 134: policy violation amount > limit
    scenario = {
        "policies": {"spend": {"max_limit": 100}},
        "tools": {"spend": {"state_changes": []}}
    }
    sandbox = tool_sandbox.ToolSandbox(scenario)
    result = sandbox.execute("spend", {"amount": 150})
    assert result["status"] == "policy_violation"
    assert "exceeds limit" in result["violation"]

def test_sandbox_match_namespace_branch():
    # Covers lines 51, 54 in _match_namespace
    scenario = {}
    sandbox = tool_sandbox.ToolSandbox(scenario)
    assert sandbox.shared_state._match_namespace("any", "*") is True
    assert sandbox.shared_state._match_namespace("ns", "ns:*") is True
    assert sandbox.shared_state._match_namespace("other", "ns:*") is False
