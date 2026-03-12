from __future__ import annotations
"""
session.py

Manages the state and trajectory of an evaluation session.
Handles conversation history, tool results, and plugin interception.
"""

import json
import asyncio
import copy
from typing import List, Dict, Any, Optional
from dataclasses import replace
from .context import TurnContext
from .events import EventEmitter, CoreEvents
from . import plugins
from . import metrics

from . import config

# Security Guardrails: Fork Bomb Prevention
MAX_FORK_DEPTH = config.MAX_FORK_DEPTH
MAX_FORK_BREADTH = config.MAX_FORK_BREADTH

class SessionManager:
    """Manages a single evaluation attempt's lifecycle."""

    def __init__(self, scenario: dict, metadata: Optional[dict] = None):
        from .engine import MAX_TURNS
        self.scenario = scenario
        self.metadata = metadata or {}
        self.max_turns = int(scenario.get("max_turns", MAX_TURNS))
        self.fork_depth = scenario.get("_fork_depth", 0)

    async def execute_tasks(self, attempt_number: int) -> List[Dict[str, Any]]:
        from .engine import AgentAdapterRegistry  # Avoid circular import
        from .tool_sandbox import ToolSandbox
        
        all_task_results = []
        sandbox = ToolSandbox(self.scenario)
        sandbox.setup()
        
        try:
            for task in self.scenario.get("tasks", []):
                task_id = task.get("task_id")
                EventEmitter.emit(CoreEvents.TASK_START, {"task_id": task_id, "attempt": attempt_number})
                
                conversation_history = []
                current_message = task.get("description") or ""
                turns_taken = 0
                agent_actions = {"used_tools": []}

                EventEmitter.emit(CoreEvents.AGENT_REQUEST, {"role": "user", "content": current_message})
                conversation_history.append({"role": "user", "content": current_message})

                for turn in range(1, self.max_turns + 1):
                    turn_ctx = TurnContext(
                        task_id=task_id,
                        turn_number=turn,
                        current_message=current_message,
                        history=copy.deepcopy(conversation_history)
                    )

                    EventEmitter.emit(CoreEvents.TURN_START, {"turn": turn, "task_id": task_id})
                    plugins.manager.trigger("on_agent_turn_start", turn_ctx)

                    try:
                        payload = {
                            "task_description": turn_ctx.current_message,
                            "turn": turn_ctx.turn_number,
                            "conversation_history": turn_ctx.history,
                        }
                        
                        protocol = self.metadata.get("protocol", "http")
                        agent_response = await AgentAdapterRegistry.call_agent(payload, protocol=protocol)
                        turns_taken += 1
                        # Support immutable TurnContext
                        turn_ctx = replace(turn_ctx, agent_response=agent_response)
                        
                        EventEmitter.emit(CoreEvents.AGENT_RESPONSE, {"step": turn, "response": agent_response})
                    except Exception as e:
                        EventEmitter.emit(CoreEvents.ERROR, {"message": f"Agent Error: {str(e)}"})
                        break

                    conversation_history.append({"role": "agent", "content": agent_response})
                    action = agent_response.get("action", "")

                    if action == "call_tool":
                        await self._handle_tool_call(turn, agent_response, sandbox, conversation_history, agent_actions, turn_ctx)
                        current_message = self._get_last_env_message(conversation_history)
                    elif action == "call_multiple_tools" and "tool_names" in agent_response:
                        await self._handle_multiple_tools(turn, agent_response, sandbox, conversation_history, agent_actions, turn_ctx)
                        current_message = self._get_last_env_message(conversation_history)
                    elif action == "hitl_pause":
                        # HITL logic
                        EventEmitter.emit(CoreEvents.HITL_PAUSE, {"task_id": task_id, "turn": turn})
                        print(f"   [Session] HITL Pause at turn {turn}. Waiting for resume...")
                        # In a real system, we'd wait for an external signal or human input.
                        # For this implementation, we'll simulate a resume with a fixed message.
                        user_input = "Human has reviewed and approved. Proceed." 
                        conversation_history.append({"role": "human", "content": user_input})
                        current_message = user_input
                        EventEmitter.emit(CoreEvents.HITL_RESUME, {"task_id": task_id})
                    elif action == "branch" and "branches" in agent_response:
                        # Non-Linear Branching
                        branch_data = agent_response["branches"]
                        if len(branch_data) > MAX_FORK_BREADTH:
                            EventEmitter.emit(CoreEvents.ERROR, {"message": f"Fork Bomb Prevention: Breadth ({len(branch_data)}) exceeds max ({MAX_FORK_BREADTH})."})
                            break
                        if getattr(self, "fork_depth", 0) >= MAX_FORK_DEPTH:
                            EventEmitter.emit(CoreEvents.ERROR, {"message": f"Fork Bomb Prevention: Depth ({self.fork_depth}) exceeds max ({MAX_FORK_DEPTH})."})
                            break
                        print(f"   [Session] Branching detected: {len(branch_data)} new paths.")
                        # This is a research-phase implementation: we'll only execute the first branch here
                        # but in a full system we would queue separate evaluation attempts for each fork.
                        current_message = branch_data[0].get("message", current_message)
                        conversation_history.append({"role": "system", "content": f"Branching to: {branch_data[0].get('name')}"})
                    elif action in ("final_answer", "provide_instructions", "error"):
                        break
                    else:
                        break
                    
                    plugins.manager.trigger("on_turn_end", turn_ctx)

                # Metric calculation...
                # (I will keep the metric logic in the session for now but it's part of the orchestration)
                task_results = await self._calculate_metrics(task, attempt_number, turns_taken, conversation_history, sandbox, agent_actions)
                all_task_results.append(task_results)
                EventEmitter.emit(CoreEvents.TASK_END, {"task_id": task_id, "results": task_results})

        finally:
            sandbox.teardown()

        return all_task_results

    async def _handle_tool_call(self, turn, agent_response, sandbox, history, actions, turn_ctx):
        tool_name = agent_response["tool_name"]
        tool_params = agent_response.get("tool_params", {})
        
        # Interception Hook
        # Note: In a real implementation, we'd check if any plugin returns False
        allowed = plugins.manager.trigger_interceptor("on_tool_request", turn_ctx, tool_name, tool_params)
        if not allowed:
            EventEmitter.emit(CoreEvents.ERROR, {"message": f"Tool call {tool_name} blocked by plugin."})
            return

        EventEmitter.emit(CoreEvents.TOOL_CALL, {"step": turn, "tool": tool_name, "arguments": tool_params})
        actions["used_tools"].append(tool_name)
        
        state_before = sandbox.state.copy()
        result = sandbox.execute(tool_name, tool_params)
        state_after = sandbox.state.copy()
        
        EventEmitter.emit(CoreEvents.TOOL_RESULT, {"step": turn, "tool": tool_name, "result": result})
        
        history.append({
            "role": "environment", 
            "content": result,
            "state_before": state_before,
            "state_after": state_after
        })
        plugins.manager.trigger("on_tool_result", turn_ctx, tool_name, result)

    async def _handle_multiple_tools(self, turn, agent_response, sandbox, history, actions, turn_ctx):
        tool_names = agent_response["tool_names"]
        actions["used_tools"].extend(tool_names)
        
        for tn in tool_names:
            EventEmitter.emit(CoreEvents.TOOL_CALL, {"step": turn, "tool": tn, "arguments": {}})
        
        all_tool_results = []
        state_before = sandbox.state.copy()
        for tn in tool_names:
            # Note: Single interception for multiple tools could be complex; here we check each
            allowed = plugins.manager.trigger_interceptor("on_tool_request", turn_ctx, tn, {})
            if allowed:
                res = sandbox.execute(tn, {})
                all_tool_results.append(res)
                EventEmitter.emit(CoreEvents.TOOL_RESULT, {"step": turn, "tool": tn, "result": res})
            else:
                all_tool_results.append({"status": "blocked", "message": f"Tool {tn} blocked by plugin."})
        state_after = sandbox.state.copy()

        history.append({
            "role": "environment", 
            "content": all_tool_results,
            "state_before": state_before,
            "state_after": state_after
        })

    def _get_last_env_message(self, history):
        if not history: return ""
        last = history[-1]
        if last["role"] == "environment":
            content = last["content"]
            if isinstance(content, list):
                return f"Tools returned: {json.dumps(content)}"
            return content.get("message") or content.get("content") or str(content)
        return ""

    async def _calculate_metrics(self, task, k, turns, history, sandbox, actions):
        import inspect
        results = {
            "task_id": task.get("task_id"),
            "attempt": k,
            "turns_taken": turns,
            "conversation_history": history,
            "metrics": [],
        }

        criteria = task.get("success_criteria", []).copy()
        # Ensure default metrics
        if "expected_state_changes" in task and not any(c["metric"] == "state_verification" for c in criteria):
            criteria.append({"metric": "state_verification", "threshold": 1.0})
        
        for criterion in criteria:
            m_name = criterion.get("metric")
            threshold = criterion.get("threshold", 1.0)
            metric_func = metrics.MetricRegistry.get(m_name)
            
            score = 0.0
            if m_name == "tool_call_correctness" and metric_func:
                score = metric_func(task.get("required_tools", []), actions["used_tools"])
            elif m_name == "state_verification" and metric_func:
                score = metric_func(task.get("expected_state_changes", []), sandbox.state)
            elif m_name == "policy_compliance" and metric_func:
                score = metric_func(history)
            elif m_name == "path_parsimony" and metric_func:
                score = metric_func(criterion, turns, self.max_turns)
            elif metric_func is not None:
                summary = self._extract_agent_summary(history)
                if inspect.iscoroutinefunction(metric_func):
                    score = await metric_func(criterion, summary)
                else:
                    score = metric_func(criterion, summary)

            results["metrics"].append({
                "metric": m_name, "score": score, "threshold": threshold, "success": score >= threshold
            })
            EventEmitter.emit(CoreEvents.EVALUATION, {"metric": m_name, "value": score, "attempt": k})

        return results

    def _extract_agent_summary(self, history):
        agent_msgs = [m for m in history if m["role"] == "agent"]
        if not agent_msgs: return ""
        last_content = agent_msgs[-1].get("content", "")
        if isinstance(last_content, dict):
            # Try to find a meaningful string across common fields
            return (
                last_content.get("summary") or 
                last_content.get("instructions") or 
                last_content.get("content") or 
                last_content.get("action") or 
                ""
            )
        return str(last_content)

    def fork(self, history: List[Dict[str, Any]], sandbox_state: Dict[str, Any]) -> SessionManager:
        """
        Creates a clone of the current session at a specific checkpoint.
        Supports research into non-linear trajectories.
        """
        if getattr(self, "fork_depth", 0) >= MAX_FORK_DEPTH:
            raise RuntimeError(f"Fork Bomb Prevention: Maximum depth ({MAX_FORK_DEPTH}) reached.")
        scenario_copy = copy.deepcopy(self.scenario)
        scenario_copy["_fork_depth"] = getattr(self, "fork_depth", 0) + 1
        new_session = SessionManager(scenario_copy)
        # Note: In a full implementation, we'd need to deep copy the sandbox
        # and ensure the conversation history is properly partitioned.
        print(f"   [Session] Forking trajectory with {len(history)} messages in history.")
        return new_session
