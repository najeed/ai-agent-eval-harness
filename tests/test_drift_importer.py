import json
import pytest
from pathlib import Path
from eval_runner.drift_importer import import_trace_as_scenario

def test_import_trace_as_scenario(tmp_path):
    # Create a mock trace file
    trace_data = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "How can I help?"}
    ]
    trace_file = tmp_path / "trace.json"
    with open(trace_file, "w") as f:
        json.dump(trace_data, f)
    
    output_dir = tmp_path / "scenarios"
    industry = "telecom"
    
    # Run import
    scenario_path = import_trace_as_scenario(trace_file, industry, output_dir)
    
    # Verify output
    assert scenario_path.exists()
    with open(scenario_path, "r") as f:
        scenario = json.loads(f.read())
    
    assert scenario["version"] == "2.0.0"
    assert scenario["industry"] == "telecom"
    assert scenario["use_case"] == "production_replay"
    assert len(scenario["tasks"]) == 1
    assert scenario["ground_truth_history"] == [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "How can I help?"}]

def test_import_invalid_json(tmp_path):
    invalid_file = tmp_path / "invalid.json"
    invalid_file.write_text("not json")
    
    output_dir = tmp_path / "scenarios"
    
    with pytest.raises(ValueError, match="No conversation history found in trace"):
        import_trace_as_scenario(invalid_file, "generic", output_dir)
