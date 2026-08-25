---
title: LangGraph Integration Guide
description: Connect and evaluate stateful LangGraph agent workflows with AgentV.
---

AgentV provides native integration with **LangGraph**, enabling comprehensive evaluation of cyclic graphs, multi-agent state machines, and human-in-the-loop decision networks.

---

## 🏗️ 1. Building the LangGraph Service Adapter

Wrap your LangGraph application in a lightweight FastAPI service conforming to the [Agent Interaction Contract](/integrator/agent-contract/):

```python
from typing import Annotated, TypedDict
from fastapi import FastAPI, Request
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

app = FastAPI(title="LangGraph Agent Service")


# Define Graph State
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    task_description: str
    run_id: str


# Node 1: Planner / Tool Selector
def reasoner_node(state: AgentState) -> dict:
    last_msg = state["messages"][-1]
    # Inspect conversation history and determine next action
    if "credit score" in state["task_description"].lower() and len(state["messages"]) == 1:
        # Request tool execution from AgentV harness
        return {
            "messages": [
                AIMessage(
                    content="",
                    additional_kwargs={
                        "action": "call_tool",
                        "tool_name": "fetch_applicant_kyc",
                        "tool_args": {"applicant_id": "APP-89421"},
                    },
                )
            ]
        }

    # Final decision node reached
    return {
        "messages": [
            AIMessage(
                content="Assessment complete: Risk score 740, Approved.",
                additional_kwargs={
                    "action": "final_answer",
                    "metadata": {"status": "APPROVED", "risk_score": 740},
                },
            )
        ]
    }


# Build Graph
builder = StateGraph(AgentState)
builder.add_node("reasoner", reasoner_node)
builder.add_edge(START, "reasoner")
builder.add_edge("reasoner", END)
graph = builder.compile()


@app.post("/execute_task")
async def execute_task(request: Request):
    payload = await request.json()
    task_desc = payload["task_description"]
    history = payload.get("conversation_history", [])

    # Map harness history into LangChain messages
    messages = []
    for item in history:
        if item["role"] == "user":
            messages.append(HumanMessage(content=item["content"]))
        elif item["role"] == "assistant":
            messages.append(AIMessage(content=item.get("summary", "")))
        elif item["role"] == "tool":
            messages.append(ToolMessage(content=item["content"], tool_call_id="1"))

    # If first turn, seed with initial prompt
    if not messages:
        messages.append(HumanMessage(content=task_desc))

    # Invoke LangGraph
    state_input: AgentState = {
        "messages": messages,
        "task_description": task_desc,
        "run_id": payload.get("run_id", "default"),
    }
    result = await graph.ainvoke(state_input)
    last_action_msg = result["messages"][-1]
    kwargs = getattr(last_action_msg, "additional_kwargs", {})

    if "action" in kwargs:
        if kwargs["action"] == "call_tool":
            return {
                "action": "call_tool",
                "tool_name": kwargs["tool_name"],
                "tool_args": kwargs.get("tool_args", {}),
                "summary": "Invoking tool via LangGraph reasoner node.",
            }
        elif kwargs["action"] == "final_answer":
            return {
                "action": "final_answer",
                "summary": last_action_msg.content,
                "metadata": kwargs.get("metadata", {}),
            }

    return {"action": "final_answer", "summary": last_action_msg.content}
```

---

## 🚀 2. Running Evaluations

Start your LangGraph service:
```bash
uvicorn agent_service:app --host 127.0.0.1 --port 8000
```

Execute evaluation via the `agentv` CLI:
```bash
agentv evaluate \
  --path industries/finance/scenarios/loan_approval_risk_check.json \
  --protocol langgraph \
  --agent http://127.0.0.1:8000/execute_task \
  --agent-name "LangGraph-Fintech-Agent" \
  --attempts 3
```

---

## 🔍 3. Live Debugger & State Trace Playback

When evaluating LangGraph agents, AgentV records the execution graph and step-by-step state deltas. Launch the Visual Console to inspect the full reasoning trajectory:

```bash
agentv console
```

Navigate to `http://localhost:5000/debugger` to view:
- Graph node execution order and cycle counts.
- Virtual filesystem (VFS) environment diffs.
- OpenTelemetry span timeline with millisecond-level step latencies.
