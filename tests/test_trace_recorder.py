import pytest
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
from eval_runner.trace_recorder import record_interaction

@pytest.mark.asyncio
async def test_record_interaction_logic(tmp_path, monkeypatch):
    """Verifies that the trace recorder captures interactions and saves them to a file."""
    # Mock inputs: 'task 1' then 'exit'
    inputs = iter(["task 1", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    
    monkeypatch.chdir(tmp_path)
    
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.get_json.return_value = {"summary": "Captured response"}
        mock_post.return_value.__aenter__.return_value = mock_response
        
        await record_interaction("http://test-agent")
        
        # Verify that a run file was created in tmp_path/runs/
        run_files = list((tmp_path / "runs").glob("*.jsonl"))
        assert len(run_files) == 1
        
        # Verify content
        with open(run_files[0], "r") as f:
            lines = f.readlines()
            events = [json.loads(l) for l in lines]
            
            assert events[0]["event"] == "run_start"
            assert events[1]["event"] == "agent_request"
            assert events[1]["task"] == "task 1"
            assert events[2]["event"] == "agent_response"
            assert events[2]["content"]["summary"] == "Captured response"
