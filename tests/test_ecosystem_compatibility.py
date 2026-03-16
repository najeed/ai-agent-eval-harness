# tests/test_p4_ecosystem.py
import pytest
import json
from pathlib import Path
from eval_runner import loader, plugins
from eval_runner.exporter import HFExporter

def test_benchmark_uri_loading():
    """Test that gaia:// URIs are correctly caught by the loader."""
    scenarios = loader.load_scenario("gaia://test_2023")
    assert isinstance(scenarios, list)
    assert len(scenarios) > 0
    assert scenarios[0]["scenario_id"].startswith("gaia_")

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
    
    mock_event = {"event": "run_start", "timestamp": "2026-01-01T00:00:00", "payload": {"scenario": "test"}}
    with open(trace_path, "w") as f:
        f.write(json.dumps(mock_event) + "\n")
        
    HFExporter.export(str(trace_path), str(output_path))
    
    assert output_path.exists()
    with open(output_path, "r") as f:
        data = json.load(f)
        assert len(data) == 1
        assert data[0]["event_type"] == "run_start"
