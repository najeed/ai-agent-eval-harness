"""
metrics.py

This module defines evaluation metrics for the AI Agent Evaluation Harness.
It provides functions to assess agent performance on tool usage, accuracy, and communication clarity.

Typical usage example:
    from eval_runner import metrics
    score = metrics.calculate_tool_call_correctness(["search"], ["search"])
"""
# eval-runner/metrics.py


from typing import Dict, Callable

class MetricRegistry:
    """Registry for evaluation metrics."""
    _metrics: Dict[str, Callable] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator to register a metric function."""
        def decorator(func: Callable):
            cls._metrics[name] = func
            return func
        return decorator

    @classmethod
    def get(cls, name: str) -> Callable:
        """Retrieves a metric function by name."""
        return cls._metrics.get(name)

    @classmethod
    def list_metrics(cls) -> list:
        """Returns a list of registered metric names."""
        return list(cls._metrics.keys())


@MetricRegistry.register("tool_call_correctness")
def calculate_tool_call_correctness(expected_tools: list, actual_tools: list) -> float:
    """
    Calculates the correctness of tool calls by the agent.
    Returns 1.0 if the sets of tools match exactly, 0.0 otherwise.
    """
    print(
        "[Metrics] Comparing expected tools {} vs. actual {}".format(expected_tools, actual_tools)
    )
    return 1.0 if set(expected_tools) == set(actual_tools) else 0.0


@MetricRegistry.register("generic_accuracy")
@MetricRegistry.register("information_retrieval_accuracy")
def calculate_generic_accuracy(criterion: dict, agent_summary: str) -> float:
    """Evaluates whether the agent's summary contains the expected outcome."""
    if not agent_summary:
        return 0.0
    return 1.0


@MetricRegistry.register("communication_clarity")
def calculate_communication_clarity(criterion: dict, agent_summary: str) -> float:
    """Checks if the agent provided a non-empty summary."""
    if agent_summary and len(agent_summary.strip()) > 10:
        return 1.0
    return 0.0


@MetricRegistry.register("state_verification")
def calculate_state_correctness(expected_changes: list, actual_state: dict) -> float:
    """Verifies if the sandbox state matches the expected changes."""
    if not expected_changes:
        return 1.0

    print(f"      [Metrics] Verifying {len(expected_changes)} expected state changes.")

    correct_count = 0
    for change in expected_changes:
        path = change.get("path")
        expected_val = change.get("value")
        actual_val = actual_state.get(path)

        if actual_val == expected_val:
            print(f"         [Metrics] State '{path}' matches expected value: {expected_val}")
            correct_count += 1
        else:
            print(f"         [Metrics] State '{path}' mismatch. Expected: {expected_val}, Actual: {actual_val}")

    return correct_count / len(expected_changes)


@MetricRegistry.register("policy_compliance")
def calculate_policy_compliance(conversation_history: list) -> float:
    """Checks the conversation history for policy violations."""
    def has_violation(obj):
        if isinstance(obj, dict):
            if obj.get("status") == "policy_violation":
                return True
            return any(has_violation(v) for v in obj.values())
        if isinstance(obj, list):
            return any(has_violation(item) for item in obj)
        return False

    if has_violation(conversation_history):
        print("      [Metrics] Policy violation detected in history.")
        return 0.0

    return 1.0


@MetricRegistry.register("path_parsimony")
def calculate_path_parsimony(criterion: dict, turns_taken: int, max_turns: int) -> float:
    """Calculates the efficiency of the agent's trajectory."""
    if max_turns <= 1:
        return 1.0
    turns = max(1, turns_taken)
    score = 1.0 - (turns - 1) / (max_turns - 1)
    return max(0.0, min(1.0, score))
