import sys
from types import ModuleType

import pytest

from eval_runner.adapters.langgraph import LangGraphAdapterPlugin
from eval_runner.events import subscribe, unsubscribe


@pytest.mark.asyncio
async def test_langgraph_adapter_real_integration():
    """Verify that the adapter works with real LangGraph components."""
    # This test requires the real langgraph package
    pytest.importorskip("langgraph")
    from langgraph.graph import END, StateGraph

    # Define a simple graph
    def my_node(state):
        return {"output": "real graph success"}

    workflow = StateGraph(dict)
    workflow.add_node("node1", my_node)
    workflow.set_entry_point("node1")
    workflow.add_edge("node1", END)
    app = workflow.compile()

    # Register the graph in sys.modules
    mock_module = ModuleType("real_graphs")
    mock_module.my_app = app
    sys.modules["real_graphs"] = mock_module

    adapter = LangGraphAdapterPlugin()
    payload = {
        "node_id": "langgraph_test",
        "input": {"data": "input"},
        "metadata": {"graph_path": "real_graphs:my_app"},
    }

    events_captured = []

    def listener(event):
        events_captured.append(event.name)

    subscribe(listener)
    try:
        result = await adapter.execute_langgraph_node(payload)

        assert result["status"] == "success"
        assert result["output"] == {"output": "real graph success"}
        # Verify telemetry via event bus subscription
        assert "chain_start" in events_captured
    finally:
        unsubscribe(listener)
        del sys.modules["real_graphs"]
