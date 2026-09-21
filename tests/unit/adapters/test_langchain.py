from types import ModuleType
from unittest.mock import AsyncMock, patch

import pytest

from eval_runner.adapters.langchain import LangChainAdapterPlugin


@pytest.mark.asyncio
async def test_langchain_adapter_requires_execution_target():
    """LangChain fails closed when no runnable or LangServe endpoint is configured."""
    adapter = LangChainAdapterPlugin()
    payload = {"task_id": "test_sim", "input": {"query": "hello"}}

    result = await adapter.execute_langchain_query(payload)

    assert result["status"] == "error"
    assert "No LangChain execution target" in result["message"]


@pytest.mark.asyncio
async def test_langchain_adapter_local_execution():
    """Verify that LangChain adapter executes a real chain when chain_path is provided."""
    adapter = LangChainAdapterPlugin()

    # Mock a chain object
    class Runnable:
        ainvoke = AsyncMock(return_value={"status": "success", "data": "real_output"})

    mock_chain = Runnable()

    # Mock a module containing the chain using patch.dict for isolation
    mock_module = ModuleType("mock_chains")
    mock_module.test_chain = mock_chain

    payload = {
        "task_id": "test_real",
        "input": {"query": "execute"},
        "metadata": {"chain_path": "mock_chains:test_chain"},
    }

    with patch.dict("sys.modules", {"mock_chains": mock_module}):
        result = await adapter.execute_langchain_query(payload)

        assert result["status"] == "success"
        assert result["output"] == {"status": "success", "data": "real_output"}
        assert result["action"] == "final_answer"  # via Heuristics

        # Verify ainvoke was called with correct config
        mock_chain.ainvoke.assert_called_once()
        args, kwargs = mock_chain.ainvoke.call_args
        assert "callbacks" in kwargs["config"]


@pytest.mark.asyncio
async def test_langchain_adapter_remote_langserve():
    """Verify that LangChain adapter calls remote LangServe via SessionManager."""
    adapter = LangChainAdapterPlugin()
    payload = {"input": {"query": "remote"}, "url": "http://langserve"}

    mock_response_data = {"output": "remote_output"}

    with patch.object(adapter, "_remote_invoke", new_callable=AsyncMock) as remote_invoke:
        remote_invoke.return_value = mock_response_data

        result = await adapter.execute_langchain_query(payload)

        assert result["status"] == "success"
        assert result["output"] == "remote_output"
        assert "http://langserve/invoke" in remote_invoke.call_args.kwargs["endpoint"]
