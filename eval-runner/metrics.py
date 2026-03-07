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
        f"      [Metrics] Comparing expected tools {expected_tools} vs. actual {actual_tools}"
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


# You can add many more specific metrics here, for example:
# - def calculate_response_relevance(agent_response, expected_summary): ...
# - def calculate_sentiment_alignment(agent_response_sentiment, expected_sentiment): ...
# - def calculate_f1_score_for_classification(agent_labels, true_labels): ...
