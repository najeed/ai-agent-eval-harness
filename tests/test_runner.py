import pytest
import sys
import json
from pathlib import Path

# Add the eval-runner directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "eval-runner"))

# Import only the loader module which doesn't have relative import issues
import loader


def test_load_valid_scenario(tmp_path):
    # Create a minimal valid scenario file
    scenario_content = {
        "scenario_id": "test_scenario",
        "title": "Test Scenario",
        "industry": "test",
        "description": "A test scenario.",
        "tasks": [
            {"task_id": "t1", "description": "Test task.", "required_tools": [], "success_criteria": []}
        ]
    }
    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(json.dumps(scenario_content))
    scenario = loader.load_scenario(scenario_file)
    assert scenario["scenario_id"] == "test_scenario"


def test_load_invalid_scenario(tmp_path):
    # Create an invalid JSON file
    scenario_file = tmp_path / "bad.json"
    scenario_file.write_text("{not: valid json}")
    with pytest.raises(Exception):
        loader.load_scenario(scenario_file)


def test_load_nonexistent_scenario(tmp_path):
    # Test loading a file that doesn't exist
    scenario_file = tmp_path / "nonexistent.json"
    with pytest.raises(FileNotFoundError):
        loader.load_scenario(scenario_file) 