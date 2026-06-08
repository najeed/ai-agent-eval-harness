"""
test_mutator.py

Unit tests for the adversarial mutation engine.
"""

import json

from eval_runner import mutator


def test_mutator_typo():
    """Verify typo mutation replaces characters."""
    scenario = {
        "aes_version": 1.4,
        "id": "typo_test",
        "title": "Typo Test",
        "industry": "test",
        "description": "test",
        "metadata": {"name": "typo_test", "compliance_level": "Standard"},
        "workflow": {
            "nodes": [{"id": "n1", "task_description": "Please clone the repo"}],
            "edges": [],
        },
    }
    mutated = mutator.mutate_scenario(scenario, "typo")
    desc = mutated["workflow"]["nodes"][0]["task_description"]
    assert desc != "Please clone the repo"
    assert len(desc) > 0


def test_mutator_ambiguity():
    """Verify ambiguity mutation adds confusing phrases."""
    scenario = {
        "aes_version": 1.4,
        "id": "ambiguity_test",
        "title": "Ambiguity Test",
        "industry": "test",
        "description": "test",
        "metadata": {"name": "ambiguity_test", "compliance_level": "Standard"},
        "workflow": {"nodes": [{"id": "n1", "task_description": "Clone the repo"}], "edges": []},
    }
    mutated = mutator.mutate_scenario(scenario, "ambiguity")
    desc = mutated["workflow"]["nodes"][0]["task_description"]
    fillers = ["I think", "maybe", "if you can", "sure though"]
    assert any(f in desc for f in fillers)
    assert desc != "Clone the repo"


def test_mutator_injection():
    """Verify injection mutation adds adversarial instructions."""
    scenario = {
        "aes_version": 1.4,
        "id": "injection_test",
        "title": "Injection Test",
        "industry": "test",
        "description": "test",
        "metadata": {"name": "injection_test", "compliance_level": "Standard"},
        "workflow": {"nodes": [{"id": "n1", "task_description": "Clone the repo"}], "edges": []},
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
    with open(output_file) as f:
        data = json.load(f)
    assert data == scenario


def test_mutate_text_with_typos_edge_cases():
    """Verify edge cases and specific branches in mutate_text_with_typos."""
    from unittest.mock import patch

    from eval_runner.mutator import mutate_text_with_typos

    # empty text
    assert mutate_text_with_typos("") == ""

    # Mocking choices to test swap, repeat, delete, and fallback branches
    with patch("random.random", return_value=0.0):
        # 1. Swap
        with patch("random.choice", return_value="swap"):
            res = mutate_text_with_typos("ab")
            assert res == "ba"

        # 2. Repeat
        with patch("random.choice", return_value="repeat"):
            res = mutate_text_with_typos("a")
            assert res == "aa"

        # 3. Delete
        with patch("random.choice", return_value="delete"):
            res = mutate_text_with_typos("ab")
            assert res == ""

        # 4. Unreachable Else branch (choice = "invalid")
        with patch("random.choice", return_value="invalid"):
            res = mutate_text_with_typos("ab")
            assert res == "ba"

    # Guarantee branch (not mutated, probability > 0)
    # 1. idx > 0
    with patch("random.random", return_value=0.9), patch("random.randint", return_value=1):
        assert mutate_text_with_typos("ab", probability=0.1) == "ba"

    # 2. idx == 0 and len > 1
    with patch("random.random", return_value=0.9), patch("random.randint", return_value=0):
        assert mutate_text_with_typos("ab", probability=0.1) == "ba"

    # 3. len == 1
    with patch("random.random", return_value=0.9), patch("random.randint", return_value=0):
        assert mutate_text_with_typos("a", probability=0.1) == ""


def test_core_mutator_can_mutate():
    """Verify CoreMutator.can_mutate branch coverage."""
    from eval_runner.mutator import CoreMutator

    mutator_obj = CoreMutator()
    assert mutator_obj.can_mutate("typos") is True
    assert mutator_obj.can_mutate("invalid_mutation") is False


def test_core_mutator_metadata_id():
    """Verify CoreMutator updates metadata id if present."""
    scenario = {
        "id": "base",
        "metadata": {"id": "meta_base"},
        "workflow": {"nodes": [{"id": "n1", "task_description": "text"}]},
    }
    mutated = mutator.mutate_scenario(scenario, "typos")
    assert mutated["metadata"]["id"] == "meta_base_mutated_typos"


def test_mutation_service_recursion_protection():
    """Verify that MutationService raises RecursionError on cycle (>50 depth)."""
    import pytest

    from eval_runner.mutator import MutationService, ScenarioMutator

    service = MutationService()

    class DummyMutator(ScenarioMutator):
        def can_mutate(self, mutation_type: str) -> bool:
            return True

        def mutate(self, scenario: dict, mutation_type: str, next_mutator) -> dict:
            return next_mutator(scenario, mutation_type)

    for _ in range(55):
        service.register_provider(DummyMutator())

    scenario = {
        "id": "base",
        "workflow": {"nodes": []},
    }
    with pytest.raises(RecursionError) as exc_info:
        service.mutate(scenario, "typos")
    assert "Max interceptor" in str(exc_info.value)


def test_mutation_service_negative_intercept():
    """Verify that MutationService bypasses provider if can_mutate returns False."""
    from eval_runner.mutator import MutationService, ScenarioMutator

    service = MutationService()

    class SkipMutator(ScenarioMutator):
        def can_mutate(self, mutation_type: str) -> bool:
            return False

        def mutate(self, scenario: dict, mutation_type: str, next_mutator) -> dict:
            scenario["skipped"] = False
            return next_mutator(scenario, mutation_type)

    service.register_provider(SkipMutator())
    scenario = {
        "id": "base",
        "workflow": {"nodes": []},
    }
    res = service.mutate(scenario, "typos")
    assert "skipped" not in res
