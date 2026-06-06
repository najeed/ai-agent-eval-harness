import json
from unittest.mock import patch

import pytest

from eval_runner.handlers.analysis import handle_trend
from eval_runner.trend import RunTrendAnalyzer


def test_ols_slope_calculation():
    analyzer = RunTrendAnalyzer("runs")

    # Positive slope
    assert analyzer._ols_slope([0.1, 0.2, 0.3]) > 0
    # Negative slope
    assert analyzer._ols_slope([0.9, 0.8, 0.7]) < 0
    # Flat slope
    assert analyzer._ols_slope([0.5, 0.5, 0.5]) == 0.0
    # Fewer than 2 points
    assert analyzer._ols_slope([0.5]) == 0.0
    assert analyzer._ols_slope([]) == 0.0


def test_ols_slope_calculation_fallback():
    analyzer = RunTrendAnalyzer("runs")
    # Force the fallback OLS calculation by mocking statistics.linear_regression to throw
    with patch("statistics.linear_regression", side_effect=Exception("mocked error")):
        assert analyzer._ols_slope([0.1, 0.2, 0.3]) > 0
        assert analyzer._ols_slope([0.9, 0.8, 0.7]) < 0
        assert analyzer._ols_slope([0.5, 0.5, 0.5]) == 0.0
        assert analyzer._ols_slope([0.5]) == 0.0
        # Check den == 0 case for fallback
        # With x values being [0, 1] and y being [0.5, 0.5], den is not 0.
        # But if we had a list of same values, variance in x is not 0
        # unless len < 2, which is handled early.


def test_run_trend_analyzer_scanning_and_fallbacks(tmp_path):
    # 1. Non-existent directory
    analyzer_nonexistent = RunTrendAnalyzer("non_existent_directory_12345")
    with pytest.raises(FileNotFoundError):
        analyzer_nonexistent.analyze()

    # 2. Setup directory
    run_dir = tmp_path / "runs"
    run_dir.mkdir()

    # Empty file (no events)
    empty_log = run_dir / "empty.jsonl"
    empty_log.write_text("")

    # Malformed manifest but valid trace
    run1_dir = run_dir / "run_1"
    run1_dir.mkdir()
    run1_log = run1_dir / "run.jsonl"
    run1_log.write_text(
        json.dumps(
            {
                "event": "run_start",
                "timestamp": "2026-06-01T10:00:00Z",
                "metadata": {"agent_name": "agent-a"},
            }
        )
        + "\n"
        + json.dumps({"event": "evaluation", "task_id": "t1", "success": True})
        + "\n"
    )
    manifest = run1_dir / "run_manifest.json"
    manifest.write_text("{malformed_json")

    # Run with manifest metadata and no timestamp
    run2_dir = run_dir / "run_2"
    run2_dir.mkdir()
    run2_log = run2_dir / "run.jsonl"
    run2_log.write_text(
        json.dumps({"event": "run_start", "metadata": {}})
        + "\n"
        + json.dumps({"event": "evaluation", "task_id": "t1", "success": True})
        + "\n"
    )
    manifest2 = run2_dir / "run_manifest.json"
    manifest2.write_text(
        json.dumps({"metadata": {"agent_name": "agent-b"}, "run_id": "custom-id-2"})
    )

    # Run with no evaluation events
    run3_dir = run_dir / "run_3"
    run3_dir.mkdir()
    run3_log = run3_dir / "run.jsonl"
    run3_log.write_text(json.dumps({"event": "run_start", "agent": "agent-c"}) + "\n")

    # Run with absolutely no agent name metadata to trigger parent directory name fallback
    run4_dir = run_dir / "run_4"
    run4_dir.mkdir()
    run4_log = run4_dir / "run.jsonl"
    run4_log.write_text(
        json.dumps({"event": "run_start", "timestamp": "2026-06-04T10:00:00Z"})
        + "\n"
        + json.dumps({"event": "evaluation", "task_id": "t1", "success": True})
        + "\n"
    )

    # Run that causes parse error in load_events (corrupted JSON)
    corrupted_log = run_dir / "corrupted.jsonl"
    corrupted_log.write_text("invalid json lines here")

    # Analyze all
    analyzer = RunTrendAnalyzer(run_log_dir=str(run_dir))
    reports = analyzer.analyze()

    # Verify reports
    agent_names = {r.agent_name for r in reports}
    assert "agent-a" in agent_names
    assert "agent-b" in agent_names
    assert "agent-c" in agent_names
    assert "run_4" in agent_names

    # Check manifest-based agent-b report
    r_b = next(r for r in reports if r.agent_name == "agent-b")
    assert r_b.run_points[0].run_id == "custom-id-2"
    assert r_b.run_points[0].timestamp is not None  # Fallback to mtime

    # Check empty evaluations run-c report
    r_c = next(r for r in reports if r.agent_name == "agent-c")
    assert r_c.run_points[0].pass_rate == 0.0

    # Test filtering by agent name
    analyzer_filtered = RunTrendAnalyzer(run_log_dir=str(run_dir), agent_name="agent-a")
    reports_filtered = analyzer_filtered.analyze()
    assert len(reports_filtered) == 1
    assert reports_filtered[0].agent_name == "agent-a"


