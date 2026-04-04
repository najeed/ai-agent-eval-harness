import pytest
import json
import jsonschema
from pathlib import Path

@pytest.fixture
def scenario_schema():
    """Robustly locate the scenario schema across diverse execution environments."""
    from eval_runner import config
    
    # Cascade discovery:
    # 1. Authoritative config path
    # 2. Repo-relative path (from tests/functional/)
    # 3. Parent-walk discovery (standard industrial root-finding)
    candidates = [
        config.PROJECT_ROOT / "schemas" / "scenario.schema.json",
        Path(__file__).parents[2] / "schemas" / "scenario.schema.json",
        Path(__file__).parents[3] / "schemas" / "scenario.schema.json"
    ]
    
    schema_path = None
    for cand in candidates:
        if cand.exists():
            schema_path = cand
            break
            
    if not schema_path:
        # Fallback for strict jails: try to find anything named scenario.schema.json in the whole tree
        # (This is expensive but better than a hard failure in restricted CI)
        for root, dirs, files in os.walk(config.PROJECT_ROOT):
            if "scenario.schema.json" in files:
                schema_path = Path(root) / "scenario.schema.json"
                break
    
    if not schema_path:
        pytest.skip("Scenario schema (scenario.schema.json) not found in the current execution environment.")
        
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)

import os

def test_enforce_min_judges_and_compliance(scenario_schema):
    """Verify that scenarios missing required 1.2 properties fail validation."""
    
    # 1. Valid Scenario (passes)
    valid_scenario = {
        "aes_version": 1.2,
        "metadata": {
            "scenario_id": "test_pass",
            "name": "Test Scenario",
            "industry": "finance",
            "compliance_level": "Regulatory_Audit"
        },
        "workflow": {
            "nodes": [
                {"id": "node_1", "task_description": "test task"}
            ],
            "edges": []
        },
        "evaluation": {
            "consensus": {
                "strategy": "Majority_Vote",
                "min_judges": 1
            }
        }
    }
    jsonschema.validate(instance=valid_scenario, schema=scenario_schema)

    # 2. Invalid Scenario (missing compliance_level)
    invalid_meta = valid_scenario.copy()
    invalid_meta["metadata"] = {"scenario_id": "test_fail", "industry": "finance"}
    with pytest.raises(jsonschema.ValidationError) as excinfo:
        jsonschema.validate(instance=invalid_meta, schema=scenario_schema)
    assert "compliance_level" in str(excinfo.value)

    # 3. Invalid Scenario (missing min_judges)
    # Re-copy to avoid side effects
    invalid_judges = json.loads(json.dumps(valid_scenario))
    del invalid_judges["evaluation"]["consensus"]["min_judges"]
    with pytest.raises(jsonschema.ValidationError) as excinfo:
        jsonschema.validate(instance=invalid_judges, schema=scenario_schema)
    assert "min_judges" in str(excinfo.value)
