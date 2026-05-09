import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.adapters.langchain import LangChainAdapterPlugin


@pytest.mark.asyncio
async def test_langchain_adapter_simulation():
    """Verify that LangChain adapter falls back to simulation when no chain_path is provided."""
    adapter = LangChainAdapterPlugin()
    payload = {"task_id": "test_sim", "input": {"query": "hello"}}

    with patch("eval_runner.adapters.langchain.AESCallbackHandler") as mock_handler_cls:
        mock_handler = MagicMock()
        mock_handler_cls.return_value = mock_handler

        result = await adapter.execute_langchain_query(payload)

        assert result["status"] == "success"
        assert "Simulation" in result["output"]
        assert result["metadata"]["mode"] == "simulated"

        # Verify callback simulation
        mock_handler.on_chain_start.assert_called()
        mock_handler.on_chain_end.assert_called()


@pytest.mark.asyncio
async def test_langchain_adapter_local_execution():
    """Verify that LangChain adapter executes a real chain when chain_path is provided."""
    adapter = LangChainAdapterPlugin()

    # Mock a chain object
    mock_chain = AsyncMock()
    mock_chain.ainvoke.return_value = {"status": "success", "data": "real_output"}

    # Mock a module containing the chain
    mock_module = ModuleType("mock_chains")
    mock_module.test_chain = mock_chain
    sys.modules["mock_chains"] = mock_module

    payload = {
        "task_id": "test_real",
        "input": {"query": "execute"},
        "metadata": {"chain_path": "mock_chains:test_chain"},
    }

    try:
        result = await adapter.execute_langchain_query(payload)

        assert result["status"] == "success"
        assert result["output"] == {"status": "success", "data": "real_output"}
        assert result["action"] == "final_answer"  # via Heuristics

        # Verify ainvoke was called with correct config
        mock_chain.ainvoke.assert_called_once()
        args, kwargs = mock_chain.ainvoke.call_args
        assert "callbacks" in kwargs["config"]
    finally:
        del sys.modules["mock_chains"]


@pytest.mark.asyncio
async def test_langchain_adapter_remote_langserve():
    """Verify that LangChain adapter calls remote LangServe via SessionManager."""
    adapter = LangChainAdapterPlugin()
    payload = {"input": {"query": "remote"}, "url": "http://langserve"}

    mock_response_data = {"output": "remote_output"}

    with patch(
        "eval_runner.adapters.common.SessionManager.get_session", new_callable=AsyncMock
    ) as mock_get_session:
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_response_data)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session.post.return_value = mock_resp

        result = await adapter.execute_langchain_query(payload)

        assert result["status"] == "success"
        assert result["output"] == "remote_output"
        assert mock_session.post.call_count == 1
        assert "http://langserve/invoke" in mock_session.post.call_args[0][0]
