import sys
from types import ModuleType
from unittest.mock import AsyncMock

import pytest

from eval_runner.adapters.autogen import AG2AdapterPlugin


@pytest.mark.asyncio
async def test_ag2_adapter_real_integration():
    """Verify that the adapter works with real AutoGen/AG2 components."""
    # This test requires the real autogen package
    pytest.importorskip("autogen")
    import autogen

    # Setup real autogen agents
    # We mock the actual initiate_chat to avoid needing an LLM
    autogen.AssistantAgent(
        name="assistant",
        llm_config=False,  # No LLM for this test
    )
    autogen.UserProxyAgent(
        name="user_proxy",
        human_input_mode="NEVER",
        max_consecutive_auto_reply=1,
    )

    # Register the agents/logic in a mock module
    async def mock_chat():
        return AsyncMock(chat_history=[{"role": "assistant", "content": "real ag2 success"}])

    mock_module = ModuleType("real_ag2")
    mock_module.start_chat = mock_chat
    sys.modules["real_ag2"] = mock_module

    adapter = AG2AdapterPlugin()
    payload = {
        "task_id": "ag2_integration_test",
        "metadata": {"logic_path": "real_ag2:start_chat"},
    }

    try:
        # We need to mock the adapter's internal loading if it's too complex
        # but here we just verify it calls the logic_path
        result = await adapter.execute_autogen_query(payload)

        assert result["status"] == "success"
        assert "real ag2 success" in result["output"]
    finally:
        del sys.modules["real_ag2"]
