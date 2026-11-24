import json

import pytest

from eval_runner.drift_importer import import_trace_as_scenario


def test_import_trace_as_scenario(tmp_path):
    # Create a mock trace file
    trace_data = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "How can I help?"},
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
    with open(scenario_path) as f:
        scenario = json.loads(f.read())

    assert scenario["aes_version"] == 1.4
    assert scenario["industry"] == "telecom"
    assert scenario["use_case"] == "production_replay"
    assert len(scenario["workflow"]["nodes"]) == 1
    assert scenario["metadata"]["ground_truth_history"] == [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "How can I help?"},
    ]


def test_import_invalid_json(tmp_path):
    invalid_file = tmp_path / "invalid.json"
    invalid_file.write_text("not json")

    output_dir = tmp_path / "scenarios"

    # Updated to match actual error message from load_events wrapped by import_trace_as_scenario
    with pytest.raises(
        ValueError,
        match="Failed to parse trace: No valid JSON events could be parsed from the trace file.",
    ):
        import_trace_as_scenario(invalid_file, "generic", output_dir)


def test_import_empty_history(tmp_path):
    empty_file = tmp_path / "empty.json"
    empty_file.write_text("[]")

    output_dir = tmp_path / "scenarios"

    # This should trigger the "No conversation history found in trace" error
    with pytest.raises(ValueError, match="No conversation history found in trace"):
        import_trace_as_scenario(empty_file, "generic", output_dir)


def test_import_nonexistent_trace_file(tmp_path):
    missing_file = tmp_path / "nonexistent.json"
    output_dir = tmp_path / "scenarios"
    with pytest.raises(FileNotFoundError, match="Trace file not found"):
        import_trace_as_scenario(missing_file, "generic", output_dir)


def test_import_trace_dict_with_history(tmp_path, monkeypatch):
    trace_dict = {
        "history": [
            {"role": "user", "content": "Question"},
            {"role": "agent", "content": "Answer"},
        ]
    }
    trace_file = tmp_path / "trace_dict.json"
    trace_file.write_text("{}")
    monkeypatch.setattr("eval_runner.drift_importer.load_events", lambda _: trace_dict)

    output_dir = tmp_path / "scenarios"
    scenario_path = import_trace_as_scenario(trace_file, "finance", output_dir)
    assert scenario_path.exists()
    data = json.loads(scenario_path.read_text())
    assert data["metadata"]["ground_truth_history"] == trace_dict["history"]

    # Imported files must satisfy the same contract as ordinary user-authored scenarios.
    from eval_runner.loader import get_scenario_validator, load_scenario

    get_scenario_validator().validate(data)
    loaded = load_scenario(scenario_path)
    assert loaded["metadata"]["ground_truth_history"] == trace_dict["history"]
