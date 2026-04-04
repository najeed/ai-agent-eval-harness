import asyncio
import sys
from unittest.mock import MagicMock, patch
from eval_runner.adapters.langgraph import LangGraphAdapterPlugin
from eval_runner.adapters.autogen import AutoGenAdapterPlugin
from eval_runner.adapters.crewai import CrewAIAdapterPlugin
from eval_runner.adapters.langchain import LangChainAdapterPlugin
from eval_runner.events import EventEmitter, CoreEvents

async def run_diagnostics():
    events = []
    def subscriber(event):
        print(f"Captured Event: {event.name}")
        events.append(event)
    EventEmitter.subscribe(subscriber)

    # 1. LangGraph
    print("\n--- Testing LangGraph ---")
    lg = LangGraphAdapterPlugin()
    with patch.dict("sys.modules", {"langchain_core": MagicMock(), "langchain_core.callbacks": MagicMock(), "langgraph": MagicMock()}):
        res = await lg.execute_langgraph_node({"node_id": "lg_node", "input": {"x": 1}})
        print(f"Result: {res['status']}")

    # 2. AutoGen
    print("\n--- Testing AutoGen ---")
    ag = AutoGenAdapterPlugin()
    with patch.dict("sys.modules", {"autogen": MagicMock()}):
        res = await ag.execute_autogen_query({"agent_id": "ag_agent", "message": "hi"})
        print(f"Result: {res['status']}")

    # 3. CrewAI
    print("\n--- Testing CrewAI ---")
    cr = CrewAIAdapterPlugin()
    with patch.dict("sys.modules", {"crewai": MagicMock()}):
        res = await cr.execute_crewai_task({"task_id": "cr_task"})
        print(f"Result: {res['status']}")

    # 4. LangChain
    print("\n--- Testing LangChain ---")
    lc = LangChainAdapterPlugin()
    with patch.dict("sys.modules", {"langchain": MagicMock(), "langchain_core": MagicMock()}):
        res = await lc.execute_langchain_query({"task_id": "lc_task", "input": {"y": 2}})
        print(f"Result: {res['status']}")

    print("\nDiagnostic Summary:")
    print(f"Total Events Captured: {len(events)}")
    unique_events = set(e.name for e in events)
    print(f"Unique Events: {unique_events}")
    
    if CoreEvents.CHAIN_START in unique_events and CoreEvents.NODE_START in unique_events:
        print("SUCCESS: High-fidelity telemetry verified.")
    else:
        print("FAILURE: Missing expected telemetry signals.")

if __name__ == "__main__":
    asyncio.run(run_diagnostics())