def test_ols_slope_improving_stable(tmp_path):
    run_dir = tmp_path / "runs"
    run_dir.mkdir()

    # Improving trend: 0.1 -> 0.9
    for i, rate in enumerate([0.1, 0.9]):
        r_dir = run_dir / f"run_{i}"
        r_dir.mkdir()
        r_log = r_dir / "run.jsonl"
        r_log.write_text(
            json.dumps(
                {
                    "event": "run_start",
                    "timestamp": f"2026-06-0{i}T10:00:00Z",
                    "metadata": {"agent_name": "agent-x"},
                }
            )
            + "\n"
            + json.dumps({"event": "evaluation", "task_id": "t1", "success": (rate > 0.5)})
            + "\n"
        )

    # Analyze with positive threshold
    analyzer = RunTrendAnalyzer(run_log_dir=str(run_dir), threshold=0.1)
    reports = analyzer.analyze()
    assert len(reports) == 1
    assert reports[0].direction == "improving"
    assert reports[0].any_regression is False

    # Stable trend: 0.5 -> 0.5
    # We clear the directory and put stable trend
    for p in run_dir.glob("*"):
        if p.is_dir():
            for f in p.glob("*"):
                f.unlink()
            p.rmdir()
        else:
            p.unlink()

    for i, _rate in enumerate([0.5, 0.5]):
        r_dir = run_dir / f"run_{i}"
        r_dir.mkdir()
        r_log = r_dir / "run.jsonl"
        r_log.write_text(
            json.dumps(
                {
                    "event": "run_start",
                    "timestamp": f"2026-06-0{i}T10:00:00Z",
                    "metadata": {"agent_name": "agent-x"},
                }
            )
            + "\n"
            + json.dumps({"event": "evaluation", "task_id": "t1", "success": True})
            + "\n"
            + json.dumps({"event": "evaluation", "task_id": "t2", "success": False})
            + "\n"
        )

    analyzer_stable = RunTrendAnalyzer(run_log_dir=str(run_dir), threshold=0.1)
    reports_stable = analyzer_stable.analyze()
    assert len(reports_stable) == 1
    assert reports_stable[0].direction == "stable"
    assert reports_stable[0].any_regression is False


@pytest.mark.asyncio
async def test_handle_trend_edge_cases(tmp_path, capsys):
    # 1. No reports
    class DummyArgsEmpty:
        run_log_dir = str(tmp_path)
        agent_name = None
        window = 10
        threshold = 0.0
        exit_on_regression = False

    status = await handle_trend(DummyArgsEmpty())
    assert status == 0
    captured = capsys.readouterr()
    assert "No matching runs or agents found to analyze." in captured.out

    # 2. Regression with exit_on_regression = True
    run_dir = tmp_path / "runs"
    run_dir.mkdir()
    # Decreasing trend: 1.0 -> 0.0
    for i, success in enumerate([True, False]):
        r_dir = run_dir / f"run_{i}"
        r_dir.mkdir()
        r_log = r_dir / "run.jsonl"
        r_log.write_text(
            json.dumps(
                {
                    "event": "run_start",
                    "timestamp": f"2026-06-0{i}T10:00:00Z",
                    "metadata": {"agent_name": "agent-y"},
                }
            )
            + "\n"
            + json.dumps({"event": "evaluation", "task_id": "t1", "success": success})
            + "\n"
        )

    class DummyArgsRegression:
        run_log_dir = str(run_dir)
        agent_name = None
        window = 10
        threshold = 0.0
        exit_on_regression = True

    status_regression = await handle_trend(DummyArgsRegression())
    assert status_regression == 1
    captured_reg = capsys.readouterr()
    assert "REGRESSION DETECTED" in captured_reg.out
    assert "Exiting with code 1." in captured_reg.out

    # 3. Exception in handle_trend
    class DummyArgsException:
        # None will cause Path(None) to fail in RunTrendAnalyzer init, throwing TypeError
        run_log_dir = None
        agent_name = None
        window = 10
        threshold = 0.0
        exit_on_regression = False

    status_exc = await handle_trend(DummyArgsException())
    assert status_exc == 1
    captured_exc = capsys.readouterr()
    assert "Trend analysis FAILED" in captured_exc.out
