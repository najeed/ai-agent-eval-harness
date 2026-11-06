# tests/test_p4_ecosystem.py
import json

import pytest

from eval_runner import loader, plugins
from eval_runner.exporter import HFExporter


def test_benchmark_uri_loading(tmp_path):
    """Benchmark dispatch reads real records and rejects an absent dataset."""
    dataset = tmp_path / "gaia.jsonl"
    dataset.write_text(
        json.dumps({"task_id": "task-2023", "Question": "What is 2 + 2?", "Final answer": "4"}),
        encoding="utf-8",
    )
    scenarios = loader.load_scenario(f"gaia://{dataset.as_posix()}")
    assert scenarios[0]["metadata"]["benchmark"]["source_id"] == "task-2023"
    assert scenarios[0]["workflow"]["nodes"][0]["expected_outcome"][0]["expected"] == "4"
    with pytest.raises(FileNotFoundError):
        loader.load_scenario(f"gaia://{(tmp_path / 'missing.jsonl').as_posix()}")


def test_adapter_plugin_loading():
    """Test that internal adapters are loaded as plugins."""
    mgr = plugins.PluginManager()
    mgr.load_plugins()
    plugin_names = [p.__class__.__name__ for p in mgr.plugins]
    assert "LangGraphAdapterPlugin" in plugin_names
    assert "CrewAIAdapterPlugin" in plugin_names


def test_hf_export_parity(tmp_path):
    """Test that HFExporter produces a valid JSON structure."""
    trace_path = tmp_path / "run.jsonl"
    output_path = tmp_path / "hf_dataset.json"

    mock_event = {
        "event": "run_start",
        "timestamp": "2026-01-01T00:00:00",
        "payload": {"scenario": "test"},
    }
    with open(trace_path, "w") as f:
        f.write(json.dumps(mock_event) + "\n")

    HFExporter.export(str(trace_path), str(output_path))

    assert output_path.exists()
    with open(output_path) as f:
        data = json.load(f)
        assert len(data) == 1
        assert data[0]["event_type"] == "run_start"
