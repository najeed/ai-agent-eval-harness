"""
tests/golden/test_golden_stats.py
Golden Verification Corpus: Percentile Index Bounds & Failure Denominator
"""

from eval_runner.context import EvaluationContext
from eval_runner.publication_plugin import PublicationPlugin


def test_golden_percentile_boundary_at_p100():
    plugin = PublicationPlugin()
    data = [10.0, 20.0, 30.0, 40.0, 50.0]

    # p=100 must not raise IndexError and must return maximum element
    val_100 = plugin._percentile(data, 100)
    assert val_100 == 50.0

    # p=0 returns minimum element
    val_0 = plugin._percentile(data, 0)
    assert val_0 == 10.0

    # Single element list
    single = [42.0]
    assert plugin._percentile(single, 100) == 42.0
    assert plugin._percentile(single, 50) == 42.0
    assert plugin._percentile(single, 0) == 42.0

    # Empty list
    assert plugin._percentile([], 95) == 0


def test_golden_failure_distribution_denominator(tmp_path, monkeypatch):
    plugin = PublicationPlugin()

    # Monkeypatch export and check regression to avoid file writes
    monkeypatch.setattr(plugin, "_export_results", lambda s: None)
    monkeypatch.setattr(plugin, "_check_regression", lambda s: None)

    ctx = EvaluationContext(
        identifier="scenario_stats_test",
        scenario_data={"id": "scenario_stats_test"},
        seed=1,
    )

    # 4 attempts total: 2 passed, 2 failed
    # Each attempt has 3 tasks
    attempt_pass_1 = [
        {"metrics": [{"success": True}], "metrics_extra": {"latency": 1.0}} for _ in range(3)
    ]
    attempt_pass_2 = [
        {"metrics": [{"success": True}], "metrics_extra": {"latency": 1.0}} for _ in range(3)
    ]
    attempt_fail_1 = [
        {"metrics": [{"success": False}], "metrics_extra": {"latency": 5.0}} for _ in range(3)
    ]
    attempt_fail_2 = [
        {"metrics": [{"success": False}], "metrics_extra": {"latency": 2.0}} for _ in range(3)
    ]

    results = [attempt_pass_1, attempt_pass_2, attempt_fail_1, attempt_fail_2]

    # Captured summary from after_evaluation
    captured_summary = None

    def mock_export(summary):
        nonlocal captured_summary
        captured_summary = summary

    monkeypatch.setattr(plugin, "_export_results", mock_export)

    plugin.after_evaluation(ctx, results)

    assert captured_summary is not None
    metrics = captured_summary["metrics"]
    assert metrics["pass_rate"] == 0.5  # 2/4
    # Denominator for failure_distribution must be total attempts N=4
    # Total failed tasks = 6 (3 in fail_1 + 3 in fail_2)
    # The count is divided by total attempts (N_total = 4) -> 6 / 4 = 1.5
    dist = metrics["failure_distribution"]
    assert len(dist) > 0
    total_failure_rate = sum(dist.values())
    assert total_failure_rate == 6 / 4
