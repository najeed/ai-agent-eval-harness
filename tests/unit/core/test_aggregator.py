"""
test_aggregator.py

Test suite for the publication aggregator.
Verifies real latency calculation and cost metrics.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from eval_runner.publication_suite.aggregator import Aggregator


@pytest.fixture
def mock_manifest_and_logs(tmp_path):
    """Creates a temporary manifest and log file for testing."""
    ts_start = datetime.now()
    # Ensure ISO format without Z for simpler testing if needed, though we handle Z now
    ts_start_str = ts_start.isoformat()
    ts_end_str = (ts_start + timedelta(seconds=15)).isoformat()

    log_file = tmp_path / "run_test.jsonl"
    events = [
        {"event": "run_start", "timestamp": ts_start_str},
        {
            "event": "agent_response",
            "content": "Hello world",
            "timestamp": (ts_start + timedelta(seconds=2)).isoformat(),
        },
        {"event": "run_end", "timestamp": ts_end_str},
        {"event": "evaluation", "success": True, "timestamp": ts_end_str},
    ]

    with open(log_file, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    manifest_file = tmp_path / "manifest.json"
    manifest = {
        "fingerprint": "test_batch",
        "agent_name": "test",
        "base_dir": str(tmp_path),
        "runs": [{"success": True, "log_path": str(log_file), "scenario": "scen_1"}],
    }

    with open(manifest_file, "w") as f:
        json.dump(manifest, f)

    return manifest_file, tmp_path


def test_latency_calculation(mock_manifest_and_logs):
    """Verify that latency is calculated as a delta between start and end events."""
    manifest_path, base_dir = mock_manifest_and_logs
    agg = Aggregator(str(manifest_path))
    output_path = agg.process()

    with open(output_path) as f:
        results = json.load(f)

    # Find any scenario entry
    assert len(results["scenarios"]) > 0
    scenario_data = next(iter(results["scenarios"].values()))

    latency = scenario_data["avg_latency"]
    # 15 seconds delta in mock events.
    # Use wide margin for environment jitter or rounding
    assert 14.0 <= latency <= 16.0


def test_cost_heuristic(mock_manifest_and_logs):
    """Verify character-based cost heuristic."""
    manifest_path, base_dir = mock_manifest_and_logs
    agg = Aggregator(str(manifest_path))
    events = [{"event": "agent_response", "content": "12345678"}]  # 8 chars = 2 tokens

    # Mock pricing directly for testing.
    agg.config["pricing"] = {"test": 1.0}  # $1 per 1M tokens
    agg.agent_name = "test"
    cost = agg._calculate_cost(events)
    # 2 tokens * ($1 / 1,000,000) = 0.000002
    assert cost == 0.000002


def test_missing_timestamp_fallback(mock_manifest_and_logs):
    """Verify fallback to 2.5s if timestamps are missing or malformed."""
    manifest_path, base_dir = mock_manifest_and_logs

    # Create a log with bad timestamps
    bad_log = base_dir / "bad_run.jsonl"
    with open(bad_log, "w") as f:
        f.write(json.dumps({"event": "run_start", "timestamp": "invalid"}) + "\n")
        f.write(json.dumps({"event": "evaluation", "success": True}) + "\n")
        f.write(json.dumps({"event": "run_end", "timestamp": "invalid"}) + "\n")

    with open(manifest_path) as f:
        man = json.load(f)
    man["runs"][0]["log_path"] = str(bad_log)
    with open(manifest_path, "w") as f:
        json.dump(man, f)

    agg = Aggregator(str(manifest_path))
    agg.process()

    with open(base_dir / "aggregated_results.json") as f:
        res = json.load(f)

    assert len(res["scenarios"]) > 0
    scenario_data = next(iter(res["scenarios"].values()))
    assert scenario_data["avg_latency"] == 2.5


def test_wilson_score_interval_math(mock_manifest_and_logs):
    """Verify Wilson Score interval calculation logic."""
    manifest_path, _ = mock_manifest_and_logs
    agg = Aggregator(str(manifest_path))

    # n=0 case
    assert agg._wilson_score_interval(0.8, 0) == 0.0

    # Normal case
    interval = agg._wilson_score_interval(0.8, 100)
    assert 0.05 < interval < 0.15


def test_cost_calculation_variants(mock_manifest_and_logs):
    """Verify cost calculation with different agent names and pricing."""
    manifest_path, _ = mock_manifest_and_logs
    agg = Aggregator(str(manifest_path))

    agg.config["pricing"] = {"gpt-4": 10.0, "claude": 5.0}

    # Case 1: GPT-4 match
    agg.manifest["agent_name"] = "GPT-4-Turbo"
    events = [{"event": "agent_response", "content": "1234"}]  # 1 token
    cost = agg._calculate_cost(events)
    assert cost == 10.0 / 1_000_000

    # Case 2: Claude match
    agg.manifest["agent_name"] = "Claude-3-Sonnet"
    cost = agg._calculate_cost(events)
    assert cost == 5.0 / 1_000_000

    # Case 3: No match
    agg.manifest["agent_name"] = "Unknown-Model"
    cost = agg._calculate_cost(events)
    assert cost == 0.0


def test_process_failed_runs(mock_manifest_and_logs):
    """Verify that failed runs or missing logs are skipped gracefully."""
    manifest_path, base_dir = mock_manifest_and_logs

    with open(manifest_path) as f:
        man = json.load(f)

    # Add a failed run and a missing log run
    man["runs"].append({"success": False, "log_path": "none", "scenario": "scen_1"})
    man["runs"].append({"success": True, "log_path": "non_existent.jsonl", "scenario": "scen_1"})

    with open(manifest_path, "w") as f:
        json.dump(man, f)

    agg = Aggregator(str(manifest_path))
    output_path = agg.process()

    with open(output_path) as f:
        res = json.load(f)

    # Should only have 1 pass from the original successful run
    assert res["scenarios"]["scen_1"]["pass_rate"] == 1.0


def test_robust_timestamp_parsing(mock_manifest_and_logs):
    """Verify the internal parse_ts logic with various formats."""
    manifest_path, base_dir = mock_manifest_and_logs

    # We test this by injecting different formats into the log
    formats = [
        "2023-05-10T19:00:00.123456",
        "2023-05-10 19:00:10",
        "2023-05-10T19:00:15Z",
        "2023-05-10T20:00:00",  # Success (positive duration)
        "totally-invalid",  # Failure (None)
        None,  # Failure (None via if not ts)
    ]

    for fmt in formats:
        log_file = base_dir / f"fmt_{formats.index(fmt)}.jsonl"
        with open(log_file, "w") as f:
            f.write(json.dumps({"event": "run_start", "timestamp": "2023-05-10T19:00:00"}) + "\n")
            f.write(json.dumps({"event": "run_end", "timestamp": fmt}) + "\n")
            f.write(json.dumps({"event": "evaluation", "success": True}) + "\n")

        with open(manifest_path) as f:
            man = json.load(f)
        man["runs"] = [{"success": True, "log_path": str(log_file), "scenario": "scen_fmt"}]
        with open(manifest_path, "w") as f:
            json.dump(man, f)

        agg = Aggregator(str(manifest_path))
        agg.process()
        with open(base_dir / "aggregated_results.json") as f:
            res = json.load(f)

        latency = res["scenarios"]["scen_fmt"]["avg_latency"]
        if fmt in ["totally-invalid", None]:
            assert latency == 2.5
        else:
            # Latency should be calculated correctly (positive)
            assert latency != 2.5 or fmt == "2023-05-10T19:00:00"


def test_failure_taxonomy_integration(mock_manifest_and_logs):
    """Verify that failures are classified via FailureTaxonomy."""
    manifest_path, base_dir = mock_manifest_and_logs
    log_file = base_dir / "fail_run.jsonl"

    with open(log_file, "w") as f:
        f.write(json.dumps({"event": "run_start", "timestamp": "2023-01-01T00:00:00"}) + "\n")
        f.write(
            json.dumps(
                {"event": "evaluation", "success": False, "message": "hallucination detected"}
            )
            + "\n"
        )
        f.write(json.dumps({"event": "run_end", "timestamp": "2023-01-01T00:00:10"}) + "\n")

    with open(manifest_path) as f:
        man = json.load(f)
    man["runs"] = [{"success": True, "log_path": str(log_file), "scenario": "scen_fail"}]
    with open(manifest_path, "w") as f:
        json.dump(man, f)

    agg = Aggregator(str(manifest_path))
    agg.process()

    with open(base_dir / "aggregated_results.json") as f:
        res = json.load(f)

    assert res["scenarios"]["scen_fail"]["pass_rate"] == 0.0
    assert len(res["scenarios"]["scen_fail"]["failure_distribution"]) > 0


def test_aggregator_load_config_missing(tmp_path):
    """Verify fallback if config.yaml is missing."""
    manifest_path = tmp_path / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump({"fingerprint": "f", "agent_name": "a", "runs": []}, f)

    # Patch Path.exists to return False for config.yaml
    with patch("pathlib.Path.exists", return_value=False):
        agg = Aggregator(str(manifest_path))
        assert agg.config["confidence_level"] == 0.95
