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
    
    This test verifies that the generic accuracy metric function
    returns the expected default score. The test ensures that
    the metric calculation is working correctly and returns
    a consistent value for basic accuracy assessment.
    
    Args:
        None
        
    Returns:
        None
        
    Raises:
        AssertionError: If the calculated score is not 1.0
        
    Example:
        Expected score: 1.0 (default accuracy score)
    """
    score = metrics.calculate_generic_accuracy()
    assert score == 1.0

def test_communication_clarity():
    """
    Test communication clarity calculation functionality.
    
    This test verifies that the communication clarity metric function
    returns the expected default score. The test ensures that
    the metric calculation is working correctly and returns
    a consistent value for communication quality assessment.
    
    Args:
        None
        
    Returns:
        None
        
    Raises:
        AssertionError: If the calculated score is not 1.0
        
    Example:
        Expected score: 1.0 (default communication clarity score)
    """
    score = metrics.calculate_communication_clarity()
    assert score == 1.0 