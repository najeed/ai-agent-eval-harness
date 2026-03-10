"""
engine.py

Core evaluation engine.
Updated for universal extensibility via registries, hooks, and typed contexts.
"""

import os
import json
import aiohttp
import asyncio
from pathlib import Path
from datetime import datetime
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

async def run_evaluation(scenario: dict, attempts: int = 1) -> list:
    """Executes the evaluation with plugin hooks and registry lookups, supporting k attempts."""
    ctx = EvaluationContext(
        scenario_id=scenario.get("scenario_id", "unknown"),
        scenario_data=scenario
    )

    # Flight Recorder setup
    run_id = f"run-{ctx.scenario_id}-{int(asyncio.get_event_loop().time())}"
    report_dir = Path("runs")
    report_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = report_dir / "run.jsonl"
    
    def emit_event(event_data: dict):
        event_data["timestamp"] = datetime.now().isoformat() + "Z"
        content = json.dumps(event_data) + "\n"
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(content)

    emit_event({"event": "run_start", "run_id": run_id, "scenario": ctx.scenario_id, "k_attempts": attempts})

    # Lifecycle Hook: before_evaluation
    plugins.manager.trigger("before_evaluation", ctx)
    
    all_attempt_results = []
    
    print(f"   [Engine] Starting evaluation for scenario ID: {ctx.scenario_id} (k={attempts})")

    for k in range(1, attempts + 1):
        if attempts > 1:
            print(f"      [Engine] Attempt {k}/{attempts}...")
            
        all_task_results = []
        sandbox = ToolSandbox(scenario)
        
        try:
            sandbox.setup()
            for task in scenario.get("tasks", []):
                task_id = task.get("task_id")
                conversation_history: List[Dict[str, Any]] = []
                current_message = task.get("description") or ""
                turns_taken = 0
                agent_actions: Dict[str, Any] = {"used_tools": []}

                # Emit initial prompts
                emit_event({"event": "task_start", "task_id": task_id, "attempt": k})
                emit_event({"event": "prompt", "role": "user", "content": current_message})

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
                        
                        emit_event({
                            "event": "agent_response", 
                            "step": turn, 
                        })
                    except Exception as e:
                        print(f"         [Engine] Communication error: {e}")
                        conversation_history.append({"role": "system", "content": {"status": "error", "message": f"Communication Error: {str(e)}"}})
                        emit_event({"event": "error", "message": str(e)})
                        break

                    # Lifecycle Hook: on_turn_end
                    plugins.manager.trigger("on_turn_end", turn_ctx)

                    conversation_history.append({"role": "agent", "content": agent_response})
                    action = agent_response.get("action", "")

                    if action == "call_tool" and "tool_name" in agent_response:
                        tool_name = agent_response["tool_name"]
                        tool_params = agent_response.get("tool_params", {})
                        
                        emit_event({"event": "tool_call", "step": turn, "tool": tool_name, "arguments": tool_params})
                        
                        agent_actions["used_tools"].append(tool_name)
                        state_before = sandbox.state.copy()
                        tool_result = sandbox.execute(tool_name, tool_params)
                        state_after = sandbox.state.copy()

                        emit_event({"event": "tool_result", "step": turn, "tool": tool_name, "result": tool_result})

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
                        
                        for tn in tool_names:
                            emit_event({"event": "tool_call", "step": turn, "tool": tn, "arguments": {}})
                        
                        state_before = sandbox.state.copy()
                        all_tool_results = [sandbox.execute(tn, {}) for tn in tool_names]
                        state_after = sandbox.state.copy()
                        
                        for i, tn in enumerate(tool_names):
                            emit_event({"event": "tool_result", "step": turn, "tool": tn, "result": all_tool_results[i]})

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
                    "attempt": k,
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
                        summary = ""
                        agent_msgs = [m for m in conversation_history if m["role"] == "agent"]
                        if agent_msgs:
                            last_content = agent_msgs[-1].get("content", "")
                            if isinstance(last_content, dict):
                                summary = last_content.get("summary") or last_content.get("content") or ""
                            else:
                                summary = str(last_content)
                        
                        if asyncio.iscoroutinefunction(metric_func):
                            score = await metric_func(criterion, summary)
                        else:
                            score = metric_func(criterion, summary)

                    task_results["metrics"].append({
                        "metric": m_name, "score": score, "threshold": threshold, "success": score >= threshold
                    })
                    
                    emit_event({"event": "evaluation", "metric": m_name, "value": score, "attempt": k})

                all_task_results.append(task_results)

        finally:
            ctx.grounding_hits = sandbox.grounding_hits
            sandbox.teardown()
            
        all_attempt_results.append(all_task_results)

    # --- CROSS-ATTEMPT AGGREGATION (Consistency Score) ---
    if attempts > 1:
        print(f"   [Engine] Calculating cross-attempt metrics...")
        for task_idx, task in enumerate(scenario.get("tasks", [])):
            task_id = task.get("task_id")
            summaries = []
            for attempt_results in all_attempt_results:
                # Find task summary in this attempt
                task_res = next((tr for tr in attempt_results if tr["task_id"] == task_id), None)
                if task_res:
                    # Look for the last agent message in history to extract summary
                    agent_msgs = [m for m in task_res["conversation_history"] if m["role"] == "agent"]
                    if agent_msgs:
                        last_agent_content = agent_msgs[-1].get("content", "")
                        if isinstance(last_agent_content, dict):
                            summary = last_agent_content.get("summary") or last_agent_content.get("content") or ""
                        else:
                            summary = str(last_agent_content)
                        summaries.append(summary)
            
            if len(summaries) >= 2:
                consistency_func = metrics.MetricRegistry.get("consistency_score")
                if consistency_func:
                    c_score = consistency_func(summaries)
                    # Inject into the last attempt or a special aggregate record
                    # For now, let's inject into each attempt's task results as an aggregate metric
                    for attempt_results in all_attempt_results:
                         task_res = next((tr for tr in attempt_results if tr["task_id"] == task_id), None)
                         if task_res:
                             task_res["metrics"].append({
                                 "metric": "consistency_score", "score": c_score, "threshold": 0.5, "success": c_score >= 0.5
                             })
                             emit_event({"event": "evaluation", "metric": "consistency_score", "value": c_score, "task_id": task_id})

    # Lifecycle Hook: after_evaluation
    plugins.manager.trigger("after_evaluation", ctx, all_attempt_results)
    
    # Calculate pass@k
    successful_attempts = 0
    for attempt in all_attempt_results:
        # Check success of regular metrics (excluding consistency_score per attempt)
        if all(all(m["success"] for m in tr["metrics"] if m["metric"] != "consistency_score") for tr in attempt):
            successful_attempts += 1
            
    pass_at_k = successful_attempts / attempts if attempts > 0 else 0.0
    
    emit_event({"event": "run_end", "pass_at_k": pass_at_k, "successful_attempts": successful_attempts, "total_attempts": attempts})
    
    return all_attempt_results
