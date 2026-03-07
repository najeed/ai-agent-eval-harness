"""
engine.py

This module provides the core evaluation engine for the AI Agent Evaluation Harness.
It is responsible for executing scenario tasks by interacting with an AI agent API
in a multi-turn conversation loop, evaluating the agent's performance using various
metrics, and returning the results.

Typical usage example:
    from eval_runner import engine
    results = await engine.run_evaluation(scenario_dict)
"""
# eval-runner/engine.py

import aiohttp
import json
import os
import asyncio
from . import metrics
from .tool_sandbox import ToolSandbox

# Read the agent URL from an environment variable, with a default for local testing
AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:5001/execute_task")

# Maximum number of conversation turns per task before forcing completion
MAX_TURNS = int(os.getenv("EVAL_MAX_TURNS", "5"))


async def run_evaluation(scenario: dict) -> list:
    """
    Executes the evaluation for a given scenario using a multi-turn conversation loop.

    For each task, the engine:
    1. Sends the task description to the agent.
    2. If the agent responds with a tool call, executes it via the ToolSandbox
       and sends the result back as the next turn.
    3. Repeats until the agent signals completion or MAX_TURNS is reached.

    Args:
        scenario (dict): The loaded scenario data.

    Returns:
        list: A list of result dicts per task, including metric scores and conversation history.
    """
    all_task_results = []
    sandbox = ToolSandbox(scenario)

    print(
        f"   [Engine] Starting evaluation for scenario ID: {scenario.get('scenario_id')}"
    )

    async with aiohttp.ClientSession() as session:
        for task in scenario.get("tasks", []):
            task_id = task.get("task_id")
            print(f"      [Engine] Executing task: {task_id} - {task.get('description')}")

            # --- MULTI-TURN CONVERSATION LOOP ---
            conversation_history = []
            agent_actions = {"used_tools": []}
            agent_response = {}
            current_message = task.get("description")

            for turn in range(1, MAX_TURNS + 1):
                print(f"         [Turn {turn}/{MAX_TURNS}] Sending: {current_message[:80]}...")

                try:
                    payload = {
                        "task_description": current_message,
                        "turn": turn,
                        "conversation_history": conversation_history,
                    }

                    async with session.post(
                        AGENT_API_URL,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as response:
                        response.raise_for_status()
                        agent_response = await response.json()

                except aiohttp.ClientError as e:
                    print(f"         [Engine] ❌ Connection error: {e}")
                    break
                except asyncio.TimeoutError:
                    print(f"         [Engine] ❌ Request timed out.")
                    break
                except json.JSONDecodeError:
                    print(f"         [Engine] ❌ Invalid JSON from agent.")
                    break

                # Record the turn
                conversation_history.append({"role": "agent", "content": agent_response})

                action = agent_response.get("action", "")

                # Extract tools used
                if action == "call_tool" and "tool_name" in agent_response:
                    tool_name = agent_response["tool_name"]
                    tool_params = agent_response.get("tool_params", {})
                    agent_actions["used_tools"].append(tool_name)

                    # Execute via sandbox and prepare the next turn
                    tool_result = sandbox.execute(tool_name, tool_params)
                    conversation_history.append({"role": "environment", "content": tool_result})
                    current_message = f"Tool '{tool_name}' returned: {json.dumps(tool_result)}. Continue with the task."

                elif action == "call_multiple_tools" and "tool_names" in agent_response:
                    tool_names = agent_response["tool_names"]
                    agent_actions["used_tools"].extend(tool_names)

                    # Execute each tool via sandbox
                    all_tool_results = []
                    for tn in tool_names:
                        result = sandbox.execute(tn, {})
                        all_tool_results.append(result)

                    conversation_history.append({"role": "environment", "content": all_tool_results})
                    current_message = f"Tools {tool_names} returned: {json.dumps(all_tool_results)}. Continue with the task."

                elif action in ("final_answer", "provide_instructions", "error"):
                    # Agent has completed or errored — exit the loop
                    print(f"         [Turn {turn}] Agent signaled '{action}'. Ending conversation.")
                    break
                else:
                    # Unknown action or no further tool calls — treat as completion
                    print(f"         [Turn {turn}] No further action from agent. Ending conversation.")
                    break
            else:
                print(f"         [Engine] ⚠️ Max turns ({MAX_TURNS}) reached for task {task_id}.")

            # --- METRIC CALCULATION ---
            task_results = {
                "task_id": task_id,
                "turns_taken": len(conversation_history),
                "metrics": [],
            }

            for criterion in task.get("success_criteria", []):
                metric_name = criterion.get("metric")
                summary = agent_response.get("summary", "")

                if metric_name == "tool_call_correctness":
                    score = metrics.calculate_tool_call_correctness(
                        task.get("required_tools", []), agent_actions["used_tools"]
                    )
                elif metric_name == "communication_clarity":
                    score = metrics.calculate_communication_clarity(summary)
                else:
                    # All other metrics use generic accuracy
                    score = metrics.calculate_generic_accuracy(criterion, summary)

                is_success = score >= criterion.get("threshold", 1.0)

                task_results["metrics"].append(
                    {
                        "metric": metric_name,
                        "score": score,
                        "threshold": criterion.get("threshold"),
                        "success": is_success,
                    }
                )

            all_task_results.append(task_results)

    return all_task_results
