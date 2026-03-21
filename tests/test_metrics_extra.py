import pytest
from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
async def test_calculate_luna_judge_score_branches():
    from eval_runner.metrics.accuracy import calculate_luna_judge_score
    
    # 1. Empty expected outcome returns 1.0
    res = await calculate_luna_judge_score({"expected_outcome": ""}, "test")
    assert res == 1.0
    
    # 2. Exact match returns 1.0 (short circuit)
    res = await calculate_luna_judge_score({"expected_outcome": "exact"}, "exact")
    assert res == 1.0
    
    # 3. Provider fails but required=True -> RuntimeError
    with patch("eval_runner.llm_providers.LLMProviderFactory.create", side_effect=Exception("API limit")):
        with pytest.raises(RuntimeError, match="Judge Configuration Error"):
            await calculate_luna_judge_score({"expected_outcome": "a", "required": True}, "b")
            
    # 4. Provider fails but required=False -> Jaccard fallback
    with patch("eval_runner.llm_providers.LLMProviderFactory.create", side_effect=Exception("API limit")):
        res = await calculate_luna_judge_score({"expected_outcome": "hello", "required": False}, "hello world")
        assert res > 0.0 # Jaccard similarity fallback

    # 5. Model override and float parsing branch
    mock_provider = MagicMock()
    mock_provider.model = "old-model"
    async def mock_generate(*args, **kwargs): return "0.95 text"
    mock_provider.generate = mock_generate
    
    with patch("eval_runner.llm_providers.LLMProviderFactory.create", return_value=mock_provider):
        res = await calculate_luna_judge_score({"expected_outcome": "a", "judge_config": {"judge_model": "new-model"}}, "b")
        assert res == 0.95
        assert mock_provider.model == "new-model"
        
    # 6. Parse failure (ValueError branch)
    async def mock_fail_generate(*args, **kwargs): return "nan string"
    mock_provider.generate = mock_fail_generate
    with patch("eval_runner.llm_providers.LLMProviderFactory.create", return_value=mock_provider):
        res = await calculate_luna_judge_score({"expected_outcome": "a"}, "b")
        # Falls back to Jaccard when ValueError occurs inside score extraction
        assert res >= 0.0

@pytest.mark.asyncio
async def test_defense_metric_branch():
    from eval_runner.metrics.defense import calculate_defense_high_fidelity_metric
    
    with patch("eval_runner.metrics.calculate_luna_judge_score", return_value=0.88) as mock_luna:
        res = await calculate_defense_high_fidelity_metric({"metric": "roe_compliance_score"}, "agent said something")
        assert res == 0.88
        args, kwargs = mock_luna.call_args
        assert args[0]["judge_config"]["judge_rubric"] == "policy_adherence"

@pytest.mark.asyncio
async def test_technical_metric_branch():
    from eval_runner.metrics.technical import calculate_technical_correctness
    
    with patch("eval_runner.metrics.calculate_luna_judge_score", return_value=0.92) as mock_luna:
        res = await calculate_technical_correctness({}, "agent code")
        assert res == 0.92
        args, kwargs = mock_luna.call_args
        assert args[0]["judge_config"]["judge_rubric"] == "technical_correctness"

def test_calculation_accuracy_branches():
    from eval_runner.metrics.accuracy import calculate_calculation_accuracy
    
    # Early exits
    assert calculate_calculation_accuracy({"expected_outcome": ""}, "") == 0.0
    
    # Valid numeric arrays but no numbers found in expected
    assert calculate_calculation_accuracy({"expected_outcome": "text only"}, "agent response") == 1.0
    
    # 1 match out of 2 expected
    res = calculate_calculation_accuracy({"expected_outcome": "5 and 10"}, "found 5 but missed 10")
    assert res == 0.5
    
def test_verification_accuracy_branches():
    from eval_runner.metrics.accuracy import calculate_verification_accuracy
    
    # Hits keyword
    res = calculate_verification_accuracy({"expected_outcome": "validate"}, "I have verified the output")
    # Keyword hit means score starts at 0.5 + 0.5 * (jaccard sim). 
    assert res >= 0.5
