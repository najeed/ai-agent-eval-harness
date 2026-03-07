"""
Test suite for evaluation metrics calculation and validation.

This module contains comprehensive tests for the metrics calculation system,
including tool call correctness, generic accuracy, and communication clarity
metrics. The tests ensure that the metrics module can properly calculate
scores for various evaluation criteria and handle different input scenarios.

The test suite covers:
- Tool call correctness with exact matches and mismatches
- Generic accuracy calculation
- Communication clarity assessment
- Edge cases and boundary conditions

Example:
    To run these tests specifically:
    pytest tests/test_metrics.py -v
"""

import pytest
import sys
from pathlib import Path

# Add the eval-runner directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "eval-runner"))

# Import the metrics module directly
import metrics

def test_tool_call_correctness_exact_match():
    """
    Test tool call correctness calculation with exact tool matches.
    
    This test verifies that the tool call correctness metric returns
    a perfect score (1.0) when the expected tools exactly match the
    actual tools used, regardless of order. The test ensures that
    the metric correctly identifies when all required tools were
    properly utilized by the agent.
    
    Args:
        None
        
    Returns:
        None
        
    Raises:
        AssertionError: If the calculated score is not 1.0
        
    Example:
        Expected tools: ["a", "b"]
        Actual tools: ["b", "a"]
        Expected score: 1.0 (perfect match regardless of order)
    """
    expected = ["a", "b"]
    actual = ["b", "a"]
    score = metrics.calculate_tool_call_correctness(expected, actual)
    assert score == 1.0

def test_tool_call_correctness_mismatch():
    """
    Test tool call correctness calculation with tool mismatches.
    
    This test verifies that the tool call correctness metric returns
    a zero score (0.0) when the actual tools used don't match the
    expected tools. The test ensures that the metric properly penalizes
    cases where the agent fails to use the required tools or uses
    incorrect tools.
    
    Args:
        None
        
    Returns:
        None
        
    Raises:
        AssertionError: If the calculated score is not 0.0
        
    Example:
        Expected tools: ["a", "b"]
        Actual tools: ["a"]
        Expected score: 0.0 (missing required tool "b")
    """
    expected = ["a", "b"]
    actual = ["a"]
    score = metrics.calculate_tool_call_correctness(expected, actual)
    assert score == 0.0

def test_generic_accuracy():
    """
    Test generic accuracy calculation functionality.
    
    Verifies that calculate_generic_accuracy returns 1.0 when a non-empty
    agent summary is provided, and 0.0 when it is empty.
    """
    criterion = {"metric": "information_retrieval_accuracy", "threshold": 0.8}
    score = metrics.calculate_generic_accuracy(criterion, "Agent retrieved customer details successfully.")
    assert score == 1.0

    score_empty = metrics.calculate_generic_accuracy(criterion, "")
    assert score_empty == 0.0

def test_communication_clarity():
    """
    Test communication clarity calculation functionality.
    
    Verifies calculate_communication_clarity returns 1.0 for a sufficiently
    long summary (>10 chars) and 0.0 for an empty or too-short summary.
    """
    score = metrics.calculate_communication_clarity("The issue is with the local Wi-Fi. Guide provided.")
    assert score == 1.0

    score_short = metrics.calculate_communication_clarity("OK")
    assert score_short == 0.0

    score_empty = metrics.calculate_communication_clarity("")
    assert score_empty == 0.0 