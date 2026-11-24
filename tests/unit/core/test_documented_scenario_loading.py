import json

import pytest
import yaml

from eval_runner.loader import load_dataset, load_scenario


def scenario(identifier):
    return {
        "aes_version": 1.4,
        "metadata": {
            "id": identifier,
            "name": "Unicode scenario café",
            "compliance_level": "Standard",
        },
        "workflow": {
            "nodes": [{"id": "task", "task_description": "Return the requested answer."}],
            "edges": [],
        },
        "evaluation": {},
    }


@pytest.mark.parametrize("suffix", [".yaml", ".yml", ".aes.yaml"])
def test_yaml_scenarios_load_through_file_and_dataset_entrypoints(tmp_path, suffix):
    path = tmp_path / f"scenario{suffix}"
    path.write_text(yaml.safe_dump(scenario("yaml-example"), allow_unicode=True), encoding="utf-8")
    loaded = load_scenario(path)
    assert loaded["metadata"]["name"] == "Unicode scenario café"
    assert load_dataset(path)[0]["id"] == "yaml-example"


def test_directory_loading_includes_nested_json_yaml_and_yml_once(tmp_path):
    for index, suffix in enumerate((".json", ".yaml", ".yml", ".aes.yaml")):
        directory = tmp_path / str(index)
        directory.mkdir()
        data = scenario(f"example-{index}")
        text = json.dumps(data) if suffix == ".json" else yaml.safe_dump(data)
        (directory / f"scenario{suffix}").write_text(text, encoding="utf-8")
    assert {row["id"] for row in load_dataset(tmp_path)} == {
        "example-0",
        "example-1",
        "example-2",
        "example-3",
    }


def test_yaml_rejects_non_object_and_unsafe_constructor(tmp_path):
    path = tmp_path / "scenario.yaml"
    path.write_text("- item\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Scenario must be an object"):
        load_scenario(path)
    path.write_text("!!python/object:unknown.Type {}", encoding="utf-8")
    with pytest.raises(yaml.constructor.ConstructorError):
        load_scenario(path)
