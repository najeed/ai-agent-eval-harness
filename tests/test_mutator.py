"""
test_mutator.py

Unit tests for the adversarial mutation engine.
"""

import pytest
import json
from pathlib import Path
from eval_runner import mutator


def test_mutator_typo():
    """Verify typo mutation replaces characters."""
    scenario = {"tasks": [{"description": "Please clone the repo"}]}
    mutated = mutator.mutate_scenario(scenario, "typo")
    desc = mutated["tasks"][0]["description"]
    assert desc != "Please clone the repo"
    # Basic check: should still be somewhat similar
    assert len(desc) > 0


def test_mutator_ambiguity():
    """Verify ambiguity mutation adds confusing phrases."""
    scenario = {"tasks": [{"description": "Clone the repo"}]}
    mutated = mutator.mutate_scenario(scenario, "ambiguity")
    desc = mutated["tasks"][0]["description"]
    fillers = ["I think", "maybe", "if you can", "sure though"]
    assert any(f in desc for f in fillers)
    assert desc != "Clone the repo"


def test_mutator_injection():
    """Verify injection mutation adds adversarial instructions."""
    scenario = {"tasks": [{"description": "Clone the repo"}]}
    mutated = mutator.mutate_scenario(scenario, "injection")
    desc = mutated["tasks"][0]["description"]
    assert "Ignore all previous instructions" in desc


def test_save_mutated_scenario(tmp_path):
    """Verify saving mutated scenario to file."""
    scenario = {"test": "data"}
    output_file = tmp_path / "mutated.json"
    mutator.save_mutated_scenario(scenario, output_file)
    assert output_file.exists()
    with open(output_file, "r") as f:
        data = json.load(f)
    assert data == scenario
