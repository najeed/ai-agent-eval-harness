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
    from jsonschema import RefResolver, validate

    schema, schema_path = scenario_schema
    resolver = RefResolver(f"file:///{schema_path.parent.as_posix()}/", schema)

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
    validate(instance=valid_scenario, schema=schema, resolver=resolver)

    # 2. Invalid Scenario (missing compliance_level)
    invalid_meta = json.loads(json.dumps(valid_scenario))
    invalid_meta["metadata"] = {
        "name": "Fail Scenario",
        "id": "test_fail",
        "industry": "finance",
    }
    with pytest.raises(jsonschema.ValidationError) as excinfo:
        validate(instance=invalid_meta, schema=schema, resolver=resolver)
    assert "compliance_level" in str(excinfo.value)

    # 3. Invalid Scenario (missing min_judges)
    invalid_judges = json.loads(json.dumps(valid_scenario))
    del invalid_judges["evaluation"]["consensus"]["min_judges"]
    with pytest.raises(jsonschema.ValidationError) as excinfo:
        validate(instance=invalid_judges, schema=schema, resolver=resolver)
    assert "min_judges" in str(excinfo.value)
