from unittest.mock import MagicMock, patch

import pytest

from eval_runner.adapters.autogen import AutoGenAdapterPlugin
from eval_runner.adapters.crewai import CrewAIAdapterPlugin
from eval_runner.adapters.langchain import LangChainAdapterPlugin
from eval_runner.adapters.langgraph import LangGraphAdapterPlugin


class MockResponse:
    def __init__(self, status=200, json_data=None):
        self.status = status
        self._json_data = json_data or {}

    async def json(self):
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
async def test_langchain_adapter_remote_success():
    plugin = LangChainAdapterPlugin()
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value = MockResponse(json_data={"output": "langchain_ok"})
        res = await plugin.execute_langchain_query({"input": "hi", "url": "http://langserve"})
        assert res["status"] == "success"
        assert res["action"] == "final_answer"
        assert res["output"] == "langchain_ok"


@pytest.mark.asyncio
async def test_autogen_adapter_remote_success():
    plugin = AutoGenAdapterPlugin()
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_post.return_value = MockResponse(json_data={"output": "autogen_ok"})
        res = await plugin.execute_autogen_query({"message": "hi", "url": "http://autogen"})
        assert res["status"] == "success"
        assert res["action"] == "final_answer"
        assert res["output"] == "autogen_ok"


@pytest.mark.asyncio
async def test_crewai_adapter_simulation():
    plugin = CrewAIAdapterPlugin()
    with patch.dict("sys.modules", {"crewai": MagicMock(__version__="1.0")}):
        res = await plugin.execute_crewai_task({"task_id": "test_crew"})
        assert res["status"] == "success"
        assert res["action"] == "final_answer"
        assert "CrewAI" in res["output"]


@pytest.mark.asyncio
async def test_langgraph_adapter_simulation():
    plugin = LangGraphAdapterPlugin()
    with patch.dict("sys.modules", {"langgraph": MagicMock(__version__="2.0")}):
        res = await plugin.execute_langgraph_node({"node_id": "test_node"})
        assert res["status"] == "success"
        assert res["action"] == "final_answer"
        assert "LangGraph" in res["output"]


@pytest.mark.asyncio
async def test_framework_adapters_error_reporting():
    # LangChain missing URL
    plugin = LangChainAdapterPlugin()
    res = await plugin.execute_langchain_query({})
    assert res["status"] == "error"
    assert res["action"] == "error"

    # AutoGen missing URL
    plugin = AutoGenAdapterPlugin()
    res = await plugin.execute_autogen_query({})
    assert res["status"] == "error"
    assert res["action"] == "error"
