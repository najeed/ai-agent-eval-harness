"""
test_mutator_pipeline.py

Unit tests for the Pipeline/Interceptor Middleware (Chain of Responsibility) mutator service.
Verifies priority routing, preemption, augmentation, post-processing, and state isolation.
"""

from collections.abc import Callable

import pytest

from eval_runner.mutator import (
    ScenarioMutator,
    mutate_scenario,
    mutation_service,
)


class EnterpriseStressorMutator(ScenarioMutator):
    """Mocks an Enterprise-level mutator that preempts standard core handling."""

    def can_mutate(self, mutation_type: str) -> bool:
        return mutation_type == "stressor"

    def mutate(
        self, scenario: dict, mutation_type: str, next_mutator: Callable[[dict, str], dict]
    ) -> dict:
        # Preempt: Return custom stressor mutation without calling next
        res = scenario.copy()
        res["id"] = scenario.get("id", "") + "_stressor"
        res["stressed"] = True
        return res


class PrefixAugmentingMutator(ScenarioMutator):
    """Mocks a mutator that augments task descriptions before downstream mutators run."""

    def can_mutate(self, mutation_type: str) -> bool:
        return mutation_type in ["ambiguity"]

    def mutate(
        self, scenario: dict, mutation_type: str, next_mutator: Callable[[dict, str], dict]
    ) -> dict:
        import json

        modified = json.loads(json.dumps(scenario))
        workflow = modified.setdefault("workflow", {})
        nodes = workflow.setdefault("nodes", [])
        for node in nodes:
            node["task_description"] = "[AUGMENTED] " + node.get("task_description", "")
        # Forward to downstream mutators (like CoreMutator)
        return next_mutator(modified, mutation_type)


class TelemetryPostProcessor(ScenarioMutator):
    """Mocks a mutator that decorates downstream mutation output with metadata."""

    def can_mutate(self, mutation_type: str) -> bool:
        # Intercept everything to post-process
        return True

    def mutate(
        self, scenario: dict, mutation_type: str, next_mutator: Callable[[dict, str], dict]
    ) -> dict:
        # Execute the next steps in the pipeline first
        result = next_mutator(scenario, mutation_type)
        # Post-process decoration
        result["telemetry_verified"] = True
        return result


@pytest.fixture(autouse=True)
def clean_mutation_service():
    """Ensure the global mutation_service registry is clean before and after each test."""
    mutation_service.reset()
    yield
    mutation_service.reset()


def test_pipeline_fallback():
    """Verify that when no plugins are active, CoreMutator handles requests normally."""
    scenario = {
        "id": "base",
        "workflow": {"nodes": [{"id": "n1", "task_description": "Initial text"}]},
    }
    # Standard Core mutation type should work
    mutated = mutate_scenario(scenario, "injection")
    assert "Ignore all previous instructions" in mutated["workflow"]["nodes"][0]["task_description"]


def test_pipeline_preemption():
    """Verify an interceptor can preempt and handle novel mutation types fully."""
    scenario = {
        "id": "base",
        "workflow": {"nodes": [{"id": "n1", "task_description": "Initial text"}]},
    }

    # Core doesn't handle "stressor" - should fallback to core mutator (which just adds suffix)
    mutated_fallback = mutate_scenario(scenario, "stressor")
    assert mutated_fallback["id"] == "base_mutated_stressor"
    assert "stressed" not in mutated_fallback

    # Register the preempting mutator
    mutation_service.register_provider(EnterpriseStressorMutator())

    # Now the registered provider should handle it and short-circuit the pipeline
    mutated_preempt = mutate_scenario(scenario, "stressor")
    assert mutated_preempt["id"] == "base_stressor"
    assert mutated_preempt["stressed"] is True


def test_pipeline_augmentation():
    """Verify an interceptor can augment data in-flight before passing downstream."""
    scenario = {
        "id": "base",
        "workflow": {"nodes": [{"id": "n1", "task_description": "Clone the repo"}]},
    }

    # Register the augmenting mutator
    mutation_service.register_provider(PrefixAugmentingMutator())

    # This should run the prefix augmenter, then forward to CoreMutator which performs ambiguity
    mutated = mutate_scenario(scenario, "ambiguity")
    desc = mutated["workflow"]["nodes"][0]["task_description"]

    assert desc.startswith("[AUGMENTED] ")
    assert desc != "[AUGMENTED] Clone the repo"


def test_pipeline_post_processing():
    """Verify an interceptor can execute downstream mutators first, then decorate the output."""
    scenario = {
        "id": "base",
        "workflow": {"nodes": [{"id": "n1", "task_description": "Clone the repo"}]},
    }

    # Register the post-processor
    mutation_service.register_provider(TelemetryPostProcessor())

    mutated = mutate_scenario(scenario, "ambiguity")
    # Output should contain standard ambiguity mutation AND telemetry verification
    assert mutated["telemetry_verified"] is True
    assert mutated["id"] == "base_mutated_ambiguity"


def test_pipeline_state_isolation():
    """Verify that calling reset() fully restores the registry to its core state."""
    mutation_service.register_provider(EnterpriseStressorMutator())
    assert len(mutation_service._providers) == 1

    mutation_service.reset()
    assert len(mutation_service._providers) == 0
