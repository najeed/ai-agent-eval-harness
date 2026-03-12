
import asyncio
import json
from unittest.mock import MagicMock, patch, AsyncMock
from eval_runner import engine, metrics

async def test_debug():
    scenario = {
        "scenario_id": "test-k",
        "tasks": [{
            "task_id": "task-1",
            "description": "Do something",
            "success_criteria": [{"metric": "generic_accuracy", "threshold": 0.5}]
        }]
    }
    
    attempt_count = 0
    async def mock_agent_call(payload, protocol="http", endpoint=None):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            return {"action": "final_answer", "summary": "Success"}
        else:
            return {"action": "final_answer", "summary": ""}
            
    with patch("eval_runner.engine.AgentAdapterRegistry.call_agent", side_effect=mock_agent_call):
        results = await engine.run_evaluation(scenario, attempts=2)
        
        print(f"Results length: {len(results)}")
        for i, attempt in enumerate(results):
            print(f"Attempt {i} results:")
            for tr in attempt:
                print(f"  Task {tr['task_id']} metrics: {tr['metrics']}")

if __name__ == "__main__":
    asyncio.run(test_debug())
