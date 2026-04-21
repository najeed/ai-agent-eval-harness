import pytest

from eval_runner.engine import AgentAdapterRegistry


def test_adapter_discovery():
    # Force reset discovery
    AgentAdapterRegistry._discovered = False
    AgentAdapterRegistry._adapters = {}

    # Use a permissive mock to allow core protocol registration for verification
    from unittest.mock import patch

    with patch(
        "eval_runner.config.RegistryManager.get_resolved_registry",
        return_value={"adapters": {"active_protocols": ["http", "local", "socket"]}},
    ):
        AgentAdapterRegistry._discover()
        assert "http" in AgentAdapterRegistry._adapters
        assert "local" in AgentAdapterRegistry._adapters
        assert "socket" in AgentAdapterRegistry._adapters


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
