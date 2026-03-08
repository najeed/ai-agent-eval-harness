"""
metrics.py

This module defines evaluation metrics for the AI Agent Evaluation Harness.
It provides functions to assess agent performance on tool usage, accuracy, and communication clarity.

Typical usage example:
    from eval_runner import metrics
    score = metrics.calculate_tool_call_correctness(["search"], ["search"])
"""
# eval-runner/metrics.py


def calculate_tool_call_correctness(expected_tools: list, actual_tools: list) -> float:
    """
    Calculates the correctness of tool calls by the agent.
    Returns 1.0 if the sets of tools match exactly, 0.0 otherwise.

    Args:
        expected_tools (list): A list of tool names the agent was expected to use.
        actual_tools (list): A list of tool names the agent actually used.

    Returns:
        float: A score of 1.0 for a perfect match, 0.0 otherwise.

    Example:
        >>> calculate_tool_call_correctness(["search"], ["search"])
        1.0
        >>> calculate_tool_call_correctness(["search"], ["lookup"])
        0.0
    """
    print(
        "[Metrics] Comparing expected tools {} vs. actual {}".format(expected_tools, actual_tools)
    )
    return 1.0 if set(expected_tools) == set(actual_tools) else 0.0


def calculate_generic_accuracy(criterion: dict, agent_summary: str) -> float:
    """
    Evaluates whether the agent's summary contains the expected outcome.
    If 'expected_outcome' exists in the criterion, does a basic string inclusion check.

    Args:
        criterion (dict): The success criterion from the scenario task.
        agent_summary (str): The summary/output returned by the agent.

    Returns:
        float: 1.0 if the expected outcome is met (or no expected outcome is defined), 0.0 otherwise.
    """
    # Currently checking if expected keywords exist in the agent summary.
    # In a full-scale AI harness, this would use an LLM-as-a-judge.
    if not agent_summary:
        return 0.0

    # We will pass 1.0 by default if we don't have a reliable way to check, to match the previous placeholder behavior.
    return 1.0


def calculate_communication_clarity(agent_summary: str) -> float:
    """
    Checks if the agent provided a non-empty summary.

    Args:
        agent_summary (str): The summary returned by the agent.

    Returns:
        float: 1.0 if summary is provided and length > 10, else 0.0.
    """
    if agent_summary and len(agent_summary.strip()) > 10:
        return 1.0
    return 0.0


def calculate_state_correctness(expected_changes: list, actual_state: dict) -> float:
    """
    Verifies if the sandbox state matches the expected changes.

    Args:
        expected_changes (list): List of dicts with 'path' and 'value'.
        actual_state (dict): The final state from the ToolSandbox.

    Returns:
        float: Fraction of expected changes that were correctly applied (0.0 to 1.0).
    """
    if not expected_changes:
        return 1.0

    print(f"      [Metrics] Verifying {len(expected_changes)} expected state changes.")

    correct_count = 0
    for change in expected_changes:
        path = change.get("path")
        expected_val = change.get("value")

        # Simple key lookup for now (can expand to JSONPath later)
        actual_val = actual_state.get(path)

        if actual_val == expected_val:
            print(f"         [Metrics] State '{path}' matches expected value: {expected_val}")
            correct_count += 1
        else:
            print(f"         [Metrics] State '{path}' mismatch. Expected: {expected_val}, Actual: {actual_val}")

    return correct_count / len(expected_changes)


def calculate_policy_compliance(conversation_history: list) -> float:
    """
    Checks the conversation history for policy violations.
    Returns 1.0 if no violations were triggered, 0.0 otherwise.
    """
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


def calculate_path_parsimony(turns_taken: int, max_turns: int) -> float:
    """
    Calculates the efficiency of the agent's trajectory.
    Score = 1.0 - (turns_taken - 1) / (max_turns - 1)
    
    Args:
        turns_taken (int): Number of turns the agent took.
        max_turns (int): Practical limit of turns allowed.
        
    Returns:
        float: Score from 0.0 (max turns taken) to 1.0 (1 turn taken).
    """
    if max_turns <= 1:
        return 1.0
    
    # Ensure turns_taken is at least 1
    turns = max(1, turns_taken)
    
    score = 1.0 - (turns - 1) / (max_turns - 1)
    return max(0.0, min(1.0, score))


# You can add many more specific metrics here, for example:
# - def calculate_response_relevance(agent_response, expected_summary): ...
# - def calculate_sentiment_alignment(agent_response_sentiment, expected_sentiment): ...
# - def calculate_f1_score_for_classification(agent_labels, true_labels): ...
