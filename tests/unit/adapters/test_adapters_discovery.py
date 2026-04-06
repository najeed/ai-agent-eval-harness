import pytest

from eval_runner.engine import AgentAdapterRegistry


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
    from unittest.mock import AsyncMock, patch

    # Mock the aiohttp.ClientSession to avoid event loop issues
    mock_response = AsyncMock()
    mock_response.status = 401
    mock_response.text = AsyncMock(return_value="Unauthorized")

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=AsyncMock())
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.post = AsyncMock(return_value=mock_response)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        AgentAdapterRegistry._discover()
        openai_func = AgentAdapterRegistry._adapters.get("openai")
        assert openai_func is not None

        res = await openai_func({"task_description": "hello", "api_key": "invalid"})
        assert res["status"] == "error"
