"""
test_mutator_regression.py

Regression test suite verifying the hardened mutator pipeline and generic extensibility framework.
Covers thread isolation, guarded exception propagation, payload shielding, and async execution.
"""

import threading
import time
from collections.abc import Callable, Coroutine

import pytest

from eval_runner.mutator import (
    ScenarioMutator,
    mutate_scenario,
    mutation_service,
)
from eval_runner.utils.pipeline import (
    AsyncInterceptor,
    AsyncPipelineService,
    Interceptor,
    PipelineService,
)

# =====================================================================
# 1. Mutator Service Concurrency, Shielding, and Exception Hardening
# =====================================================================


class CrashyMutator(ScenarioMutator):
    """Bypassed plugin that throws standard RuntimeError."""

    def can_mutate(self, mutation_type: str) -> bool:
        return True

    def mutate(self, scenario: dict, mutation_type: str, next_mutator: Callable) -> dict:
        raise RuntimeError("Something went wrong internally in plugin")


class SystemAbortMutator(ScenarioMutator):
    """Critical plugin that throws a system-critical control exception."""

    def __init__(self, exception_class):
        self.exception_class = exception_class

    def can_mutate(self, mutation_type: str) -> bool:
        return True

    def mutate(self, scenario: dict, mutation_type: str, next_mutator: Callable) -> dict:
        raise self.exception_class("System force exit requested")


class MaliciousMutator(ScenarioMutator):
    """Plugin attempting to illegally mutate the scenario state in-place."""

    def can_mutate(self, mutation_type: str) -> bool:
        return True

    def mutate(self, scenario: dict, mutation_type: str, next_mutator: Callable) -> dict:
        # Directly modify scenario state
        scenario["workflow"]["nodes"][0]["task_description"] = "MUTATED_BY_PLUGIN"
        return next_mutator(scenario, mutation_type)


@pytest.fixture(autouse=True)
def clean_mutation_service():
    mutation_service.reset()
    yield
    mutation_service.reset()


def test_standard_exception_fault_tolerance():
    """Verify that a standard Exception is caught, logged, and gracefully bypassed."""
    scenario = {
        "id": "base",
        "workflow": {"nodes": [{"id": "n1", "task_description": "Initial text"}]},
    }
    mutation_service.register_provider(CrashyMutator())

    # Should gracefully bypass CrashyMutator and fall back to standard core mutations
    mutated = mutate_scenario(scenario, "ambiguity")
    assert mutated["id"] == "base_mutated_ambiguity"
    assert "Initial text" in mutated["workflow"]["nodes"][0]["task_description"]


@pytest.mark.parametrize("exc", [RecursionError, KeyboardInterrupt, SystemExit, GeneratorExit])
def test_critical_exceptions_propagate(exc):
    """Verify that system-critical control exceptions are never swallowed."""
    scenario = {
        "id": "base",
        "workflow": {"nodes": [{"id": "n1", "task_description": "Initial text"}]},
    }
    mutation_service.register_provider(SystemAbortMutator(exc))

    with pytest.raises(exc):
        mutate_scenario(scenario, "ambiguity")


def test_payload_deep_copy_shielding():
    """Verify that a plugin attempting to modify scenario state in-place
    is successfully isolated.
    """
    scenario = {
        "id": "base",
        "workflow": {"nodes": [{"id": "n1", "task_description": "Safe text"}]},
    }
    mutation_service.register_provider(MaliciousMutator())

    # Mutator execution occurs
    mutated = mutate_scenario(scenario, "ambiguity")

    # Original scenario must remain completely untouched
    assert scenario["workflow"]["nodes"][0]["task_description"] == "Safe text"
    # Mutated scenario has the changes
    assert "MUTATED_BY_PLUGIN" in mutated["workflow"]["nodes"][0]["task_description"]


def test_thread_concurrency_isolation():
    """Verify that different threads registering plugins concurrently
    operate in completely isolated registries.
    """
    scenario = {
        "id": "base",
        "workflow": {"nodes": [{"id": "n1", "task_description": "Clean state"}]},
    }

    class ThreadSpecificMutator(ScenarioMutator):
        def __init__(self, suffix):
            self.suffix = suffix

        def can_mutate(self, mutation_type: str) -> bool:
            return True

        def mutate(self, scenario: dict, mutation_type: str, next_mutator: Callable) -> dict:
            res = next_mutator(scenario, mutation_type)
            res["thread_mark"] = self.suffix
            return res

    results = {}

    def thread_worker(name, suffix, delay):
        # Register a local provider via the context manager
        mutator = ThreadSpecificMutator(suffix)
        with mutation_service.override_provider(mutator):
            # Hold the override registration to allow concurrency collision window
            time.sleep(delay)
            # Run mutation
            res = mutate_scenario(scenario, "ambiguity")
            results[name] = res

    # Thread 1 registers a provider with mark 'A' and runs
    t1 = threading.Thread(target=thread_worker, args=("Thread_A", "MARK_A", 0.1))
    # Thread 2 registers a provider with mark 'B' and runs
    t2 = threading.Thread(target=thread_worker, args=("Thread_B", "MARK_B", 0.05))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Thread A must only see MARK_A, Thread B must only see MARK_B
    assert results["Thread_A"]["thread_mark"] == "MARK_A"
    assert results["Thread_B"]["thread_mark"] == "MARK_B"


# =====================================================================
# 2. Generic Synchronous & Asynchronous Extensibility Engine
# =====================================================================


def test_sync_pipeline_service():
    """Verify generic PipelineService supports standard interceptor chains."""

    def base_handler(req: str) -> str:
        return req + "_core"

    pipeline = PipelineService[str, str](base_handler, "TestSync")

    class UpperInterceptor(Interceptor[str, str]):
        def can_intercept(self, request: str) -> bool:
            return True

        def intercept(self, request: str, next_interceptor: Callable[[str], str]) -> str:
            res = next_interceptor(request)
            return res.upper()

    pipeline.register_interceptor(UpperInterceptor())
    result = pipeline.execute("hello")
    assert result == "HELLO_CORE"


@pytest.mark.asyncio
async def test_async_pipeline_service():
    """Verify generic AsyncPipelineService natively executes asynchronous interceptor chains."""

    async def async_base_handler(req: str) -> str:
        # Simulate small network boundary latency
        return req + "_core"

    pipeline = AsyncPipelineService[str, str](async_base_handler, "TestAsync")

    class AsyncUpperInterceptor(AsyncInterceptor[str, str]):
        def can_intercept(self, request: str) -> bool:
            return True

        async def intercept(
            self, request: str, next_interceptor: Callable[[str], Coroutine[None, None, str]]
        ) -> str:
            # Native awaitable execution
            res = await next_interceptor(request)
            return res.upper()

    pipeline.register_interceptor(AsyncUpperInterceptor())
    result = await pipeline.execute("async_hello")
    assert result == "ASYNC_HELLO_CORE"
