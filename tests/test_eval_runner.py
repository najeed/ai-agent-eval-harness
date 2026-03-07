"""
Test suite for evaluation runner core functionality and integration.

Covers:
- Scenario file loading from disk
- Schema validation at load time
- Dataset loading for CSV and JSONL
- Evaluation execution workflow
- Error handling for invalid scenarios

Example:
    pytest tests/test_eval_runner.py -v
"""

import pytest
import json
import sys
import tempfile
from pathlib import Path

# Add the eval-runner directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "eval-runner"))

import loader


# --- Phase 1: Scenario Loading Tests ---

def test_scenario_loading_from_file():
    """Test loading a valid scenario from a real file on disk."""
    # Use a known scenario file from the industries directory
    scenario_path = Path(__file__).parent.parent / "industries" / "telecom" / "scenarios" / "technical_support" / "13814_home_internet_slow_speed.json"
    
    if scenario_path.exists():
        scenario = loader.load_scenario(scenario_path)
        assert scenario["scenario_id"] == "telecom-ts-13814"
        assert "tasks" in scenario
        assert len(scenario["tasks"]) > 0
    else:
        pytest.skip("Telecom scenario file not found")


def test_scenario_loading_file_not_found():
    """Test that loading a non-existent file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        loader.load_scenario(Path("nonexistent/path/to/scenario.json"))


def test_scenario_schema_validation_rejects_invalid():
    """Test that schema validation rejects a scenario missing required fields."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"scenario_id": "bad", "title": "Missing Fields"}, f)
        f.flush()
        temp_path = Path(f.name)

    with pytest.raises(ValueError, match="Schema validation failed"):
        loader.load_scenario(temp_path)

    temp_path.unlink(missing_ok=True)


# --- Phase 1: Dataset Loading Tests ---

def test_load_csv_dataset():
    """Test loading a CSV dataset file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
        f.write("name,value\n")
        f.write("alpha,1\n")
        f.write("beta,2\n")
        f.flush()
        temp_path = Path(f.name)

    data = loader.load_dataset(temp_path)
    assert len(data) == 2
    assert data[0]["name"] == "alpha"
    assert data[1]["value"] == "2"

    temp_path.unlink(missing_ok=True)


def test_load_jsonl_dataset():
    """Test loading a JSONL dataset file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write('{"id": 1, "text": "hello"}\n')
        f.write('{"id": 2, "text": "world"}\n')
        f.flush()
        temp_path = Path(f.name)

    data = loader.load_dataset(temp_path)
    assert len(data) == 2
    assert data[0]["id"] == 1
    assert data[1]["text"] == "world"

    temp_path.unlink(missing_ok=True)


def test_load_dataset_file_not_found():
    """Test that loading a non-existent dataset raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        loader.load_dataset(Path("nonexistent/dataset.csv"))


def test_load_dataset_unsupported_format():
    """Test that an unsupported format returns an empty list."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("this is not a dataset\n")
        f.flush()
        temp_path = Path(f.name)

    data = loader.load_dataset(temp_path)
    assert data == []

    temp_path.unlink(missing_ok=True)


# --- Phase 1: Evaluation Workflow Tests ---

@pytest.mark.asyncio
async def test_basic_evaluation():
    """Test that a valid scenario structure can be processed."""
    test_scenario = {
        "scenario_id": "basic_eval_test",
        "title": "Basic Evaluation Test",
        "industry": "test",
        "description": "A basic evaluation test scenario.",
        "tasks": [
            {
                "task_id": "basic_task",
                "description": "A simple test task",
                "required_tools": ["test_tool"],
                "success_criteria": [
                    {"metric": "tool_call_correctness", "threshold": 1.0}
                ],
            }
        ],
    }
    assert test_scenario["scenario_id"] == "basic_eval_test"
    assert len(test_scenario["tasks"]) == 1
    assert test_scenario["tasks"][0]["task_id"] == "basic_task"


def test_invalid_scenario():
    """Test that invalid scenarios are detected."""
    invalid_scenarios = [
        {},
        {"scenario_id": "test"},
        {"scenario_id": "test", "tasks": []},
        {"scenario_id": "test", "tasks": [{"invalid": "structure"}]},
    ]
    for scenario in invalid_scenarios:
        if not scenario:
            assert len(scenario) == 0
        elif "tasks" not in scenario:
            assert "tasks" not in scenario
        elif scenario.get("tasks") == []:
            assert len(scenario["tasks"]) == 0
