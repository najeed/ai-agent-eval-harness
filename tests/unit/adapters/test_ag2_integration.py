import sys
from types import ModuleType
from unittest.mock import AsyncMock

import pytest

from eval_runner.adapters.ag2 import AG2AdapterPlugin


@pytest.mark.asyncio
async def test_ag2_adapter_real_integration():
    """Verify that the adapter works with a logic_path module when ag2 is present."""
    pytest.importorskip("ag2")

    # Register a mock module with a chat handler
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
        result = await adapter.execute_ag2_query(payload)
        assert result["status"] == "success"
        assert "real ag2 success" in result["output"]
    finally:
        del sys.modules["real_ag2"]
