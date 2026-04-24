import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import json

import pytest
from jsonschema import validate

from eval_runner import scaffold

# Resolve paths
BASE_DIR = Path(__file__).parent.parent.parent.parent
SCHEMA_PATH = BASE_DIR / "spec" / "aes" / "aes.schema.json"


@pytest.fixture
def scenario_schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_generated_scenario_compliance(tmp_path, scenario_schema, monkeypatch):
    """
    Test that the interactive generator produces schema-compliant JSON.
    We mock the inputs to 'generate_interactive' and check the output.
    """
    from referencing import Registry, Resource

    resource = Resource.from_contents(scenario_schema)
    base_uri = SCHEMA_PATH.parent.as_uri() + "/"
    registry = Registry().with_resource(base_uri, resource)

    # Register definitions to enable $ref resolution in tests
    defs_dir = SCHEMA_PATH.parent / "definitions"
    for def_file in defs_dir.glob("*.json"):
        with open(def_file, encoding="utf-8") as df:
            def_content = json.load(df)
            # Register using absolute file URI
            def_uri = def_file.as_uri()
            # Also register as relative to the parent for $ref: "definitions/..."
            rel_uri = base_uri + "definitions/" + def_file.name

            res = Resource.from_contents(def_content)
            registry = registry.with_resource(def_uri, res)
            registry = registry.with_resource(rel_uri, res)

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
    with open(gen_file, encoding="utf-8") as f:
        generated_json = json.load(f)

    # This will raise ValidationError if invalid
    # Inject $id to enable relative $ref resolution
    scenario_schema["$id"] = SCHEMA_PATH.as_uri()
    validate(instance=generated_json, schema=scenario_schema, registry=registry)

    # Check specific fields
    assert generated_json["industry"] == "fintech"
    assert "workflow" in generated_json
    assert "expected_outcome" in generated_json["workflow"]["nodes"][0]
