# tests/test_schema_validation.py
import os
import json
import pytest
from jsonschema import validate, ValidationError

SCHEMA_PATH = "schemas/scenario.schema.json"
SCENARIOS_ROOT = "industries"

@pytest.fixture(scope="module")
def scenario_schema():
    with open(SCHEMA_PATH, "r") as f:
        return json.load(f)

def load_all_scenario_files():
    for root, _, files in os.walk(SCENARIOS_ROOT):
        for file in files:
            if file.endswith(".json"):
                yield os.path.join(root, file)

def test_all_scenarios_are_valid(scenario_schema):
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
