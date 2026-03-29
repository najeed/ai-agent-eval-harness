import pytest
import json
import yaml
from pathlib import Path
from eval_runner.handlers.scenarios import handle_aes_validate


class MockArgs:
    def __init__(self, path):
        self.path = path
        self.aes_command = "validate"


def test_aes_validation_success(tmp_path, capsys):
    aes_data = {
        "aes_version": 1.2,
        "metadata": {"name": "test", "compliance_level": "Standard"},
        "description": "test description",
        "industry": "general",
        "workflow": {
            "nodes": [
                {"id": "node_1", "task_description": "hi"}
            ],
            "edges": []
        }
    }
    aes_file = tmp_path / "valid.aes.yaml"
    with open(aes_file, "w") as f:
        yaml.dump(aes_data, f)

    args = MockArgs(str(aes_file))
    handle_aes_validate(args)

    captured = capsys.readouterr()
    assert "✅ valid.aes.yaml: Valid (v1.2)" in captured.out


def test_aes_validation_failure(tmp_path, capsys):
    aes_data = {
        "aes_version": "invalid",  # Should be number
        "metadata": {},  # Missing 'name'
    }
    aes_file = tmp_path / "invalid.aes.yaml"
    with open(aes_file, "w") as f:
        yaml.dump(aes_data, f)

    args = MockArgs(str(aes_file))
    handle_aes_validate(args)

    captured = capsys.readouterr()
    assert "❌ invalid.aes.yaml: Invalid - 'workflow' is a required property" in captured.out


def test_aes_validation_with_complexity_level(tmp_path, capsys):
    """v1.2: metadata is the primary container for governance."""
    aes_data = {
        "aes_version": 1.2,
        "metadata": {
            "name": "complexity_test",
            "compliance_level": "Regulatory_Audit",
            "standards_registry": ["ISO_20022"]
        },
        "description": "test",
        "industry": "finance",
        "workflow": {
            "nodes": [{"id": "n1", "task_description": "audit"}],
            "edges": []
        }
    }
    aes_file = tmp_path / "complexity.aes.yaml"
    with open(aes_file, "w") as f:
        yaml.dump(aes_data, f)

    args = MockArgs(str(aes_file))
    handle_aes_validate(args)

    captured = capsys.readouterr()
    assert "✅ complexity.aes.yaml: Valid (v1.2)" in captured.out
