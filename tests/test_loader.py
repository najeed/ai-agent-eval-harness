"""
Test suite for scenario loading and validation functionality.

This module contains comprehensive tests for the scenario loading system,
including valid scenario loading, error handling for invalid JSON files,
and handling of non-existent files. The tests ensure the loader module
can properly parse and validate scenario files according to the expected format.

The test suite covers:
- Valid scenario file loading with proper JSON structure
- Error handling for malformed JSON files
- File not found scenarios
- Basic scenario structure validation

Example:
    To run these tests specifically:
    pytest tests/test_runner.py -v
"""

import pytest
import sys
import json
import tempfile
from pathlib import Path

from eval_runner import loader


def test_load_valid_scenario(tmp_path):
    """
    Test loading a valid scenario file with proper JSON structure.

    This test verifies that the loader can successfully parse a well-formed
    scenario file containing all required fields: scenario_id, title, industry,
    description, and tasks array. The test creates a temporary scenario file
    with minimal valid content and ensures it loads without errors.

    Args:
        tmp_path: pytest fixture providing a temporary directory path

    Returns:
        None

    Raises:
        AssertionError: If the loaded scenario doesn't match expected values

    Example:
        The test creates a scenario file with:
        {
            "scenario_id": "test_scenario",
            "title": "Test Scenario",
            "industry": "test",
            "description": "A test scenario.",
            "tasks": [{"task_id": "t1", "description": "Test task.",
                      "required_tools": [], "success_criteria": []}]
        }
    """
    # Create a minimal valid scenario file
    scenario_content = {
        "scenario_id": "test_scenario",
        "title": "Test Scenario",
        "industry": "test",
        "description": "A test scenario.",
        "use_case": "Testing",
        "core_function": "Unit Test",
        "tasks": [
            {
                "task_id": "t1",
                "description": "Test task.",
                "expected_outcome": "Task completes successfully.",
                "required_tools": [],
                "success_criteria": [],
            }
        ],
    }
    scenario_file = tmp_path / "scenario.json"
    scenario_file.write_text(json.dumps(scenario_content))
    scenario = loader.load_scenario(scenario_file)
    assert scenario["scenario_id"] == "test_scenario"


def test_load_invalid_scenario(tmp_path):
    """
    Test error handling when loading a scenario file with invalid JSON.

    This test ensures that the loader properly handles malformed JSON files
    by raising an appropriate exception. The test creates a temporary file
    with invalid JSON syntax and verifies that the loader fails gracefully
    with an exception rather than crashing or returning invalid data.

    Args:
        tmp_path: pytest fixture providing a temporary directory path

    Returns:
        None

    Raises:
        Exception: Expected to be raised when invalid JSON is encountered

    Example:
        The test creates a file with invalid JSON:
        "{not: valid json}"
    """
    # Create an invalid JSON file
    scenario_file = tmp_path / "bad.json"
    scenario_file.write_text("{not: valid json}")
    with pytest.raises(Exception):
        loader.load_scenario(scenario_file)


def test_load_nonexistent_scenario(tmp_path):
    """
    Test error handling when attempting to load a non-existent scenario file.

    This test verifies that the loader properly handles cases where the
    specified scenario file doesn't exist in the filesystem. The test
    attempts to load a file that was never created and ensures that
    a FileNotFoundError is raised, indicating proper error handling.

    Args:
        tmp_path: pytest fixture providing a temporary directory path

    Returns:
        None

    Raises:
        FileNotFoundError: Expected to be raised when file doesn't exist

    Example:
        The test attempts to load "nonexistent.json" which was never created.
    """
    # Test loading a file that doesn't exist
    scenario_file = tmp_path / "nonexistent.json"
    with pytest.raises(FileNotFoundError):
        loader.load_scenario(scenario_file)


# --- Dataset Loading Tests (Migrated from test_eval_runner.py) ---


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


def test_load_dataset_with_format_override():
    """Test loading a dataset with an explicit format_type override."""
    # Create a CSV file with a .txt extension
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, newline="") as f:
        f.write("id,label\n")
        f.write("1,test\n")
        f.flush()
        temp_path = Path(f.name)

    # Load with explicit .csv format_type
    data = loader.load_dataset(temp_path, format_type=".csv")
    assert len(data) == 1
    assert data[0]["label"] == "test"

    temp_path.unlink(missing_ok=True)


def test_load_csv_empty_file():
    """Empty CSV (headers only) returns empty list."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
        f.write("col1,col2\n")
        f.flush()
        temp_path = Path(f.name)

    data = loader.load_dataset(temp_path)
    assert data == []
    temp_path.unlink(missing_ok=True)


def test_load_jsonl_empty_file():
    """Empty JSONL returns empty list."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write("")
        f.flush()
        temp_path = Path(f.name)

    data = loader.load_dataset(temp_path)
    assert data == []
    temp_path.unlink(missing_ok=True)


# --- Dataset Loading (Migrated from test_loader_v2.py) ---


def test_load_dataset_single_json(tmp_path):
    scenario_file = tmp_path / "test.json"
    scenario_data = {
        "scenario_id": "test-123",
        "version": "2.0.0",
        "title": "Test",
        "description": "Test description",
        "use_case": "Test use case",
        "core_function": "Test core function",
        "industry": "test",
        "tasks": [],
    }
    scenario_file.write_text(json.dumps(scenario_data))

    # Mocking the schema validation for unit test if needed,
    # but here we use the real one since it's available.
    results = loader.load_dataset(scenario_file)
    assert len(results) == 1
    assert results[0]["scenario_id"] == "test-123"


def test_load_dataset_directory(tmp_path):
    (tmp_path / "s1.json").write_text(
        json.dumps(
            {
                "scenario_id": "s1",
                "version": "2.0.0",
                "title": "S1",
                "industry": "i1",
                "description": "d1",
                "use_case": "u1",
                "core_function": "c1",
                "tasks": [],
            }
        )
    )
    (tmp_path / "s2.json").write_text(
        json.dumps(
            {
                "scenario_id": "s2",
                "version": "2.0.0",
                "title": "S2",
                "industry": "i2",
                "description": "d2",
                "use_case": "u2",
                "core_function": "c2",
                "tasks": [],
            }
        )
    )
    (tmp_path / "other.txt").write_text("not a json")

    results = loader.load_dataset(tmp_path)
    assert len(results) == 2
    ids = [r["scenario_id"] for r in results]
    assert "s1" in ids
    assert "s2" in ids
