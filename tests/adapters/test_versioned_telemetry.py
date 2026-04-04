import pytest
import asyncio
from unittest.mock import MagicMock, patch
from eval_runner.adapters.langgraph import LangGraphAdapterPlugin
from eval_runner.adapters.autogen import AutoGenAdapterPlugin
from eval_runner.adapters.crewai import CrewAIAdapterPlugin
from eval_runner.adapters.langchain import LangChainAdapterPlugin
from eval_runner.events import EventEmitter, CoreEvents

@pytest.fixture
def event_bus():
    events = []
    def subscriber(event):
        events.append(event)
    EventEmitter.subscribe(subscriber)
    yield events
    EventEmitter.reset()

@pytest.mark.asyncio
async def test_langgraph_v2_telemetry(event_bus):
    plugin = LangGraphAdapterPlugin()
    payload = {
        "node_id": "test_node",
        "input": {"data": "hello"},
        "config": {}
    }
    
    # Mock langchain_core to prevent ImportError
    with patch.dict("sys.modules", {"langchain_core": MagicMock(), "langchain_core.callbacks": MagicMock(), "langgraph": MagicMock()}):
        result = await plugin.execute_langgraph_node(payload)
        
    assert result["status"] == "success"
    assert result["metadata"]["protocol"] == "v2"
    
    # Verify events
    event_names = [e.name for e in event_bus]
    assert CoreEvents.CHAIN_START in event_names
    assert CoreEvents.NODE_START in event_names
    assert CoreEvents.CHAIN_END in event_names
    
    # Verify state hash existence
    start_event = next(e for e in event_bus if e.name == CoreEvents.CHAIN_START)
    assert "state_hash" in start_event.data
    assert start_event.data["inputs_summary"] == {"data": "str"}

@pytest.mark.asyncio
async def test_autogen_v1_telemetry(event_bus):
    plugin = AutoGenAdapterPlugin()
    payload = {"agent_id": "assistant_agent", "message": "query"}
    
    with patch.dict("sys.modules", {"autogen": MagicMock()}):
        result = await plugin.execute_autogen_query(payload)
        
    assert result["status"] == "success"
    assert result["metadata"]["protocol"] == "v1"
    
    event_names = [e.name for e in event_bus]
    assert CoreEvents.CHAIN_START in event_names
    assert CoreEvents.NODE_START in event_names

@pytest.mark.asyncio
async def test_crewai_v1_telemetry(event_bus):
    plugin = CrewAIAdapterPlugin()
    payload = {"task_id": "research_task"}
    
    with patch.dict("sys.modules", {"crewai": MagicMock()}):
        result = await plugin.execute_crewai_task(payload)
        
    assert result["status"] == "success"
    assert result["metadata"]["protocol"] == "v1"
    
    event_names = [e.name for e in event_bus]
    assert CoreEvents.CHAIN_START in event_names
    assert CoreEvents.CHAIN_END in event_names

@pytest.mark.asyncio
async def test_langchain_v1_telemetry(event_bus):
    plugin = LangChainAdapterPlugin()
    payload = {"task_id": "translator_chain", "input": {"text": "hello"}}
    
    with patch.dict("sys.modules", {"langchain": MagicMock(), "langchain_core": MagicMock()}):
        result = await plugin.execute_langchain_query(payload)
        
    assert result["status"] == "success"
    assert result["metadata"]["protocol"] == "v1"
    
    event_names = [e.name for e in event_bus]
    assert CoreEvents.CHAIN_START in event_names
    assert CoreEvents.NODE_START in event_names
    assert CoreEvents.CHAIN_END in event_names

@pytest.mark.asyncio
async def test_missing_sdk_err_reporting(event_bus):
    """Verifies all adapters report 'error' when SDK is missing (No-Masking policy)."""
    lg_plugin = LangGraphAdapterPlugin()
    ag_plugin = AutoGenAdapterPlugin()
    crew_plugin = CrewAIAdapterPlugin()
    lc_plugin = LangChainAdapterPlugin()

    # Force missing SDKs
    with patch.dict("sys.modules", {
        "langgraph": None,
        "autogen": None,
        "crewai": None,
        "langchain": None,
        "langchain_core": None
    }), patch("eval_runner.config.AUTOGEN_API_URL", None):
        # LangGraph
        lg_res = await lg_plugin.execute_langgraph_node({"node_id": "test"})
        assert lg_res["status"] == "error"
        assert "not installed" in lg_res["message"]

        # AutoGen (unconfigured fallback)
        ag_res = await ag_plugin.execute_autogen_query({"agent_id": "test"})
        assert ag_res["status"] == "error"
        assert "not installed" in ag_res["message"]

        # CrewAI
        crew_res = await crew_plugin.execute_crewai_task({"task_id": "test"})
        assert crew_res["status"] == "error"
        assert "not installed" in crew_res["message"]

        # LangChain
        lc_res = await lc_plugin.execute_langchain_query({"task_id": "test"})
        assert lc_res["status"] == "error"
        assert "not installed" in lc_res["message"]

    # Verify ERROR events were emitted
    event_names = [e.name for e in event_bus]
    assert CoreEvents.ERROR in event_names

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
