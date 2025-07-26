import pytest
import sys
from pathlib import Path

# Add the eval-runner directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "eval-runner"))

# Import the metrics module directly
import metrics

def test_tool_call_correctness_exact_match():
    expected = ["a", "b"]
    actual = ["b", "a"]
    score = metrics.calculate_tool_call_correctness(expected, actual)
    assert score == 1.0

def test_tool_call_correctness_mismatch():
    expected = ["a", "b"]
    actual = ["a"]
    score = metrics.calculate_tool_call_correctness(expected, actual)
    assert score == 0.0

def test_generic_accuracy():
    score = metrics.calculate_generic_accuracy()
    assert score == 1.0

def test_communication_clarity():
    score = metrics.calculate_communication_clarity()
    assert score == 1.0 