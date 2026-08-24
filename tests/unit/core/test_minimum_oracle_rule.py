"""
A2: Minimum-oracle rule + zero-assertions invalidation.

Compile-time:
  - A workflow node without any oracle assertion source (success_criteria,
    state_hygiene rules, expected_outcome) is rejected by compile_workflow
    with a NO_ASSERTIONS violation.

Runtime backstop:
  - calculate_metrics on a node with zero oracle rows yields
    evaluation_valid=False, triage_tag=EVALUATION_INVALID, and an explicit
    oracle_coverage metric row with reason NO_ASSERTIONS.
"""

from typing import Any

import pytest

from eval_runner.execution_ir import PlanValidationError, compile_workflow
from eval_runner.session_components.metrics_calculator import (
    EVALUATION_INVALID,
    SessionMetricsCalculator,
)


def _scenario_with_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "aes_version": 1.4,
        "workflow": {
            "nodes": [node],
            "edges": [],
        },
    }


# ---------------------------------------------------------------------------
# Compile-time minimum-oracle rule
# ---------------------------------------------------------------------------


def test_compile_rejects_zero_assertion_node():
    scenario = _scenario_with_node({"id": "bare", "task_description": "do things"})
    with pytest.raises(PlanValidationError, match="NO_ASSERTIONS"):
        compile_workflow(scenario)


def test_compile_accepts_success_criteria_oracle():
    scenario = _scenario_with_node(
        {
            "id": "with_criteria",
            "task_description": "do things",
            "success_criteria": [{"metric": "task_completion", "threshold": 1.0}],
        }
    )
    plan = compile_workflow(scenario)
    assert "with_criteria" in plan.nodes


def test_compile_accepts_state_hygiene_oracle():
    scenario = _scenario_with_node(
        {
            "id": "with_hygiene",
            "task_description": "do things",
            "state_hygiene": {"rules": [{"path": "balance", "op": "exists"}]},
        }
    )
    plan = compile_workflow(scenario)
    assert "with_hygiene" in plan.nodes


def test_compile_accepts_expected_outcome_oracle():
    scenario = _scenario_with_node(
        {
            "id": "with_outcome",
            "task_description": "do things",
            "expected_outcome": [{"target": "message", "expected": "done"}],
        }
    )
    plan = compile_workflow(scenario)
    assert "with_outcome" in plan.nodes


def test_compile_rejects_empty_assertion_containers():
    # Empty containers are NOT oracles — they must not bypass the rule.
    scenario = _scenario_with_node(
        {
            "id": "empty_all",
            "success_criteria": [],
            "expected_outcome": [],
            "state_hygiene": {"rules": []},
        }
    )
    with pytest.raises(PlanValidationError, match="empty_all"):
        compile_workflow(scenario)


def test_compile_error_names_the_offending_nodes():
    scenario = _scenario_with_node(
        {
            "id": "guilty_node",
            "task_description": "x",
            "state_hygiene": {"rules": [{"path": "p", "op": "eq", "expected": 1}]},
        }
    )
    # Add a second node lacking any oracle via explicit edge chain.
    scenario["workflow"]["nodes"].append({"id": "also_guilty"})
    scenario["workflow"]["edges"] = [
        {"from": "guilty_node", "to": "also_guilty"},
    ]
    with pytest.raises(PlanValidationError) as excinfo:
        compile_workflow(scenario)
    msg = str(excinfo.value)
    assert "also_guilty" in msg
    assert "guilty_node" not in msg.split("nodes declare")[1].split(":")[1]


# ---------------------------------------------------------------------------
# Runtime zero-assertions backstop
# ---------------------------------------------------------------------------


class _StubSessionManager:
    """Minimal session-manager surface used by SessionMetricsCalculator."""

    def __init__(self):
        self.protocol_sequence = []
        self.state_snapshots = []
        self.resource_telemetry = []
        self.session_metadata = {}
        self.scenario = {}
        self.max_turns = 10
        self.plugin_manager = type("PluginManagerStub", (), {"provenance_map": {}})()
        self.forensics = type("ForensicsStub", (), {"resource_telemetry": []})()

    def _extract_tool_registry(self):
        return {}


@pytest.mark.asyncio
async def test_calculate_metrics_zero_assertions_is_invalid():
    calc = SessionMetricsCalculator(_StubSessionManager())
    node = {"id": "oracle_free", "task_description": "nothing to verify"}

    result = await calc.calculate_metrics(
        node=node,
        attempt_number=1,
        turns=2,
        history=[],
        sandbox=type("SandboxStub", (), {"state": {}})(),
        actions={"used_tools": []},
    )

    assert result["evaluation_valid"] is False
    assert result["triage_tag"] == EVALUATION_INVALID
    assert any("NO_ASSERTIONS" in r for r in result["invalid_reasons"])
    oracle_rows = [m for m in result["metrics"] if m.get("reason") == "NO_ASSERTIONS"]
    assert len(oracle_rows) == 1
    assert oracle_rows[0]["status"] == EVALUATION_INVALID
    assert oracle_rows[0]["success"] is False


@pytest.mark.asyncio
async def test_calculate_metrics_with_criteria_remains_valid():
    from eval_runner import metrics as metrics_module

    @metrics_module.MetricRegistry.register("always_pass_stub")
    def _always_pass(**kwargs):
        return 1.0

    calc = SessionMetricsCalculator(_StubSessionManager())
    node = {
        "id": "has_oracle",
        "success_criteria": [{"metric": "always_pass_stub", "threshold": 1.0}],
    }

    result = await calc.calculate_metrics(
        node=node,
        attempt_number=1,
        turns=1,
        history=[],
        sandbox=type("SandboxStub", (), {"state": {}})(),
        actions={"used_tools": []},
    )

    assert result["evaluation_valid"] is True
    assert "triage_tag" not in result
    assert all(m.get("status") != EVALUATION_INVALID for m in result["metrics"])
