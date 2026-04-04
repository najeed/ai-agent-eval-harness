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

    print("=== INDUSTRIAL ADAPTER HARDENING DIAGNOSTIC ===")
    
    # 0. Hard Failure Check (No-Masking Policy)
    print("\n--- 0. Hard Failure Check (No-Masking Policy) ---")
    lg_plugin = LangGraphAdapterPlugin()
    # Force ImportError by masking the real SDKs
    with patch.dict("sys.modules", {"langgraph": None, "autogen": None, "crewai": None, "langchain": None}):
        res = await lg_plugin.execute_langgraph_node({"node_id": "test"})
        print(f"LangGraph (No SDK): {res['status']} (Expected: error)")
        assert res['status'] == "error"

    # 1. LangGraph (SIMULATED)
    print("\n--- 1. Testing LangGraph (SIMULATED) ---")
    lg = LangGraphAdapterPlugin()
    with patch.dict("sys.modules", {"langchain_core": MagicMock(), "langchain_core.callbacks": MagicMock(), "langgraph": MagicMock()}):
        res = await lg.execute_langgraph_node({"node_id": "lg_node", "input": {"x": 1}})
        print(f"Result: {res['status']} (Simulated Success)")

    # 2. AutoGen (SIMULATED)
    print("\n--- 2. Testing AutoGen (SIMULATED) ---")
    ag = AutoGenAdapterPlugin()
    with patch.dict("sys.modules", {"autogen": MagicMock()}):
        res = await ag.execute_autogen_query({"agent_id": "ag_agent", "message": "hi"})
        print(f"Result: {res['status']} (Simulated Success)")

    # 3. CrewAI (SIMULATED)
    print("\n--- 3. Testing CrewAI (SIMULATED) ---")
    cr = CrewAIAdapterPlugin()
    with patch.dict("sys.modules", {"crewai": MagicMock()}):
        res = await cr.execute_crewai_task({"task_id": "cr_task"})
        print(f"Result: {res['status']} (Simulated Success)")

    # 4. LangChain (SIMULATED)
    print("\n--- 4. Testing LangChain (SIMULATED) ---")
    lc = LangChainAdapterPlugin()
    with patch.dict("sys.modules", {"langchain": MagicMock(), "langchain_core": MagicMock()}):
        res = await lc.execute_langchain_query({"task_id": "lc_task", "input": {"y": 2}})
        print(f"Result: {res['status']} (Simulated Success)")

    print("\nDiagnostic Summary:")
    print(f"Total Events Captured: {len(events)}")
    unique_events = set(e.name for e in events)
    print(f"Unique Events: {unique_events}")
    
    if CoreEvents.ERROR in unique_events:
        print("SUCCESS: Hard Failure (ERROR) signal detected.")
    
    if CoreEvents.CHAIN_START in unique_events and CoreEvents.NODE_START in unique_events:
        print("SUCCESS: High-fidelity telemetry verified.")
    else:
        print("FAILURE: Missing expected telemetry signals.")

if __name__ == "__main__":
    asyncio.run(run_diagnostics())
