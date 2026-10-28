from unittest.mock import patch

import pytest

from eval_runner.handlers.analysis import handle_trend
from eval_runner.trend import RunTrendAnalyzer


class FakeRunStore:
    def __init__(self, records, manifests, events):
        self.records, self.manifests, self.events = records, manifests, events

    def list_runs(self, *, limit, context=None):
        return self.records

    def get_manifest(self, run_id, *, context=None):
        return self.manifests.get(run_id, {})

    def get_events(self, run_id, *, offset, limit, context=None):
        return self.events[run_id]


@pytest.fixture
def run_store():
    records = [{"run_id": "r1"}, {"run_id": "r2"}, {"run_id": "r3"}]
    manifests = {
        "r1": {"agent_name": "agent-a"},
        "r2": {"agent_name": "agent-a"},
        "r3": {"agent_name": "agent-b"},
    }
    events = {
        "r1": [
            {"event": "run_start", "timestamp": "2026-06-01T10:00:00Z"},
            {"event": "evaluation", "task_id": "t", "success": False},
        ],
        "r2": [
            {"event": "run_start", "timestamp": "2026-06-02T10:00:00Z"},
            {"event": "evaluation", "task_id": "t", "success": True},
        ],
        "r3": [{"event": "run_start", "timestamp": "2026-06-03T10:00:00Z"}],
    }
    return FakeRunStore(records, manifests, events)


def test_ols_slope_calculation(run_store):
    analyzer = RunTrendAnalyzer(run_store=run_store)
    assert analyzer._ols_slope([0.1, 0.2, 0.3]) > 0
    assert analyzer._ols_slope([0.9, 0.8, 0.7]) < 0
    assert analyzer._ols_slope([0.5]) == 0.0
    with patch("statistics.linear_regression", side_effect=Exception("fallback")):
        assert analyzer._ols_slope([0.1, 0.2, 0.3]) > 0


def test_analyze_provider_runs_and_filter(run_store):
    reports = RunTrendAnalyzer(run_store=run_store, threshold=0.1).analyze()
    agent_a = next(report for report in reports if report.agent_name == "agent-a")
    assert agent_a.direction == "improving"
    assert (
        next(report for report in reports if report.agent_name == "agent-b").run_points[0].pass_rate
        == 0.0
    )
    filtered = RunTrendAnalyzer(run_store=run_store, agent_name="agent-a").analyze()
    assert [report.agent_name for report in filtered] == ["agent-a"]


def test_analyze_skips_invalid_and_unreadable_provider_records():
    class PartiallyBrokenStore(FakeRunStore):
        def get_events(self, run_id, **kwargs):
            if run_id == "broken":
                raise ValueError("unavailable")
            return super().get_events(run_id, **kwargs)

    store = PartiallyBrokenStore(
        [
            {"created_at": "ignored"},
            {"run_id": "broken"},
            {"run_id": "fallback", "agent_id": "agent-fallback"},
        ],
        {"fallback": {}},
        {
            "fallback": [
                {"event": "run_start"},
                {"event": "evaluation", "task_id": "a", "success": True},
            ]
        },
    )
    reports = RunTrendAnalyzer(run_store=store).analyze()
    assert len(reports) == 1
    assert reports[0].agent_name == "agent-fallback"


@pytest.mark.asyncio
async def test_handle_trend_resolves_provider_and_reports_regression(run_store, capsys):
    class Args:
        agent_name = "agent-a"
        window = 10
        threshold = 0.0
        exit_on_regression = False

    with patch("eval_runner.runtime_services.resolve_run_store", return_value=run_store):
        assert await handle_trend(Args()) == 0
    assert "AGENT PERFORMANCE TREND ANALYSIS" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_handle_trend_empty_provider(run_store, capsys):
    class Args:
        agent_name = None
        window = 10
        threshold = 0.0
        exit_on_regression = False

    empty = FakeRunStore([], {}, {})
    with patch("eval_runner.runtime_services.resolve_run_store", return_value=empty):
        assert await handle_trend(Args()) == 0
    assert "No matching runs" in capsys.readouterr().out
