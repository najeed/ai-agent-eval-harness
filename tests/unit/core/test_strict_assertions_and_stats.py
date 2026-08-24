"""
Unit tests for strict assertion semantics (P0 #4/#5) and standardized
scoring statistics (P0 #8).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from eval_runner.session_components.metrics_calculator import (
    EVALUATION_INVALID,
    SessionMetricsCalculator,
)
from eval_runner.statistics import (
    compute_attempt_statistics,
    pass_at_k_estimator,
    wilson_interval,
)


class _NullBus:
    def emit(self, *args, **kwargs):
        pass


def _fake_session():
    return SimpleNamespace(
        event_bus=_NullBus(),
        plugin_manager=SimpleNamespace(provenance_map={}),
        identifier="test_case",
        max_turns=10,
        protocol_sequence=[],
        state_snapshots=[],
        resource_telemetry=[],
        scenario={"metadata": {}},
        session_metadata={},
        forensics=SimpleNamespace(resource_telemetry=[]),
        _extract_tool_registry=lambda: {},
    )


def _sandbox(state=None):
    return SimpleNamespace(state=state or {})


# ---------------------------------------------------------------------------
# Strict assertion semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_metric_produces_evaluation_invalid_not_skip():
    calc = SessionMetricsCalculator(_fake_session())
    node = {
        "id": "n1",
        "success_criteria": [{"metric": "does_not_exist_metric", "threshold": 0.8}],
    }
    result = await calc.calculate_metrics(node, 1, 1, [], _sandbox(), {"used_tools": []})

    assert result["evaluation_valid"] is False
    assert result["triage_tag"] == EVALUATION_INVALID
    assert any("does_not_exist_metric" in r for r in result["invalid_reasons"])
    row = result["metrics"][0]
    assert row["status"] == EVALUATION_INVALID
    assert row["success"] is False


@pytest.mark.asyncio
async def test_evaluator_exception_produces_evaluation_invalid():
    from eval_runner import metrics as metrics_pkg

    calc = SessionMetricsCalculator(_fake_session())

    def _boom(**kwargs):
        raise RuntimeError("verifier unavailable")

    metrics_pkg.MetricRegistry.register("explosive_metric")(_boom)
    try:
        node = {
            "id": "n1",
            "success_criteria": [{"metric": "explosive_metric", "threshold": 0.5}],
        }
        result = await calc.calculate_metrics(node, 1, 1, [], _sandbox(), {"used_tools": []})
    finally:
        metrics_pkg.MetricRegistry._metrics.pop("explosive_metric", None)
        metrics_pkg.MetricRegistry._provenance.pop("explosive_metric", None)

    assert result["evaluation_valid"] is False
    assert result["triage_tag"] == EVALUATION_INVALID
    assert any("explosive_metric" in r for r in result["invalid_reasons"])
    assert result["metrics"][0]["status"] == EVALUATION_INVALID


@pytest.mark.asyncio
async def test_malformed_criterion_is_evaluation_invalid():
    calc = SessionMetricsCalculator(_fake_session())
    node = {"id": "n1", "success_criteria": [{"threshold": 0.9}]}  # no metric key
    result = await calc.calculate_metrics(node, 1, 1, [], _sandbox(), {"used_tools": []})
    assert result["evaluation_valid"] is False
    assert any("Malformed" in r for r in result["invalid_reasons"])


@pytest.mark.asyncio
async def test_required_hygiene_failure_gates_node():
    calc = SessionMetricsCalculator(_fake_session())
    node = {
        "id": "n1",
        "state_hygiene": {
            "rules": [
                {"path": "order.status", "op": "eq", "expected": "approved"},
                {"path": "audit.trail", "op": "exists"},
            ]
        },
    }
    sandbox = _sandbox({"order": {"status": "denied"}})
    result = await calc.calculate_metrics(node, 1, 1, [], sandbox, {"used_tools": []})

    assert result["evaluation_valid"] is False
    rows = result["state_hygiene"]
    assert rows[0]["success"] is False
    assert rows[0]["actual"] == "denied"  # evidence carries actual value
    assert any("state_hygiene" in r for r in result["invalid_reasons"])


@pytest.mark.asyncio
async def test_informational_hygiene_failure_does_not_gate():
    calc = SessionMetricsCalculator(_fake_session())
    node = {
        "id": "n1",
        "state_hygiene": {
            "rules": [
                {
                    "path": "optional.flag",
                    "op": "exists",
                    "severity": "informational",
                }
            ]
        },
    }
    result = await calc.calculate_metrics(node, 1, 1, [], _sandbox({}), {"used_tools": []})
    assert result["evaluation_valid"] is True
    assert result["state_hygiene"][0]["success"] is False


@pytest.mark.asyncio
async def test_passing_criteria_stay_valid():

    calc = SessionMetricsCalculator(_fake_session())
    node = {
        "id": "n1",
        "success_criteria": [{"metric": "generic_accuracy", "threshold": 0.5}],
    }
    history = [{"role": "agent", "content": "All done and correct"}]
    result = await calc.calculate_metrics(node, 1, 1, history, _sandbox(), {"used_tools": []})
    assert result["evaluation_valid"] is True
    assert result["metrics"][0]["success"] is True


# ---------------------------------------------------------------------------
# Statistics semantics
# ---------------------------------------------------------------------------


def test_pass_at_k_estimator_matches_reference_values():
    # HumanEval reference: n=10 samples, c successes, k requested
    assert pass_at_k_estimator(1, 1, 1) == 1.0
    assert pass_at_k_estimator(1, 0, 1) == 0.0
    assert pass_at_k_estimator(2, 2, 2) == 1.0
    assert pass_at_k_estimator(2, 1, 2) == 1.0  # at least one of all 2 passes
    assert pass_at_k_estimator(10, 5, 1) == pytest.approx(0.5)
    assert pass_at_k_estimator(10, 5, 10) == 1.0
    with pytest.raises(ValueError):
        pass_at_k_estimator(3, 4, 1)


def test_statistics_separate_materially_different_semantics():
    attempts = [["ok"], ["ok"], ["bad"], ["bad"]]
    stats = compute_attempt_statistics(attempts, lambda a: a[0] == "ok", requested_k=4)

    assert stats["executed_attempts"] == 4
    assert stats["successful_attempts"] == 2
    assert stats["attempt_success_rate"] == 0.5
    assert stats["pass_at_k"] == 1.0  # P(at least one of the 4 passes) with c=2
    assert stats["all_pass"] is False
    assert stats["any_pass"] is True
    assert stats["truncated_by_cancellation"] is False


def test_statistics_use_executed_attempts_not_requested_k():
    # Cancellation stopped after 1 of 3 requested attempts.
    attempts = [["ok"]]
    stats = compute_attempt_statistics(attempts, lambda a: a[0] == "ok", requested_k=3)

    assert stats["truncated_by_cancellation"] is True
    assert stats["attempt_success_rate"] == 1.0
    assert stats["pass_at_k"] == 1.0
    assert stats["requested_attempts"] == 3
    assert stats["executed_attempts"] == 1


def test_wilson_interval_bounds():
    ci = wilson_interval(0, 10)
    assert ci["lower"] == 0.0
    assert 0 < ci["upper"] < 0.35

    ci_all = wilson_interval(10, 10)
    assert ci_all["upper"] == 1.0
    assert ci_all["lower"] > 0.65
