from __future__ import annotations

"""
session.py

Manages the state and trajectory of an evaluation session.
Handles conversation history, tool results, and plugin interception.
"""

import os
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
        self.session_metadata = dict(metadata) if metadata else {}
        self.max_turns = int(scenario.get("max_turns", MAX_TURNS))
        self.fork_depth = scenario.get("_fork_depth", 0)

    async def execute_tasks(self, attempt_number: int) -> List[Dict[str, Any]]:
        from .engine import AgentAdapterRegistry
        from .tool_sandbox import ToolSandbox

        from graphlib import TopologicalSorter, CycleError

        all_task_results = []
        executed_nodes = set()
        sandbox = ToolSandbox(self.scenario)
        sandbox.setup()

        try:
            workflow = self.scenario.get("workflow", {})
            nodes_data = {node["id"]: node for node in workflow.get("nodes", [])}
            edges = workflow.get("edges", [])

            # 1. Build Dependency Graph
            graph = {node_id: set() for node_id in nodes_data}
            for edge in edges:
                if edge["to"] in graph:
                    graph[edge["to"]].add(edge["from"])

            # 4. Topological Sort (Stable DAG Logic)
            try:
                ts = TopologicalSorter(graph)
                execution_order = list(ts.static_order())
            except CycleError as e:
                print(f"      [Session] Cycle Error in workflow: {e}")
                # Fallback or strict fail? User requested "real implementation".
                # We should fail the session as DAGs by definition are acyclic.
                raise ValueError(f"Workflow contains cyclic dependencies: {e}")

            # 3. Handle Empty Workflow
            if not nodes_data:
                raise ValueError("Scenario missing required 'workflow' block (Unified Standard v1.2)")
            for node_id in execution_order:
                node = nodes_data.get(node_id)
                if not node:
                    continue # Should not happen with built graph

                task_description = node.get("task_description")
                
                EventEmitter.emit(
                    CoreEvents.TASK_START,
                    {"task_id": node_id, "attempt": attempt_number},
                    span_context=self.session_metadata.get("span_context")
                )

                conversation_history = []
                current_message = task_description or ""
                turns_taken = 0
                agent_actions = {"used_tools": []}

                protocol = self.session_metadata.get("protocol", "http")
                endpoint = self.session_metadata.get("agent")
                agent_name = self.session_metadata.get("agent_name")

                EventEmitter.emit(
                    CoreEvents.AGENT_REQUEST,
                    {
                        "role": "user",
                        "content": current_message,
                        "protocol": protocol,
                        "agent": endpoint,
                        "agent_name": agent_name,
                    },
                    span_context=self.session_metadata.get("span_context")
                )
                conversation_history.append({"role": "user", "content": current_message})

                for turn in range(1, self.max_turns + 1):
                    # R3.2 Remediation: Turn-Based Throttling
                    if config.EVAL_TURN_THROTTLE > 0:
                        await asyncio.sleep(config.EVAL_TURN_THROTTLE)

                    turn_ctx = TurnContext(
                        task_id=node_id,
                        turn_number=turn,
                        current_message=current_message,
                        history=copy.deepcopy(conversation_history),
                        span_context=self.session_metadata.get("span_context"),
                    )

                    EventEmitter.emit(CoreEvents.TURN_START, {"turn": turn, "task_id": node_id}, span_context=turn_ctx.span_context)
                    plugins.manager.trigger("on_agent_turn_start", turn_ctx)

                    try:
                        payload = {
                            "task_description": turn_ctx.current_message,
                            "turn": turn_ctx.turn_number,
                            "conversation_history": turn_ctx.history,
                        }
                        # Resolve endpoint defaults (Restored from previous version)
                        protocol = self.session_metadata.get("protocol", "http")
                        endpoint = self.session_metadata.get("agent")
                        if not endpoint:
                            if protocol == "http":
                                endpoint = config.AGENT_API_URL
                            elif protocol == "local":
                                endpoint = os.getenv("AGENT_LOCAL_CMD")
                        
                        agent_response = await AgentAdapterRegistry.call_agent(
                            payload, protocol=protocol, endpoint=endpoint, span_context=turn_ctx.span_context
                        )
                        turns_taken = turn

                        if not agent_name:
                             # Discover name...
                             agent_name = (
                                 agent_response.get("name") 
                                 or agent_response.get("agent_name") 
                                 or agent_response.get("metadata", {}).get("name")
                                 or "Agent"
                             )
                             self.session_metadata["agent_name"] = agent_name

                        turn_ctx = replace(turn_ctx, agent_response=agent_response)
                        EventEmitter.emit(
                            CoreEvents.AGENT_RESPONSE, 
                            {
                                "step": turn, 
                                "response": agent_response,
                                "agent_name": agent_name
                            },
                            span_context=turn_ctx.span_context
                        )
                    except Exception as e:
                        EventEmitter.emit(CoreEvents.ERROR, {"message": f"Agent Error: {str(e)}"})
                        break

                    conversation_history.append({"role": "agent", "content": self._sanitize_for_history(agent_response)})
                    action = agent_response.get("action", "")

                    if action == "call_tool":
                        await self._handle_tool_call(turn, agent_response, sandbox, conversation_history, agent_actions, turn_ctx)
                        current_message = self._get_last_env_message(conversation_history)
                    elif action == "call_multiple_tools":
                        await self._handle_multiple_tools(turn, agent_response, sandbox, conversation_history, agent_actions, turn_ctx)
                        current_message = self._get_last_env_message(conversation_history)
                    elif action == "hitl_pause":
                        # Guardrail 4.6.4: Interactive Recovery
                        human_response = await self._handle_hitl(node_id, agent_response.get("prompt", "Agent requested intervention."))
                        conversation_history.append({"role": "human", "content": human_response})
                        current_message = human_response
                    elif action in ("final_answer", "provide_instructions", "error"):
                        break
                    else:
                        break

                    plugins.manager.trigger("on_turn_end", turn_ctx)

                # Metric calculation...
                task_results = await self._calculate_metrics(
                    node,
                    attempt_number,
                    turns_taken,
                    conversation_history,
                    sandbox,
                    agent_actions,
                )
                all_task_results.append(task_results)
                executed_nodes.add(node_id)
                EventEmitter.emit(CoreEvents.TASK_END, {"task_id": node_id, "results": task_results}, span_context=self.session_metadata.get("span_context"))

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
            EventEmitter.emit(
                CoreEvents.ERROR,
                {"message": f"Tool call {tool_name} blocked by plugin."},
            )
            return

        EventEmitter.emit(
            CoreEvents.TOOL_CALL,
            {"step": turn, "tool": tool_name, "arguments": tool_params},
        )
        actions["used_tools"].append(tool_name)

        state_before = sandbox.state.copy()
        result = sandbox.execute(tool_name, tool_params)
        state_after = sandbox.state.copy()

        EventEmitter.emit(CoreEvents.TOOL_RESULT, {"step": turn, "tool": tool_name, "result": result}, span_context=turn_ctx.span_context)

        history.append(
            {
                "role": "environment",
                "content": self._sanitize_for_history(result),
                "state_before": copy.deepcopy(state_before),
                "state_after": copy.deepcopy(state_after),
            }
        )
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

        history.append(
            {
                "role": "environment",
                "content": all_tool_results,
                "state_before": state_before,
                "state_after": state_after,
            }
        )

    async def _handle_hitl(self, task_id: str, prompt: str) -> str:
        """Handles Human-In-The-Loop interaction."""
        import os
        from .events import EventEmitter, CoreEvents
        
        # Guardrail 4.6.4: CI Auto-Approval
        if os.getenv("CI", "").lower() == "true":
            response = f"Auto-approved (CI-Override): {prompt}"
            EventEmitter.emit(CoreEvents.HITL_RESUME, {"task_id": task_id, "response": response})
            print(f"      [HITL] CI Mode: Auto-approving task {task_id}")
            return response

        # Standard interactive input
        EventEmitter.emit(CoreEvents.HITL_PAUSE, {"task_id": task_id, "prompt": prompt})
        
        # Check if we are in a TTY or have a way to get input
        import sys
        if sys.stdin.isatty():
            print(f"\n      [HITL] Agent is requesting intervention for task '{task_id}':")
            print(f"      > {prompt}")
            response = input("      Enter response (or 'exit' to abort): ").strip()
            if response.lower() == "exit":
                raise InterruptedError("User aborted evaluation.")
            EventEmitter.emit(CoreEvents.HITL_RESUME, {"task_id": task_id, "response": response})
            return response
        else:
            summary = prompt[:50] + "..." if len(prompt) > 50 else prompt
            response = f"[Simulation] Interaction for '{summary}' acknowledged in non-interactive mode."
            EventEmitter.emit(CoreEvents.HITL_RESUME, {"task_id": task_id, "response": response})
            print(f"      [HITL] Non-interactive environment: {response}")
            return response

    def _get_last_env_message(self, history):
        if not history:
            return ""
        last = history[-1]
        if last["role"] == "environment":
            content = last["content"]
            if isinstance(content, list):
                return f"Tools returned: {json.dumps(content)}"
            return content.get("message") or content.get("content") or str(content)
        return ""

    async def _calculate_metrics(self, node, attempt_number, turns, history, sandbox, actions):
        node_id = node.get("id")
        results = {
            "task_id": node_id,
            "attempt": attempt_number,
            "turns_taken": turns,
            "conversation_history": history,
            "metrics": [],
        }

        # v1.2 Hardened Metrics: Pre-condition check (State Hygiene)
        sh = node.get("state_hygiene", {})
        if sh:
            hygiene_results = []
            for rule in sh.get("rules", []):
                path = rule.get("path")
                expected = rule.get("expected")
                op = rule.get("op", "eq") # eq, exists, not_exists, contains

                # Resolve nested path in sandbox.state
                parts = path.split(".")
                val = sandbox.state
                try:
                    for part in parts:
                        if "[" in part:
                            # Handle dict/list indexing: e.g. "git[file_tree]"
                            key = part.split("[")[1].split("]")[0].strip("'\"")
                            part = part.split("[")[0]
                            if part: val = val.get(part, {})
                            val = val.get(key)
                        else:
                            val = val.get(part)
                except (AttributeError, KeyError, TypeError):
                    val = None

                success = False
                if op == "eq": success = val == expected
                elif op == "exists": success = val is not None
                elif op == "not_exists": success = val is None
                elif op == "contains": success = expected in val if val else False
                
                hygiene_results.append({
                    "path": path,
                    "op": op,
                    "success": success
                })
            
            # Record hygiene as a meta-metric or log it
            if hygiene_results:
                results["state_hygiene"] = hygiene_results

        # Parse success_criteria from node if it exists (for compatibility)
        # or use the v1.2 expected_outcome
        outcome = node.get("expected_outcome", {})
        
        # Mapping legacy-like success criteria if still present in the node
        criteria = node.get("success_criteria", []).copy()
        
        for criterion in criteria:
            try:
                m_name = criterion.get("metric")
                threshold = criterion.get("threshold", 1.0)
                metric_func = metrics.MetricRegistry.get(m_name)

                async def _invoke(func, *args):
                    if asyncio.iscoroutinefunction(func):
                        return await func(*args)
                    return func(*args)

                score = 0.0
                if m_name == "tool_call_correctness" and metric_func:
                    score = await _invoke(metric_func, node.get("required_tools", []), actions["used_tools"])
                elif m_name == "state_verification" and metric_func:
                    score = await _invoke(metric_func, node.get("expected_state_changes", []), sandbox.state)
                elif m_name == "policy_compliance" and metric_func:
                    score = await _invoke(metric_func, history)
                elif m_name == "path_parsimony" and metric_func:
                    score = await _invoke(metric_func, criterion, turns, self.max_turns)
                elif metric_func is not None:
                    summary = self._extract_agent_summary(history)
                    score = await _invoke(metric_func, criterion, summary)
                else:
                    continue

                results["metrics"].append({
                    "metric": m_name,
                    "score": score,
                    "threshold": threshold,
                    "success": score >= threshold
                })
            except Exception as e:
                print(f"      [Metric Error] {node_id}: {e}")

        return results

    def _extract_agent_summary(self, history):
        agent_msgs = [m for m in history if m["role"] == "agent"]
        if not agent_msgs:
            return ""
        last_content = agent_msgs[-1].get("content", "")
        if isinstance(last_content, dict):
            # Try to find a meaningful string across common fields
            return last_content.get("summary") or last_content.get("instructions") or last_content.get("content") or ""
        return str(last_content)

    def _sanitize_for_history(self, obj: Any) -> Any:
        """Coerces objects (especially Mocks) into plain serializable types for history safety."""
        from .trace_utils import AESJsonEncoder
        encoder = AESJsonEncoder()

        if isinstance(obj, dict):
            return {str(k): self._sanitize_for_history(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._sanitize_for_history(i) for i in obj]
        elif isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        
        try:
            # Leverage the specialized encoder's default logic for leaf values
            return encoder.default(obj)
        except TypeError:
            # Fallback to string representation for anything else
            return str(obj)

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
