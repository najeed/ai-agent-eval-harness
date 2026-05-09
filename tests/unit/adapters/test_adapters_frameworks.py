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

    def raise_for_status(self):
        if self.status >= 400:
            from unittest.mock import MagicMock

            import aiohttp

            raise aiohttp.ClientResponseError(
                request_info=MagicMock(), history=(), status=self.status, message="Error"
            )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
async def test_langchain_adapter_remote_success():
    plugin = LangChainAdapterPlugin()
    with patch("eval_runner.adapters.common.SessionManager.get_session") as mock_get_session:
        session_instance = MagicMock()
        mock_get_session.return_value = session_instance
        session_instance.post.return_value = MockResponse(json_data={"output": "langchain_ok"})
        res = await plugin.execute_langchain_query({"input": "hi", "url": "http://langserve"})
        assert res["status"] == "success"
        assert res["action"] == "final_answer"
        assert res["output"] == "langchain_ok"


@pytest.mark.asyncio
async def test_autogen_adapter_remote_success():
    plugin = AutoGenAdapterPlugin()
    with patch("eval_runner.adapters.common.SessionManager.get_session") as mock_get_session:
        session_instance = MagicMock()
        mock_get_session.return_value = session_instance
        session_instance.post.return_value = MockResponse(json_data={"output": "autogen_ok"})
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
    # LangChain missing URL -> Simulation Fallback
    plugin = LangChainAdapterPlugin()
    res = await plugin.execute_langchain_query({})
    assert res["status"] == "success"
    assert res["action"] == "final_answer"

    # AutoGen missing URL -> should reach error (no SDK, no config URL)
    plugin = AutoGenAdapterPlugin()
    with patch("eval_runner.adapters.autogen.config") as mock_cfg:
        mock_cfg.AUTOGEN_API_URL = None
        res = await plugin.execute_autogen_query({})
    assert res["status"] == "error"
    assert res["action"] == "error"
