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
from pathlib import Path

# Add the eval-runner directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "eval-runner"))

# Import only the loader module which doesn't have relative import issues
import loader


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
        "tasks": [
            {"task_id": "t1", "description": "Test task.", "required_tools": [], "success_criteria": []}
        ]
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