from unittest.mock import AsyncMock, patch

import pytest

from eval_runner import cli, tool_sandbox

# ==============================================================================
# CLI.PY - FINAL COVERAGE BRIDGE
# ==============================================================================


def test_cli_evaluate_bridge():
    # Covers line 308: asyncio.run(run_evaluate(args))
    with (
        patch("sys.argv", ["agentv", "evaluate", "--path", "test.json"]),
        patch(
            "eval_runner.handlers.evaluation.handle_evaluate",
            new_callable=AsyncMock,
            return_value=0,
        ) as mock_eval,
    ):
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 0
        assert mock_eval.called


def test_cli_lint_bridge():
    # Covers line 312: handle_lint(args)
    with (
        patch("sys.argv", ["agentv", "lint", "--path", "test.json"]),
        patch(
            "eval_runner.handlers.scenarios.handle_lint", new_callable=AsyncMock, return_value=0
        ) as mock_lint,
    ):
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 0
        assert mock_lint.called


def test_cli_init_bridge():
    # Covers line 314: handle_init(args)
    with (
        patch("sys.argv", ["agentv", "init", "--dir", "tmp_init"]),
        patch(
            "eval_runner.handlers.environment.handle_init", new_callable=AsyncMock, return_value=0
        ) as mock_init,
    ):
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 0
        assert mock_init.called


def test_cli_list_metrics_bridge(capsys):
    # Covers lines 316-320: Registered Metrics list
    # The command is 'list-metrics'
    with (
        patch("sys.argv", ["agentv", "list-metrics"]),
        patch("eval_runner.metrics.MetricRegistry._metrics", {"test_metric": 1}),
    ):
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 0
    captured = capsys.readouterr().out
    assert "Registered Evaluation Metrics" in captured
    assert "test_metric" in captured


def test_cli_install_bridge():
    # Covers line 380: handle_install(args)
    with (
        patch("sys.argv", ["agentv", "install", "telecom-pack"]),
        patch(
            "eval_runner.handlers.environment.handle_install",
            new_callable=AsyncMock,
            return_value=0,
        ) as mock_inst,
    ):
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 0
        assert mock_inst.called


def test_cli_calibrate_bridge():
    # Covers line 392: handle_calibrate(args)
    with (
        patch("sys.argv", ["agentv", "calibrate", "--run-id", "test-run"]),
        patch(
            "eval_runner.handlers.analysis.handle_calibrate", new_callable=AsyncMock, return_value=0
        ) as mock_cal,
    ):
        with pytest.raises(SystemExit) as e:
            cli.main()
        assert e.value.code == 0
        assert mock_cal.called


# ==============================================================================
# TOOL_SANDBOX.PY - FINAL COVERAGE BRIDGE
# ==============================================================================


@pytest.mark.asyncio
async def test_sandbox_permission_denied():
    # Covers lines 34, 156 (shared_write permission error)
    scenario = {"agent_topology": {"agent1": {"writes": []}}}  # No permissions
    sandbox = tool_sandbox.ToolSandbox(scenario)
    result = await sandbox.execute(
        "some_tool", {"shared_write": {"path": "ns:key", "value": "val"}}, agent_name="agent1"
    )
    assert result["status"] == "error"
    assert "no write permission" in result["message"]


@pytest.mark.asyncio
async def test_sandbox_read_permission_denied():
    # Covers line 166 (shared_read permission error)
    # We need the key to exist in registry first
    scenario = {"agent_topology": {"admin": {"writes": ["*"]}, "user": {"reads": []}}}
    sandbox = tool_sandbox.ToolSandbox(scenario)
    sandbox.shared_state.write("admin", "global:secret", "value")

    result = await sandbox.execute(
        "some_tool", {"shared_read": {"path": "global:secret"}}, agent_name="user"
    )
    assert result["status"] == "error"
    assert "no read permission" in result["message"]


@pytest.mark.asyncio
async def test_sandbox_policy_violation_bridge():
    # Covers line 134: policy violation amount > limit
    scenario = {
        "policies": {"spend": {"max_limit": 100}},
        "tools": {"spend": {"state_changes": []}},
    }
    sandbox = tool_sandbox.ToolSandbox(scenario)
    result = await sandbox.execute("spend", {"amount": 150})
    assert result["status"] == "policy_violation"
    assert "exceeds limit" in result["violation"]


def test_sandbox_match_namespace_branch():
    # Covers lines 51, 54 in _match_namespace
    scenario = {}
    sandbox = tool_sandbox.ToolSandbox(scenario)
    assert sandbox.shared_state._match_namespace("any", "*") is True
    assert sandbox.shared_state._match_namespace("ns", "ns:*") is True
    assert sandbox.shared_state._match_namespace("other", "ns:*") is False
