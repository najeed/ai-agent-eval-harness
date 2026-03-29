"""
Test suite for scenario loading and validation functionality.
"""

import pytest
import json
import tempfile
from pathlib import Path

from eval_runner import loader


def test_load_valid_scenario(tmp_path):
    """Test loading a valid scenario file with proper v1.2 JSON structure."""
    scenario_content = {
        "aes_version": 1.2,
        "scenario_id": "test_scenario",
        "title": "Test Scenario",
        "industry": "test",
        "description": "A test scenario.",
        "use_case": "Testing",
        "core_function": "Unit Test",
        "metadata": {
            "name": "test_scenario",
            "compliance_level": "Standard"
        },
        "workflow": {
            "nodes": [
                {
                    "id": "t1",
                    "task_description": "Test task.",
                    "expected_outcome": {
                        "type": "typed_value",
                        "data_type": "string",
                        "value": "Task completes successfully."
                    },
                    "required_tools": [],
                    "success_criteria": [],
                }
            ],
            "edges": []
        },
    }
    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(json.dumps(scenario_content))
    scenario = loader.load_scenario(scenario_file)
    assert scenario["scenario_id"] == "test_scenario"


def test_load_invalid_scenario(tmp_path):
    """Test error handling when loading a scenario file with invalid JSON."""
    scenario_file = tmp_path / "bad.json"
    scenario_file.write_text("{not: valid json}")
    with pytest.raises(Exception):
        loader.load_scenario(scenario_file)


def test_load_nonexistent_scenario(tmp_path):
    """Test error handling when attempting to load a non-existent scenario file."""
    scenario_file = tmp_path / "nonexistent.json"
    with pytest.raises(FileNotFoundError):
        loader.load_scenario(scenario_file)


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


def test_load_dataset_single_json(tmp_path):
    """Test loading a single JSON scenario via load_dataset."""
    scenario_file = tmp_path / "test.json"
    scenario_data = {
        "aes_version": 1.2,
        "scenario_id": "test-123",
        "title": "Test",
        "description": "Test description",
        "industry": "test",
        "metadata": {"name": "Test", "compliance_level": "Standard"},
        "workflow": {"nodes": [], "edges": []},
    }
    scenario_file.write_text(json.dumps(scenario_data))
    results = loader.load_dataset(scenario_file)
    assert len(results) == 1
    assert results[0]["scenario_id"] == "test-123"


def test_load_dataset_directory(tmp_path):
    """Test loading multiple scenarios from a directory."""
    (tmp_path / "s1.json").write_text(
        json.dumps(
            {
                "aes_version": 1.2,
                "scenario_id": "s1",
                "title": "S1",
                "industry": "i1",
                "description": "d1",
                "metadata": {"name": "S1", "compliance_level": "Standard"},
                "workflow": {"nodes": [], "edges": []},
            }
        )
    )
    (tmp_path / "s2.json").write_text(
        json.dumps(
            {
                "aes_version": 1.2,
                "scenario_id": "s2",
                "title": "S2",
                "industry": "i2",
                "description": "d2",
                "metadata": {"name": "S2", "compliance_level": "Standard"},
                "workflow": {"nodes": [], "edges": []},
            }
        )
    )
    (tmp_path / "other.txt").write_text("not a json")

    results = loader.load_dataset(tmp_path)
    assert len(results) == 2
    ids = [r["scenario_id"] for r in results]
    assert "s1" in ids
    assert "s2" in ids
