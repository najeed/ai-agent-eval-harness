import pytest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from eval_runner import engine, metrics

@pytest.mark.asyncio
async def test_pass_at_k_protocol():
    """Verify that engine runs k attempts and calculates pass@k."""
    scenario = {
        "scenario_id": "test-k",
        "tasks": [{
            "task_id": "task-1",
            "description": "Do something",
            "success_criteria": [{"metric": "generic_accuracy", "threshold": 0.5}]
        }]
    }
    
    # Mock agent to succeed in 1 out of 2 attempts
    attempt_count = 0
    async def mock_agent_call(payload): # Remove cls here
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            return {"action": "final_answer", "summary": "Success"}
        else:
            return {"action": "final_answer", "summary": ""} # Fails generic_accuracy (length > 0)
            
    with patch("eval_runner.engine.AgentAdapterRegistry.call_agent", new_callable=AsyncMock) as mock_agent:
        mock_agent.side_effect = mock_agent_call
        results = await engine.run_evaluation(scenario, attempts=2)
        
        assert len(results) == 2
        # pass@2 should be 0.5 (1 success, 1 failure)
        # Note: in engine.py emitter, we emit pass_at_k. 
        # Here we check the returned object structure.
        
        successes = 0
        for attempt in results:
            if all(all(m["success"] for m in tr["metrics"] if m["metric"] != "consistency_score") for tr in attempt):
                successes += 1
        
        assert successes == 1

@pytest.mark.asyncio
async def test_consistency_score_integration():
    """Verify that consistency score is calculated across attempts."""
    scenario = {
        "scenario_id": "test-consistency",
        "tasks": [{
            "task_id": "task-1",
            "description": "Do something",
            "success_criteria": []
        }]
    }
    
    # Mock agent to give same answer twice
    async def mock_agent_call(payload):
        return {"action": "final_answer", "summary": "Identical result"}
            
    with patch("eval_runner.engine.AgentAdapterRegistry.call_agent", side_effect=mock_agent_call):
        results = await engine.run_evaluation(scenario, attempts=2)
        
        # Check task metrics in the last attempt
        task_res = results[-1][0]
        consistency_metric = next((m for m in task_res["metrics"] if m["metric"] == "consistency_score"), None)
        
        assert consistency_metric is not None
        assert consistency_metric["score"] == 1.0

@pytest.mark.asyncio
async def test_luna_judge_ollama_mock():
    """Verify Luna-Judge calls Ollama and falls back on error."""
    criterion = {"expected_outcome": "The user is happy"}
    agent_summary = "User expressed happiness"
    
    # Mock successful Ollama response
    mock_ollama_resp = AsyncMock()
    mock_ollama_resp.status = 200
    mock_ollama_resp.json.return_value = {"response": "0.9"}
    
    # Patch ClientSession
    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value.__aenter__.return_value = mock_session
        
        # session.post returns an object that supports 'async with'
        # Crucial: post itself should NOT be an AsyncMock, it should return the CM
        mock_resp_cm = MagicMock()
        mock_resp_cm.__aenter__ = AsyncMock(return_value=mock_ollama_resp)
        mock_resp_cm.__aexit__ = AsyncMock()
        mock_session.post.return_value = mock_resp_cm
        
        score = await metrics.calculate_luna_judge_score(criterion, agent_summary)
        assert score == 0.9

@pytest.mark.asyncio
async def test_luna_judge_fallback():
    """Verify Luna-Judge fallback to Jaccard when Ollama fails."""
    criterion = {"expected_outcome": "apple banana"}
    agent_summary = "apple orange"
    
    # Mock failed Ollama response by patching ClientSession to raise
    with patch("aiohttp.ClientSession", side_effect=Exception("Connection Refused")):
        score = await metrics.calculate_luna_judge_score(criterion, agent_summary)
        # Jaccard: intersection={apple}, union={apple, banana, orange} -> 1/3 = 0.33
        assert 0.33 < score < 0.34
