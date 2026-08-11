"""
Test suite for JSON schema validation of scenario files.
Refactored for true pytest-xdist parallelization across 5,000+ scenarios,
strict exception hygiene (Ruff B017 compliance), multi-version schema dispatch,
and disk inventory sentinel assertions.
"""

import json
import os
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate
from referencing import Registry, Resource

BASE_DIR = Path(__file__).parent.parent.parent
SCHEMA_1_4_PATH = BASE_DIR / "spec" / "aes" / "aes.schema.json"
SCENARIOS_ROOT = BASE_DIR / "industries"


def _get_scenario_relative_paths() -> list[str]:
    """Discovers all scenario relative paths under industries/ for pytest parametrization."""
    paths = []
    if not SCENARIOS_ROOT.exists():
        return paths

    for root, _, files in os.walk(SCENARIOS_ROOT):
        for file in files:
            if (
                file.endswith(".json")
                and file != "pack_manifest.json"
                and not file.startswith("mock_")
            ):
                abs_path = Path(root) / file
                rel_path = str(abs_path.relative_to(BASE_DIR)).replace("\\", "/")
                paths.append(rel_path)
    return sorted(paths)


ALL_SCENARIO_PATHS = _get_scenario_relative_paths()


@pytest.fixture(scope="module")
def schema_registry_and_specs():
    """
    Module-scoped fixture loading schema specifications and definition registries
    for multi-version schema dispatch.
    """
    with open(SCHEMA_1_4_PATH, encoding="utf-8") as f:
        schema_1_4 = json.load(f)

    defs_dir = SCHEMA_1_4_PATH.parent / "definitions"
    registry = Registry()
    if defs_dir.exists():
        for fpath in defs_dir.glob("*.json"):
            with open(fpath, encoding="utf-8") as f_def:
                def_schema = json.load(f_def)
                registry = registry.with_resource(
                    uri=f"definitions/{fpath.name}",
                    resource=Resource.from_contents(def_schema),
                )

    # Multi-version schema dispatch mapping (AES version -> Schema object)
    schemas = {
        1.4: schema_1_4,
        "1.4": schema_1_4,
    }
    return schemas, registry


def test_scenario_inventory_matches_disk():
    """
    Sentinel Test: Verifies scenario corpus count matches disk expectation (>5,000 files).
    Ensures xdist worker distribution operates on a complete, un-truncated scenario corpus.
    """
    total_count = len(ALL_SCENARIO_PATHS)
    assert total_count > 5000, (
        f"Corpus inventory failure: Expected >5000 scenarios on disk under industries/, "
        f"but discovered only {total_count}!"
    )


@pytest.mark.parametrize("rel_path", ALL_SCENARIO_PATHS)
def test_scenario_compliance(rel_path: str, schema_registry_and_specs):
    """
    Parametrized Test: Validates an individual scenario JSON file against its AES schema version.
    Distributed across workers by pytest-xdist for full parallelization.
    Strict Exception Hygiene: Catches only json.JSONDecodeError and ValidationError.
    Unexpected validator/code defects crash loudly without silent suppression.
    """
    schemas, registry = schema_registry_and_specs
    abs_path = BASE_DIR / rel_path

    assert abs_path.exists(), f"Scenario file not found on disk: {rel_path}"
    content = abs_path.read_text(encoding="utf-8").strip()
    assert content, f"Scenario file is empty: {rel_path}"

    # 1. JSON Parsing (Explicit Exception Hygiene)
    try:
        scenario = json.loads(content)
    except json.JSONDecodeError as exc:
        pytest.fail(f"Scenario JSONDecodeError in {rel_path}: {exc}")

    assert isinstance(scenario, dict), f"Scenario root in {rel_path} is not a JSON object"

    # 2. Multi-Version Schema Dispatch
    aes_version = scenario.get("aes_version", 1.4)
    target_schema = schemas.get(aes_version, schemas[1.4])

    # 3. Schema Validation (Explicit Exception Hygiene)
    try:
        validate(instance=scenario, schema=target_schema, registry=registry)
    except ValidationError as exc:
        pytest.fail(f"Scenario ValidationError in {rel_path} (AES v{aes_version}): {exc.message}")
