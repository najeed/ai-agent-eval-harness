import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from eval_runner.playground import run_playground

@pytest.mark.asyncio
async def test_run_playground_smoke(capsys, monkeypatch):
    """Verifies that the playground loop handles inputs and responses."""
    # Mock inputs: 'hello' then 'exit'
    inputs = iter(["hello", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.get_json.return_value = {"summary": "I am a test agent", "action": "none"}
        mock_post.return_value.__aenter__.return_value = mock_response
        
        await run_playground("http://test-agent")
        
        captured = capsys.readouterr()
        assert "Playground" in captured.out
        assert "AGENT: I am a test agent" in captured.out
