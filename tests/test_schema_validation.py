"""
Test suite for JSON schema validation of scenario files.

This module contains comprehensive tests for validating scenario files
against the defined JSON schema. The tests ensure that all scenario
files in the industries directory conform to the expected structure
and data types defined in the schema specification.

The test suite covers:
- Schema loading and validation
- Comprehensive validation of all scenario files
- Error reporting for invalid scenarios
- Fixture setup for schema reuse

Example:
    To run these tests specifically:
    pytest tests/test_schema_validation.py -v
"""

# tests/test_schema_validation.py
import os
import json
import pytest
from jsonschema import validate, ValidationError

SCHEMA_PATH = "schemas/scenario.schema.json"
SCENARIOS_ROOT = "industries"

@pytest.fixture(scope="module")
def scenario_schema():
    """
    Fixture to load and cache the scenario schema for reuse across tests.
    
    This fixture loads the JSON schema file once and makes it available
    to all tests in the module. The module scope ensures the schema
    is only loaded once, improving test performance.
    
    Args:
        None
        
    Returns:
        dict: The loaded JSON schema for scenario validation
        
    Raises:
        FileNotFoundError: If the schema file doesn't exist
        json.JSONDecodeError: If the schema file contains invalid JSON
        
    Example:
        The fixture loads the schema from "schemas/scenario.schema.json"
        and returns it as a Python dictionary for use in validation tests.
    """
    with open(SCHEMA_PATH, "r") as f:
        return json.load(f)

def load_all_scenario_files():
    """
    Generator function to yield paths of all scenario JSON files.
    
    This function recursively walks through the industries directory
    and yields the full path of each JSON file found. It's used to
    systematically validate all scenario files against the schema.
    
    Args:
        None
        
    Yields:
        str: Full path to each scenario JSON file found
        
    Example:
        Yields paths like:
        "industries/accounting/scenarios/accounts_payable/scenario1.json"
        "industries/aerospace/scenarios/aircraft_manufacturing/scenario2.json"
    """
    for root, _, files in os.walk(SCENARIOS_ROOT):
        for file in files:
            if file.endswith(".json"):
                yield os.path.join(root, file)

def test_all_scenarios_are_valid(scenario_schema):
    """
    Test that all scenario files conform to the defined JSON schema.
    
    This test validates every JSON file in the industries directory
    against the scenario schema. It collects all validation errors
    and reports them comprehensively, ensuring that the entire
    scenario corpus maintains data integrity and consistency.
    
    Args:
        scenario_schema: pytest fixture providing the loaded JSON schema
        
    Returns:
        None
        
    Raises:
        pytest.fail: If any scenario files fail schema validation
        
    Example:
        The test validates files like:
        - industries/accounting/scenarios/accounts_payable/*.json
        - industries/aerospace/scenarios/aircraft_manufacturing/*.json
        - All other scenario files in the industries directory
        
        If validation fails, it reports specific errors for each file.
    """
    errors = []
    for path in load_all_scenario_files():
        with open(path, "r") as f:
            try:
                scenario = json.load(f)
                validate(instance=scenario, schema=scenario_schema)
            except ValidationError as e:
                errors.append((path, str(e)))
    if errors:
        for path, err in errors:
            print(f"Validation error in {path}: {err}")
        pytest.fail(f"{len(errors)} scenario file(s) failed schema validation")
