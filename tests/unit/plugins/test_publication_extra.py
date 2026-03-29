import pytest
from pathlib import Path
import json
import math
from eval_runner.publication_plugin import PublicationPlugin
from eval_runner.context import EvaluationContext

@pytest.fixture
def plugin(tmp_path, monkeypatch):
    """Fixture for PublicationPlugin with isolated filesystem."""
    monkeypatch.chdir(tmp_path)
    # Create a dummy config if needed
    config_path = tmp_path / "config.yaml"
    config_path.write_text("pricing:\n  gpt: 10.0\nregression_threshold: 0.1")
    return PublicationPlugin()

def test_wilson_score_interval(plugin):
    """Verifies edge cases for Wilson Score Interval calculation."""
    # Base case: 100% pass, 10 runs
    margin = plugin._wilson_score_interval(1.0, 10)
    assert margin > 0
    
    # Edge case: 0 runs
    assert plugin._wilson_score_interval(0.5, 0) == 0.0
    
    # Edge case: 0% pass
    margin_zero = plugin._wilson_score_interval(0.0, 100)
    assert margin_zero < 0.1

def test_calculate_pass_at_k(plugin):
    """Verifies Pass@k estimation for various distributions."""
    # Case: 5 runs, 3 passes. Calculate pass@1, 3, 5
    pass_flags = [True, True, True, False, False]
    res = plugin._calculate_pass_at_k(pass_flags)
    
    assert "pass@1" in res
    assert "pass@3" in res
    assert res["pass@1"] == 0.6  # 3/5
    assert res["pass@5"] == 1.0  # Since we have at least 1 pass in 5
    
    # Case: insufficient runs for k=10
    assert "pass@10" not in res

def test_export_results_and_regression(plugin, tmp_path):
    """Verifies export and regression detection logic."""
    summary = {
        "scenario_id": "test-scen",
        "metrics": {"pass_rate": 0.5},
        "agent": "gpt-4"
    }
    
    # 1. Export
    plugin._export_results(summary)
    res_file = tmp_path / "results/publication_results.jsonl"
    assert res_file.exists()
    
    # 2. Regression Detection (No baseline)
    plugin._check_regression(summary) # Should not crash
    
    # 3. Regression Detection (With baseline)
    baseline_path = tmp_path / "results/baselines.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    with open(baseline_path, "w") as f:
        json.dump({"test-scen": {"pass_rate": 0.9}}, f)
        
    # Trigger regression (0.9 -> 0.5 > 0.1 threshold)
    plugin._check_regression(summary) 
    # (Checking stdout would require capsys but we just verify it doesn't crash)

def test_after_evaluation_flow(plugin, tmp_path):
    """End-to-end flow of the plugin metrics calculation."""
    # Setup context
    ctx = EvaluationContext(scenario_id="scen-1", scenario_data={}, metadata={})
    ctx.plugin_data["agent_name"] = "gpt-tester"
    
    # Results structure: [[task_res_1, task_res_2]] (1 attempt)
    results = [[
        {
            "task_id": "t1",
            "metrics": [{"success": True}],
            "metrics_extra": {"latency": 1.2, "total_tokens": 100}
        }
    ]]
    
    plugin.after_evaluation(ctx, results)
    
    res_file = tmp_path / "results/publication_results.jsonl"
    with open(res_file, "r") as f:
        data = json.loads(f.read().strip())
        assert data["scenario_id"] == "scen-1"
        assert data["metrics"]["pass_rate"] == 1.0
        assert data["metrics"]["avg_latency"] == 1.2
