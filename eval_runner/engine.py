"""
engine.py

Core evaluation engine.
Updated for universal extensibility via registries, hooks, and typed contexts.
"""

import os
import json
import aiohttp
import asyncio
from typing import Dict, Any, List, Optional, Callable
from . import plugins
from . import metrics
from .context import EvaluationContext, TurnContext
from .tool_sandbox import ToolSandbox

# Read the agent URL from an environment variable, with a default for local testing
AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:5001/execute_task")

# Maximum number of conversation turns per task before forcing completion
MAX_TURNS = int(os.getenv("EVAL_MAX_TURNS", "5"))

# Dynamic Adapter Registry for Agent Communication
class AgentAdapterRegistry:
    _adapters: Dict[str, Callable] = {}
    
    @classmethod
    def register(cls, protocol: str, adapter_func):
        cls._adapters[protocol] = adapter_func
        
    @classmethod
    async def call_agent(cls, payload: dict, protocol="http"):
        adapter = cls._adapters.get(protocol)
        if adapter:
            return await adapter(payload)
        # Default HTTP implementation
        async with aiohttp.ClientSession() as session:
            async with session.post(
                AGENT_API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                response.raise_for_status()
                return await response.json()

async def run_evaluation(scenario: dict) -> list:
    """Executes the evaluation with plugin hooks and registry lookups."""
    ctx = EvaluationContext(
        scenario_id=scenario.get("scenario_id", "unknown"),
        scenario_data=scenario
    )

    # Lifecycle Hook: before_evaluation
    plugins.manager.trigger("before_evaluation", ctx)
    
    all_task_results = []
    sandbox = ToolSandbox(scenario)
    
    print(f"   [Engine] Starting evaluation for scenario ID: {ctx.scenario_id}")

    try:
        sandbox.setup()
        for task in scenario.get("tasks", []):
            task_id = task.get("task_id")
            conversation_history: List[Dict[str, Any]] = []
            current_message = task.get("description") or ""
            turns_taken = 0
            agent_actions: Dict[str, Any] = {"used_tools": []}

            for turn in range(1, MAX_TURNS + 1):
                # Build Turn Context
                turn_ctx = TurnContext(
                    task_id=task_id,
                    turn_number=turn,
                    current_message=current_message,
                    history=conversation_history
                )
                
                try:
                    payload = {
                        "task_description": turn_ctx.current_message,
                        "turn": turn_ctx.turn_number,
                        "conversation_history": turn_ctx.history,
                    }
                    agent_response = await AgentAdapterRegistry.call_agent(payload)
                    turns_taken += 1
                    turn_ctx.agent_response = agent_response
                except Exception as e:
                    print(f"         [Engine] Communication error: {e}")
                    break

                # Lifecycle Hook: on_turn_end
                plugins.manager.trigger("on_turn_end", turn_ctx)

                conversation_history.append({"role": "agent", "content": agent_response})
                action = agent_response.get("action", "")

                if action == "call_tool" and "tool_name" in agent_response:
                    tool_name = agent_response["tool_name"]
                    tool_params = agent_response.get("tool_params", {})
                    agent_actions["used_tools"].append(tool_name)
                    state_before = sandbox.state.copy()
                    tool_result = sandbox.execute(tool_name, tool_params)
                    state_after = sandbox.state.copy()

                    if tool_result.get("status") == "policy_violation":
                        violation_msg = tool_result.get("violation", "Unknown policy violation")
                        conversation_history.append({
                            "role": "environment", 
                            "content": {"status": "policy_violation", "message": violation_msg},
                            "state_before": state_before, "state_after": state_after
                        })
                        current_message = f"GOVERNANCE ERROR: {violation_msg}. Please adjust your action."
                    else:
                        conversation_history.append({
                            "role": "environment", "content": tool_result,
                            "state_before": state_before, "state_after": state_after
                        })
                        current_message = f"Tool '{tool_name}' returned: {json.dumps(tool_result)}. Continue with the task."

                elif action == "call_multiple_tools" and "tool_names" in agent_response:
                    tool_names = agent_response["tool_names"]
                    agent_actions["used_tools"].extend(tool_names)
                    state_before = sandbox.state.copy()
                    all_tool_results = [sandbox.execute(tn, {}) for tn in tool_names]
                    state_after = sandbox.state.copy()
                    conversation_history.append({
                        "role": "environment", "content": all_tool_results,
                        "state_before": state_before, "state_after": state_after
                    })
                    current_message = f"Tools {tool_names} returned: {json.dumps(all_tool_results)}. Continue with the task."

                elif action in ("final_answer", "provide_instructions", "error"):
                    break
                else:
                    break
            else:
                print(f"         [Engine] Warning: Max turns reached for task {task_id}.")

            # --- METRIC CALCULATION (Using MetricRegistry) ---
            task_results = {
                "task_id": task_id,
                "turns_taken": turns_taken,
                "conversation_history": conversation_history,
                "metrics": [],
            }

            criteria = task.get("success_criteria", []).copy()
            # Defaults
            if "expected_state_changes" in task and not any(c["metric"] == "state_verification" for c in criteria):
                    criteria.append({"metric": "state_verification", "threshold": 1.0})
            for m in ["policy_compliance", "path_parsimony"]:
                if not any(c["metric"] == m for c in criteria):
                    criteria.append({"metric": m, "threshold": 0.5})

            for criterion in criteria:
                m_name = criterion.get("metric")
                threshold = criterion.get("threshold", 1.0)
                metric_func = metrics.MetricRegistry.get(m_name)
                
                score = 0.0
                if m_name == "tool_call_correctness" and metric_func:
                    score = metric_func(task.get("required_tools", []), agent_actions["used_tools"])
                elif m_name == "state_verification" and metric_func:
                    score = metric_func(task.get("expected_state_changes", []), sandbox.state)
                elif m_name == "policy_compliance" and metric_func:
                    score = metric_func(conversation_history)
                elif m_name == "path_parsimony" and metric_func:
                    score = metric_func(criterion, turns_taken, MAX_TURNS)
                elif metric_func is not None:
                    # Safely handle potential missing agent_response if communication failed
                    summary = agent_response.get("summary", "") if 'agent_response' in locals() and agent_response else ""
                    score = metric_func(criterion, summary)

                task_results["metrics"].append({
                    "metric": m_name, "score": score, "threshold": threshold, "success": score >= threshold
                })

            all_task_results.append(task_results)

    finally:
        ctx.grounding_hits = sandbox.grounding_hits
        sandbox.teardown()

    # Lifecycle Hook: after_evaluation
    plugins.manager.trigger("after_evaluation", ctx, all_task_results)
    return all_task_results
