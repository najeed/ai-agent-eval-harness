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
import json
import os
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate
from referencing import Registry, Resource

# Systemic path resolution
BASE_DIR = Path(__file__).parent.parent.parent
SCHEMA_PATH = BASE_DIR / "spec" / "aes" / "aes.schema.json"
SCENARIOS_ROOT = BASE_DIR / "industries"


@pytest.fixture(scope="module")
def scenario_schema():
    """
    Fixture to load and cache the scenario schema for reuse across tests.
    """
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.loads(f.read())


def load_all_scenario_files():
    """
    Generator function to yield paths of all scenario JSON files in industries/.
    Excludes non-scenario data fixtures (mock_*.json) and pack manifests (pack_manifest.json).
    """
    for root, _, files in os.walk(SCENARIOS_ROOT):
        for file in files:
            if (
                file.endswith(".json")
                and file != "pack_manifest.json"
                and not file.startswith("mock_")
            ):
                yield os.path.join(root, file)


def test_all_scenarios_are_valid(scenario_schema):
    """
    Test that all scenario files under industries/ conform to valid scenario JSON specs.
    Fails loudly on any JSON decode error, schema error, or missing scenario files.
    """
    errors = []
    count = 0
    all_files = list(load_all_scenario_files())
    total_on_disk = len(all_files)

    def _get_definitions():
        defs = {}
        defs_dir = SCHEMA_PATH.parent / "definitions"
        if defs_dir.exists():
            for fpath in defs_dir.glob("*.json"):
                with open(fpath, encoding="utf-8") as f_def:
                    defs[f"definitions/{fpath.name}"] = json.load(f_def)
        return defs

    definitions = _get_definitions()
    registry = Registry()
    for ref_path, def_schema in definitions.items():
        registry = registry.with_resource(uri=ref_path, resource=Resource.from_contents(def_schema))

    for path_str in all_files:
        path = Path(path_str)
        try:
            content = path.read_text(encoding="utf-8")
            if not content.strip():
                errors.append((path_str, "Empty file content"))
                continue

            try:
                scenario = json.loads(content)
            except json.JSONDecodeError as exc:
                errors.append((path_str, f"JSONDecodeError: {str(exc)}"))
                continue

            if not isinstance(scenario, dict):
                errors.append((path_str, "Scenario root element is not a JSON object"))
                continue

            count += 1
            validate(instance=scenario, schema=scenario_schema, registry=registry)
        except ValidationError as e:
            errors.append((path_str, f"ValidationError: {str(e)}"))
        except Exception as e:
            errors.append((path_str, f"Unexpected error: {str(e)}"))

    print(f"\n[DEBUG] Validated {count}/{total_on_disk} scenario files across industries/.")
    if errors:
        print(f"\n[ERROR] Found {len(errors)} scenario failure(s):")
        for p, err in errors[:20]:  # Limit print output if many
            print(f"  - File: {p}")
            print(f"    Error: {err}\n")
        pytest.fail(f"{len(errors)} scenario file(s) failed validation under industries/")

    assert total_on_disk > 5000, f"Expected >5000 scenarios on disk, but found {total_on_disk}!"
    assert count == total_on_disk, f"Validated {count} scenarios, but expected {total_on_disk}!"
