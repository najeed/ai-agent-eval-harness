import pytest
from eval_runner.engine import AgentAdapterRegistry
from eval_runner import plugins

def test_adapter_discovery():
    # Force reset discovery
    AgentAdapterRegistry._discovered = False
    AgentAdapterRegistry._adapters = {}
    
    AgentAdapterRegistry._discover()
    
    # Check default human adapter
    assert "human" in AgentAdapterRegistry._adapters
    
    # Check internal ecosystem adapters (should be loaded automatically from eval_runner/adapters/)
    # CrewAI and LangGraph were already there, others were added.
    assert "crewai" in AgentAdapterRegistry._adapters
    assert "openai" in AgentAdapterRegistry._adapters
    assert "ollama" in AgentAdapterRegistry._adapters
    assert "langchain" in AgentAdapterRegistry._adapters
    assert "gemini" in AgentAdapterRegistry._adapters
    assert "claude" in AgentAdapterRegistry._adapters

@pytest.mark.asyncio
async def test_openai_adapter_logic():
    # OpenAI adapter involves aiohttp, we just check if it's callable
    # and if it handles a mock payload reasonably (e.g. error without API key)
    AgentAdapterRegistry._discover()
    openai_func = AgentAdapterRegistry._adapters.get("openai")
    assert openai_func is not None
    
    # Simple call without key should result in error (or attempt to hit API)
    # We use a payload that will likely fail fast or trigger our error handling
    res = await openai_func({"task": "hello", "api_key": "invalid"})
    assert res["status"] == "error"
