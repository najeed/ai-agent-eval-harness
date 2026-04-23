import json
from pathlib import Path

import jsonschema
import pytest


@pytest.fixture
def scenario_schema():
    """Robustly locate the AES schema across diverse execution environments."""
    from eval_runner import config

    # Cascade discovery centered on the hardened AES v1.4.0 root
    candidates = [
        config.PROJECT_ROOT / "spec" / "aes" / "aes.schema.json",
        Path(__file__).parents[2] / "spec" / "aes" / "aes.schema.json",
    ]

    schema_path = None
    for cand in candidates:
        if cand.exists():
            schema_path = cand
            break

    if not schema_path:
        pytest.fail(
            "Authoritative AES schema (aes.schema.json) not found. "
            "Forensic environment sync is required."
        )

    with open(schema_path, encoding="utf-8") as f:
        return json.load(f), schema_path


def test_enforce_min_judges_and_compliance(scenario_schema):
    """Verify that scenarios missing required v1.4 properties fail validation."""
    from jsonschema.validators import validator_for
    from referencing import Registry, Resource

    schema, schema_path = scenario_schema

    # Industrial Migration: Use Registry for 4.18+
    def _get_definitions():
        defs = {}
        defs_dir = schema_path.parent / "definitions"
        if defs_dir.exists():
            for fpath in defs_dir.glob("*.json"):
                with open(fpath) as f_def:
                    defs[f"definitions/{fpath.name}"] = json.load(f_def)
        return defs

    definitions = _get_definitions()
    registry = Registry()
    for ref_path, def_schema in definitions.items():
        registry = registry.with_resource(uri=ref_path, resource=Resource.from_contents(def_schema))

    validator_cls = validator_for(schema)
    validator = validator_cls(schema, registry=registry)

    # 1. Valid Scenario (passes v1.4.0)
    valid_scenario = {
        "aes_version": 1.4,
        "metadata": {
            "name": "Industrial Compliance Test",
            "id": "test_pass",
            "industry": "finance",
            "compliance_level": "Regulatory_Audit",
        },
        "workflow": {"nodes": [{"id": "node_1", "task_description": "test task"}], "edges": []},
        "evaluation": {"consensus": {"strategy": "Majority_Vote", "min_judges": 1}},
    }
    validator.validate(valid_scenario)

    # 2. Invalid Scenario (missing compliance_level)
    invalid_meta = json.loads(json.dumps(valid_scenario))
    invalid_meta["metadata"] = {
        "name": "Fail Scenario",
        "id": "test_fail",
        "industry": "finance",
    }
    with pytest.raises(jsonschema.ValidationError) as excinfo:
        validator.validate(invalid_meta)
    assert "compliance_level" in str(excinfo.value)

    # 3. Invalid Scenario (missing min_judges)
    invalid_judges = json.loads(json.dumps(valid_scenario))
    del invalid_judges["evaluation"]["consensus"]["min_judges"]
    with pytest.raises(jsonschema.ValidationError) as excinfo:
        validator.validate(invalid_judges)
    assert "min_judges" in str(excinfo.value)
