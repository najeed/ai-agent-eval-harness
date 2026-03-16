"""
test_aggregator.py

Test suite for the publication aggregator.
Verifies real latency calculation and cost metrics.
"""

import pytest
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from scripts.publication_suite.aggregator import Aggregator

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
        {"event": "agent_response", "content": "Hello world", "timestamp": (ts_start + timedelta(seconds=2)).isoformat()},
        {"event": "run_end", "timestamp": ts_end_str},
        {"event": "evaluation", "success": True, "timestamp": ts_end_str}
    ]
    
    with open(log_file, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
            
    manifest_file = tmp_path / "manifest.json"
    manifest = {
        "fingerprint": "test_batch",
        "agent_name": "test",
        "base_dir": str(tmp_path),
        "runs": [
            {"success": True, "log_path": str(log_file), "scenario": "scen_1"}
        ]
    }
    
    with open(manifest_file, "w") as f:
        json.dump(manifest, f)
        
    return manifest_file, tmp_path

def test_latency_calculation(mock_manifest_and_logs):
    """Verify that latency is calculated as a delta between start and end events."""
    manifest_path, base_dir = mock_manifest_and_logs
    agg = Aggregator(str(manifest_path))
    output_path = agg.process()
    
    with open(output_path, "r") as f:
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
    events = [{"event": "agent_response", "content": "12345678"}] # 8 chars = 2 tokens
    
    # Mock pricing directly for testing.
    agg.config["pricing"] = {"test": 1.0} # $1 per 1M tokens
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
        
    with open(manifest_path, "r") as f:
        man = json.load(f)
    man["runs"][0]["log_path"] = str(bad_log)
    with open(manifest_path, "w") as f:
        json.dump(man, f)
        
    agg = Aggregator(str(manifest_path))
    agg.process()
    
    with open(base_dir / "aggregated_results.json", "r") as f:
        res = json.load(f)
        
    assert len(res["scenarios"]) > 0
    scenario_data = next(iter(res["scenarios"].values()))
    assert scenario_data["avg_latency"] == 2.5
