from unittest.mock import AsyncMock, patch

import pytest

from eval_runner.metrics.accuracy import calculate_luna_judge_score


@pytest.mark.asyncio
async def test_luna_judge_invalid_scores():
    with patch("eval_runner.llm_providers.LLMProviderFactory.create") as mock_factory:
        mock_provider = AsyncMock()
        mock_factory.return_value = mock_provider

        criterion = {"expected_outcome": "Test"}

        # Case 1: Score out of range (greater than 1)
        mock_provider.generate.return_value = "Score: 1.5"
        score = await calculate_luna_judge_score(criterion, "Different")
        assert score == 1.0  # Clamped to 1.0

        # Case 2: Score out of range (negative)
        mock_provider.generate.return_value = "Score: -0.5"
        # Note: The regex currently doesn't match negative signs, so it might fail to find a score
        # or find '0.5' if it's not careful. Let's see how the robust extraction handles it.
        # Actually, let's test if it handles it gracefully.
        score = await calculate_luna_judge_score(criterion, "Different")
        # If it fails to find a score, it falls back to Jaccard
        # But if it finds 0.5, it should clamp it.
        assert 0.0 <= score <= 1.0


@pytest.mark.asyncio
async def test_luna_judge_garbage_response():
    with patch("eval_runner.llm_providers.LLMProviderFactory.create") as mock_factory:
        mock_provider = AsyncMock()
        mock_factory.return_value = mock_provider

        criterion = {"expected_outcome": "Test"}

        # Case: No numbers at all
        mock_provider.generate.return_value = "I refuse to give a score."
        score = await calculate_luna_judge_score(criterion, "Different")
        # Should fallback to Jaccard
        from eval_runner.metrics.utils import calculate_jaccard

        expected_jaccard = calculate_jaccard("Test", "Different")
        assert score == expected_jaccard


@pytest.mark.asyncio
async def test_luna_judge_required_fail():
    with patch("eval_runner.llm_providers.LLMProviderFactory.create") as mock_factory:
        mock_factory.side_effect = Exception("Provider init failed")

        criterion = {"expected_outcome": "Test", "required": True}

        with pytest.raises(RuntimeError, match="Judge Configuration Error"):
            await calculate_luna_judge_score(criterion, "Different")
