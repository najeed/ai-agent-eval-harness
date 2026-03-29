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
    scenario = {
        "aes_version": 1.2,
        "scenario_id": "typo_test",
        "title": "Typo Test",
        "industry": "test",
        "description": "test",
        "metadata": {"name": "typo_test", "compliance_level": "Standard"},
        "workflow": {
            "nodes": [{"id": "n1", "task_description": "Please clone the repo"}],
            "edges": []
        }
    }
    mutated = mutator.mutate_scenario(scenario, "typo")
    desc = mutated["workflow"]["nodes"][0]["task_description"]
    assert desc != "Please clone the repo"
    assert len(desc) > 0


def test_mutator_ambiguity():
    """Verify ambiguity mutation adds confusing phrases."""
    scenario = {
        "aes_version": 1.2,
        "scenario_id": "ambiguity_test",
        "title": "Ambiguity Test",
        "industry": "test",
        "description": "test",
        "metadata": {"name": "ambiguity_test", "compliance_level": "Standard"},
        "workflow": {
            "nodes": [{"id": "n1", "task_description": "Clone the repo"}],
            "edges": []
        }
    }
    mutated = mutator.mutate_scenario(scenario, "ambiguity")
    desc = mutated["workflow"]["nodes"][0]["task_description"]
    fillers = ["I think", "maybe", "if you can", "sure though"]
    assert any(f in desc for f in fillers)
    assert desc != "Clone the repo"


def test_mutator_injection():
    """Verify injection mutation adds adversarial instructions."""
    scenario = {
        "aes_version": 1.2,
        "scenario_id": "injection_test",
        "title": "Injection Test",
        "industry": "test",
        "description": "test",
        "metadata": {"name": "injection_test", "compliance_level": "Standard"},
        "workflow": {
            "nodes": [{"id": "n1", "task_description": "Clone the repo"}],
            "edges": []
        }
    }
    mutated = mutator.mutate_scenario(scenario, "injection")
    desc = mutated["workflow"]["nodes"][0]["task_description"]
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
