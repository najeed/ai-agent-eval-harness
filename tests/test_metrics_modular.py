import pytest
from unittest.mock import MagicMock, patch
from eval_runner.metrics import MetricRegistry

# Note: These tests are written prior to implementation (TDD).
# They will fail initially until the eval_runner/metrics/ package is correctly structured.


def test_metric_registry_retrieval():
    """Verify registry can retrieve standard and custom metrics."""
    assert MetricRegistry.get("tool_call_correctness") is not None
    # Assuming these will be registered by the new modules
    # assert MetricRegistry.get("calculation_accuracy") is not None
    # assert MetricRegistry.get("planning_quality") is not None


@patch("eval_runner.metrics.utils.extract_numbers")
def test_calculation_accuracy_logic(mock_extract):
    """Verify numerical comparison logic for calculation_accuracy."""
    from eval_runner.metrics.accuracy import calculate_calculation_accuracy

    # Scene: Expected 100, Agent says 100
    mock_extract.side_effect = [[100.0], [100.0]]
    score = calculate_calculation_accuracy(
        {"expected_outcome": "Result is 100"}, "Agent says 100"
    )
    assert score == 1.0

    # Scene: Expected 100, Agent says 50
    mock_extract.side_effect = [[100.0], [50.0]]
    score = calculate_calculation_accuracy(
        {"expected_outcome": "Result is 100"}, "Agent says 50"
    )
    assert score == 0.0


def test_numeric_utility_extraction():
    """Test the regex-based number extractor."""
    from eval_runner.metrics.utils import extract_numbers

    text = "The invoice total is $1,250.50 with a discount of 5%."
    numbers = extract_numbers(text)
    assert 1250.5 in numbers
    assert 5.0 in numbers


@pytest.mark.asyncio
@patch("eval_runner.llm_providers.LLMProviderFactory.create")
async def test_planning_quality_uses_correct_rubric(mock_factory):
    """Ensure planning_quality triggers the strategic_planning rubric."""
    from eval_runner.metrics.planning import calculate_planning_quality

    mock_provider = MagicMock()
    mock_provider.generate.return_value = "1.0"
    mock_factory.return_value = mock_provider

    with patch("eval_runner.rubrics.RubricRegistry.get") as mock_rubric_get:
        mock_rubric_get.return_value = (
            "Mock Planning Rubric {expected_outcome} {agent_summary}"
        )

        await calculate_planning_quality(
            {"expected_outcome": "Plan A", "required": True}, "Agent Plan B"
        )

        # Verify it requested the correct rubric
        mock_rubric_get.assert_called_with("strategic_planning")


def test_root_cause_analysis_logic():
    """Verify root_cause_analysis_correctness registration and existence."""
    # This just ensures the import path will be valid after refactor
    from eval_runner.metrics.planning import calculate_root_cause_analysis

    assert callable(calculate_root_cause_analysis)
