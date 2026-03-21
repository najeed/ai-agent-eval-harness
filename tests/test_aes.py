import pytest
import json
import yaml
from pathlib import Path
from eval_runner.cli import handle_aes_validate


class MockArgs:
    def __init__(self, path):
        self.path = path
        self.aes_command = "validate"


def test_aes_validation_success(tmp_path, capsys):
    # Setup schema path relative to cli.py location
    # Note: cli.py is in eval_runner/
    # schema is in spec/aes/aes.schema.json

    aes_data = {
        "aes_version": 0.2,
        "metadata": {"name": "test"},
        "task": {"system_prompt": "hi", "user_prompt": "bye"},
        "evaluation": {"success_criteria": []},
    }
    aes_file = tmp_path / "valid.aes.yaml"
    with open(aes_file, "w") as f:
        yaml.dump(aes_data, f)

    args = MockArgs(str(aes_file))
    handle_aes_validate(args)

    captured = capsys.readouterr()
    assert "[OK] valid.aes.yaml: Valid" in captured.out


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
    assert "[FAIL] invalid.aes.yaml: Invalid aes_version" in captured.out


def test_aes_validation_with_enabled_shims(tmp_path, capsys):
    """v0.2: Benchmark with valid enabled_shims list should pass validation."""
    aes_data = {
        "aes_version": 0.2,
        "metadata": {"name": "shim_test"},
        "task": {"system_prompt": "act", "user_prompt": "do"},
        "evaluation": {"success_criteria": []},
        "enabled_shims": ["database", "stripe", "security", "slack"],
    }
    aes_file = tmp_path / "shims.aes.yaml"
    with open(aes_file, "w") as f:
        yaml.dump(aes_data, f)

    args = MockArgs(str(aes_file))
    handle_aes_validate(args)

    captured = capsys.readouterr()
    assert "[OK] shims.aes.yaml: Valid" in captured.out


def test_aes_validation_with_agent_topology(tmp_path, capsys):
    """v0.2: Multi-agent topology with reads/writes permissions should pass."""
    aes_data = {
        "aes_version": 0.2,
        "metadata": {"name": "multi_agent_test"},
        "task": {"system_prompt": "coordinate agents", "user_prompt": "solve task"},
        "evaluation": {"success_criteria": []},
        "agent_topology": {
            "agent_a": {"reads": ["user.*"], "writes": ["user.profile"]},
            "agent_b": {"reads": ["user.*", "order.*"], "writes": ["order.status"]},
        },
    }
    aes_file = tmp_path / "topology.aes.yaml"
    with open(aes_file, "w") as f:
        yaml.dump(aes_data, f)

    args = MockArgs(str(aes_file))
    handle_aes_validate(args)

    captured = capsys.readouterr()
    assert "[OK] topology.aes.yaml: Valid" in captured.out


def test_aes_validation_with_complexity_level(tmp_path, capsys):
    """v0.2: complexity_level must be one of low/medium/high."""
    aes_data = {
        "aes_version": 0.2,
        "metadata": {"name": "complexity_test"},
        "task": {"system_prompt": "hi", "user_prompt": "bye"},
        "evaluation": {"success_criteria": []},
        "complexity_level": "high",
    }
    aes_file = tmp_path / "complexity.aes.yaml"
    with open(aes_file, "w") as f:
        yaml.dump(aes_data, f)

    args = MockArgs(str(aes_file))
    handle_aes_validate(args)

    captured = capsys.readouterr()
    assert "[OK] complexity.aes.yaml: Valid" in captured.out


def test_aes_validation_invalid_complexity_level(tmp_path, capsys):
    """v0.2: complexity_level with an invalid enum value should fail."""
    aes_data = {
        "aes_version": 0.2,
        "metadata": {"name": "bad_complexity"},
        "task": {"system_prompt": "hi", "user_prompt": "bye"},
        "evaluation": {"success_criteria": []},
        "complexity_level": "extreme",  # Not in enum: low/medium/high
    }
    aes_file = tmp_path / "bad_complexity.aes.yaml"
    with open(aes_file, "w") as f:
        yaml.dump(aes_data, f)

    args = MockArgs(str(aes_file))
    handle_aes_validate(args)

    captured = capsys.readouterr()
    assert "[FAIL] bad_complexity.aes.yaml: Invalid complexity_level 'extreme'" in captured.out
