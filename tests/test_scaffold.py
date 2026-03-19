import pytest
import json
from pathlib import Path
from unittest.mock import patch
from eval_runner.scaffold import generate_interactive

def test_scaffold_generation(tmp_path, monkeypatch):
    # Mock input
    inputs = iter(["telecom", "reboot", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    
    # Run in tmp_path
    monkeypatch.chdir(tmp_path)
    
    with patch("builtins.print"):
        generate_interactive()
        
    expected_file = tmp_path / "scenarios" / "telecom" / "gen_telecom_reboot_1.json"
    assert expected_file.exists()
    
    with open(expected_file, "r") as f:
        data = json.load(f)
        assert data["industry"] == "telecom"
        assert data["use_case"] == "reboot"
