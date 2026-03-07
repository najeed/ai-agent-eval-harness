"""
engine.py

This module provides the core evaluation engine for the AI Agent Evaluation Harness.
It is responsible for executing scenario tasks by interacting with an AI agent API,
evaluating the agent's performance using various metrics, and returning the results.

Typical usage example:
    from eval_runner import engine
    results = engine.run_evaluation(scenario_dict)
"""
# eval-runner/engine.py

import aiohttp
import json
import os
import asyncio
from . import metrics

# Read the agent URL from an environment variable, with a default for local testing
AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:5001/execute_task")


async def run_evaluation(scenario: dict) -> list:
    """
    Executes the evaluation for a given scenario asynchronously by simulating an AI agent performing each task.

    Args:
        scenario (dict): A dictionary containing the loaded scenario data. Must include 'scenario_id' and a list of 'tasks'.

    Returns:
        list: A list of dictionaries, each containing the results for a single task, including metric scores and success status.
    """
    all_task_results = []

    print(
        f"   [Engine] Starting evaluation for scenario ID: {scenario.get('scenario_id')}"
    )

    async with aiohttp.ClientSession() as session:
        for task in scenario.get("tasks", []):
            task_id = task.get("task_id")
            print(f"      [Engine] Executing task: {task_id} - {task.get('description')}")

            # --- AGENT INTERACTION ---
            agent_actions = {"used_tools": []}  # Default to empty list
            agent_response = {}  # Default to empty dict to prevent UnboundLocalError
            try:
                payload = {"task_description": task.get("description")}
                
                async with session.post(AGENT_API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    response.raise_for_status()
                    agent_response = await response.json()
                    
                    # Extract the tools used from the agent's response
                    if "tool_name" in agent_response:
                        agent_actions["used_tools"] = [agent_response["tool_name"]]
                    elif "tool_names" in agent_response:
                        agent_actions["used_tools"] = agent_response["tool_names"]

            except aiohttp.ClientError as e:
                print(
                    f"      [Engine] ❌ ERROR: Could not connect to agent at {AGENT_API_URL}. Details: {e}"
                )
            except asyncio.TimeoutError:
                print(f"      [Engine] ❌ ERROR: Request to {AGENT_API_URL} timed out.")
            except json.JSONDecodeError:
                print("      [Engine] ❌ ERROR: Failed to decode JSON response from agent.")

            # --- METRIC CALCULATION ---
            task_results = {"task_id": task_id, "metrics": []}

            for criterion in task.get("success_criteria", []):
                metric_name = criterion.get("metric")

                # Simplified dispatch
                if metric_name == "tool_call_correctness":
                    score = metrics.calculate_tool_call_correctness(
                        task.get("required_tools", []), agent_actions["used_tools"]
                    )
                elif metric_name == "information_retrieval_accuracy":
                    score = metrics.calculate_generic_accuracy(criterion, agent_response.get("summary", ""))
                elif metric_name == "instructional_clarity":
                    score = metrics.calculate_generic_accuracy(criterion, agent_response.get("summary", ""))
                elif metric_name == "problem_resolution_effectiveness":
                    score = metrics.calculate_generic_accuracy(criterion, agent_response.get("summary", ""))
                elif metric_name == "process_adherence":
                    score = metrics.calculate_generic_accuracy(criterion, agent_response.get("summary", ""))
                elif metric_name == "root_cause_analysis_correctness":
                    score = metrics.calculate_generic_accuracy(criterion, agent_response.get("summary", ""))
                elif metric_name == "communication_clarity":
                    score = metrics.calculate_communication_clarity(agent_response.get("summary", ""))
                else:
                    score = 0.0  # Unknown metric

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
