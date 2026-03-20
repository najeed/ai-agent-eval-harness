import json
import pytest
from pathlib import Path
from jsonschema import validate
from eval_runner import scaffold

# Resolve paths
BASE_DIR = Path(__file__).parent.parent
SCHEMA_PATH = BASE_DIR / "schemas" / "scenario.schema.json"


@pytest.fixture
def scenario_schema():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_generated_scenario_compliance(tmp_path, scenario_schema, monkeypatch):
    """
    Test that the interactive generator produces schema-compliant JSON.
    We mock the inputs to 'generate_interactive' and check the output.
    """
    # Mock inputs: Industry=fintech, Capability=credit_score, Count=1
    inputs = iter(["fintech", "credit_score", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    # Change CWD to tmp_path so 'scenarios/' dir is created there
    monkeypatch.chdir(tmp_path)

    # Run generation
    scaffold.generate_interactive()

    # Verify file exists
    gen_dir = tmp_path / "scenarios" / "fintech"
    gen_file = gen_dir / "gen_fintech_credit_score_1.json"
    assert gen_file.exists()

    # Validate against schema
    with open(gen_file, "r", encoding="utf-8") as f:
        generated_json = json.load(f)

    # This will raise ValidationError if invalid
    validate(instance=generated_json, schema=scenario_schema)

    # Check specific fields
    assert generated_json["use_case"] == "credit_score"
    assert generated_json["industry"] == "fintech"
    assert "tasks" in generated_json
    assert "expected_outcome" in generated_json["tasks"][0]
    assert "success_criteria" in generated_json["tasks"][0]
