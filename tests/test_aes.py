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
        "aes_version": 0.1,
        "metadata": {"name": "test"},
        "task": {"system_prompt": "hi", "user_prompt": "bye"},
        "evaluation": {"success_criteria": []}
    }
    aes_file = tmp_path / "valid.aes.yaml"
    with open(aes_file, "w") as f:
        yaml.dump(aes_data, f)
    
    args = MockArgs(str(aes_file))
    handle_aes_validate(args)
    
    captured = capsys.readouterr()
    assert "Valid" in captured.out

def test_aes_validation_failure(tmp_path, capsys):
    aes_data = {
        "aes_version": "invalid", # Should be number
        "metadata": {} # Missing 'name'
    }
    aes_file = tmp_path / "invalid.aes.yaml"
    with open(aes_file, "w") as f:
        yaml.dump(aes_data, f)
    
    args = MockArgs(str(aes_file))
    handle_aes_validate(args)
    
    captured = capsys.readouterr()
    assert "Invalid" in captured.out
