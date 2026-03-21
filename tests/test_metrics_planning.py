import pytest
from unittest.mock import patch, AsyncMock
from eval_runner.metrics import planning

@pytest.mark.asyncio
async def test_calculate_planning_quality():
    """Test planning_quality metric calculation."""
    criterion = {"id": "c1", "judge_config": {"temp": 0.5}}
    agent_summary = "Agent did a good job planning."
    
    with patch("eval_runner.metrics.calculate_luna_judge_score", new_callable=AsyncMock) as mock_judge:
        mock_judge.return_value = 0.85
        score = await planning.calculate_planning_quality(criterion, agent_summary)
        
        assert score == 0.85
        # Verify rubric was injected
        call_args = mock_judge.call_args[0]
        assert call_args[0]["judge_config"]["judge_rubric"] == "strategic_planning"

@pytest.mark.asyncio
async def test_calculate_root_cause_analysis():
    """Test root_cause_analysis_correctness metric calculation."""
    criterion = {}
    agent_summary = "Found the bug."
    
    with patch("eval_runner.metrics.calculate_luna_judge_score", new_callable=AsyncMock) as mock_judge:
        mock_judge.return_value = 0.9
        score = await planning.calculate_root_cause_analysis(criterion, agent_summary)
        
        assert score == 0.9
        # Verify rubric was injected
        call_args = mock_judge.call_args[0]
        assert call_args[0]["judge_config"]["judge_rubric"] == "causal_inference"
