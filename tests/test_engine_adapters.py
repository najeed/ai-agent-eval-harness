import pytest
import os
from unittest.mock import patch, AsyncMock
from eval_runner.engine import AgentAdapterRegistry


@pytest.mark.asyncio
async def test_registry_discovery():
    AgentAdapterRegistry._discovered = False
    AgentAdapterRegistry._discover()
    assert "http" in AgentAdapterRegistry._adapters
    assert "local" in AgentAdapterRegistry._adapters
    assert "socket" in AgentAdapterRegistry._adapters


@pytest.mark.asyncio
async def test_call_agent_protocol_selection():
    payload = {"test": "data"}
    AgentAdapterRegistry._discovered = False
    AgentAdapterRegistry._discover()

    # Target the dictionary values directly to be sure
    with patch.dict(
        AgentAdapterRegistry._adapters,
        {"local": AsyncMock(return_value={"action": "final_answer", "content": "ok"})},
    ):
        result = await AgentAdapterRegistry.call_agent(
            payload, protocol="local", endpoint="echo 'test'"
        )
        assert result["content"] == "ok"


@pytest.mark.asyncio
async def test_call_agent_env_fallback():
    payload = {"test": "data"}
    AgentAdapterRegistry._discovered = False
    AgentAdapterRegistry._discover()

    with patch.dict(os.environ, {"AGENT_LOCAL_CMD": "python mock_agent.py"}):
        with patch.dict(
            AgentAdapterRegistry._adapters,
            {
                "local": AsyncMock(
                    return_value={"action": "final_answer", "content": "env_ok"}
                )
            },
        ):
            result = await AgentAdapterRegistry.call_agent(payload, protocol="local")
            assert result["content"] == "env_ok"
