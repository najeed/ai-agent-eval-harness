from unittest.mock import AsyncMock, patch

import pytest

from eval_runner.metrics.accuracy import calculate_luna_judge_score
from eval_runner.metrics.core import calculate_generic_accuracy


@pytest.mark.asyncio
async def test_generic_accuracy_no_expected():
    # Should fallback to presence check
    score = await calculate_generic_accuracy({}, "Some summary")
    assert score == 1.0

    score = await calculate_generic_accuracy({}, "")
    assert score == 0.0


@pytest.mark.asyncio
async def test_generic_accuracy_with_expected():
    criterion = {"expected_outcome": "Success"}
    summary = "Task was a success"

    with patch(
        "eval_runner.metrics.accuracy.calculate_luna_judge_score", new_callable=AsyncMock
    ) as mock_judge:
        mock_judge.return_value = 0.95
        score = await calculate_generic_accuracy(criterion, summary)

        assert score == 0.95
        mock_judge.assert_called_once()


@pytest.mark.asyncio
async def test_luna_judge_score_extraction():
    # Test different LLM response formats
    with patch("eval_runner.llm_providers.LLMProviderFactory.create") as mock_factory:
        mock_provider = AsyncMock()
        mock_factory.return_value = mock_provider

        criterion = {"expected_outcome": "Test"}

        # Format 1: Just the number
        mock_provider.generate.return_value = "0.8"
        score = await calculate_luna_judge_score(criterion, "Different summary")
        assert score == 0.8

        # Format 2: Reasoning then score
        mock_provider.generate.return_value = "The agent did well. Score: 0.9"
        score = await calculate_luna_judge_score(criterion, "Different summary")
        assert score == 0.9

        # Format 3: Multiple numbers, take the one that looks like a score
        mock_provider.generate.return_value = "Version 1.0 was used. Result: 0.75"
        score = await calculate_luna_judge_score(criterion, "Different summary")
        assert score == 0.75

        # Format 4: Rating keyword
        mock_provider.generate.return_value = "Rating: 1.0"
        score = await calculate_luna_judge_score(criterion, "Different summary")
        assert score == 1.0
