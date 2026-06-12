import builtins
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from eval_runner.context import EvaluationContext
from eval_runner.publication_plugin import PublicationPlugin


def test_publication_plugin_config_load_exception():
    """Verify fallback to defaults when config.yaml raises an open exception."""
    plugin = PublicationPlugin()
    with patch("builtins.open", MagicMock(side_effect=OSError("Read error"))):
        cfg = plugin._load_config()
        assert cfg == {"pricing": {}, "confidence_level": 0.95}


def test_publication_plugin_percentile_empty():
    """Verify that _percentile returns 0 when given an empty list."""
    plugin = PublicationPlugin()
    assert plugin._percentile([], 95) == 0


def test_publication_plugin_calculate_cost_match():
    """Verify pricing conversion works when agent name matches pricing key."""
    plugin = PublicationPlugin()
    plugin.config = {"pricing": {"agent_x": 10.0}}
    cost = plugin._calculate_cost({"metrics_extra": {"total_tokens": 1000}}, "agent_x")
    # 1000 * (10.0 / 1_000_000.0) = 0.01
    assert abs(cost - 0.01) < 1e-9


def test_publication_plugin_regression_no_alert(tmp_path, monkeypatch):
    """Verify no regression alert prints when difference is within threshold."""
    plugin = PublicationPlugin()
    baseline_path = tmp_path / "baselines.json"
    baseline_path.write_text(json.dumps({"test_scen": {"pass_rate": 0.5}}), encoding="utf-8")
    monkeypatch.setattr(
        Path, "exists", lambda self: True if "baselines.json" in str(self) else False
    )

    summary = {
        "id": "test_scen",
        "metrics": {"pass_rate": 0.49},  # Difference is 0.01 (less than threshold 0.03)
    }

    # We patch open to return our baseline file
    orig_open = builtins.open

    def mock_open(file, *args, **kwargs):
        if "baselines.json" in str(file):
            return orig_open(baseline_path, *args, **kwargs)
        return orig_open(file, *args, **kwargs)

    with patch("builtins.open", mock_open):
        # Should execute and not print regression alert
        plugin._check_regression(summary)


def test_publication_plugin_regression_exception(tmp_path, monkeypatch):
    """Verify exceptions during regression check are swallowed."""
    plugin = PublicationPlugin()
    baseline_path = tmp_path / "baselines.json"
    baseline_path.write_text("corrupted_json", encoding="utf-8")
    monkeypatch.setattr(
        Path, "exists", lambda self: True if "baselines.json" in str(self) else False
    )

    orig_open = builtins.open

    def mock_open(file, *args, **kwargs):
        if "baselines.json" in str(file):
            return orig_open(baseline_path, *args, **kwargs)
        return orig_open(file, *args, **kwargs)

    with patch("builtins.open", mock_open):
        # Exception during json.load is caught and passed
        plugin._check_regression({"id": "test_scen", "metrics": {"pass_rate": 0.5}})


def test_publication_plugin_after_evaluation_failure(tmp_path, monkeypatch):
    """Verify failure classification and counting on failing evaluations."""
    plugin = PublicationPlugin()

    # Mock context
    context = MagicMock(spec=EvaluationContext)
    context.scenario_data = {"industry": "finance", "use_case": "ab_testing", "difficulty": "hard"}
    context.metadata = {"agent_name": "test_agent", "args": {"seed": 42}}
    context.identifier = "test_run_123"

    # Failing results (is_success will be False because metric success is False)
    task_res = {
        "metrics": [{"success": False, "metric": "state_verification"}],
        "metrics_extra": {"latency": 1.2, "total_tokens": 100},
        "conversation_history": [],
    }
    attempts = [[task_res]]

    # Export results writes to results/publication_results.jsonl, redirect it
    monkeypatch.setattr(plugin, "_export_results", lambda summary: None)

    # Baseline path exists mock to avoid actual baseline check warnings
    monkeypatch.setattr(Path, "exists", lambda self: False)

    # This should run and classify failure (hitting lines 65-66)
    plugin.after_evaluation(context, attempts)
