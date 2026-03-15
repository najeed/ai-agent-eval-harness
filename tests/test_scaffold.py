import json
import pytest
from pathlib import Path
from unittest.mock import patch
from eval_runner.scaffold import generate_interactive

def test_generate_interactive_logic(tmp_path, monkeypatch):
    """Verifies that the interactive scenario generator produces files correctly."""
    # Mock inputs: Industry 'telecom', Capability 'billing', Count '2'
    inputs = iter(["telecom", "billing", "2"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    
    # Change CWD to tmp_path to capture file generation
    monkeypatch.chdir(tmp_path)
    
    generate_interactive()
    
    # Verify directory structure
    output_dir = tmp_path / "scenarios" / "telecom"
    assert output_dir.exists()
    
    # Verify files
    files = list(output_dir.glob("*.json"))
    assert len(files) == 2
    
    for f in files:
        with open(f, "r") as json_file:
            data = json.load(json_file)
            assert data["industry"] == "telecom"
            assert "billing" in data["title"].lower()
            assert "billing" in data["tasks"][0]["description"].lower()
