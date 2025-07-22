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

import requests
import json
import os
from . import metrics

# Read the agent URL from an environment variable, with a default for local testing
AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:5001/execute_task")


# set AGENT_API_URL=http://aievalharness.pythonanywhere.com/execute_task
def run_evaluation(scenario: dict) -> list:
    """
    Executes the evaluation for a given scenario by simulating an AI agent performing each task and evaluating the outcome.

    Args:
        scenario (dict): A dictionary containing the loaded scenario data. Must include 'scenario_id' and a list of 'tasks'.

    Returns:
        list: A list of dictionaries, each containing the results for a single task, including metric scores and success status.

    Example:
        >>> scenario = {"scenario_id": "123", "tasks": [{"task_id": "t1", "description": "...", "success_criteria": [{"metric": "tool_call_correctness", "threshold": 1.0}]}]}
        >>> results = run_evaluation(scenario)
        >>> print(results)
        [{"task_id": "t1", "metrics": [{"metric": "tool_call_correctness", "score": 1.0, "threshold": 1.0, "success": True}]}]

    Raises:
        requests.exceptions.RequestException: If the agent API call fails.
        json.JSONDecodeError: If the agent response is not valid JSON.
    """
    all_task_results = []

    print(
        f"   [Engine] Starting evaluation for scenario ID: {scenario.get('scenario_id')}"
    )

    for task in scenario.get("tasks", []):
        task_id = task.get("task_id")
        print(f"      [Engine] Executing task: {task_id} - {task.get('description')}")

        # --- AGENT INTERACTION SIMULATION ---
        # In a real implementation, this is where you would call your AI agent's API.
        # The agent would be given the task description and access to the required tools.
        # For this skeleton, we'll simulate a successful outcome.

        # Placeholder for the agent's actual output and actions
        # agent_actions = {
        #    "used_tools": task.get("required_tools", []),
        #    "retrieved_info": "Simulated correct information",
        #    "final_answer": "Simulated correct final answer"
        # }

        # --- AGENT INTERACTION ---
        # This section would make a real HTTP call to the agent's API.
        agent_actions = {"used_tools": []}  # Default to empty list
        try:
            payload = {"task_description": task.get("description")}
            response = requests.post(AGENT_API_URL, json=payload, timeout=10)
            response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)

            agent_response = response.json()
            # Extract the tools used from the agent's response
            if "tool_name" in agent_response:
                agent_actions["used_tools"] = [agent_response["tool_name"]]
            elif "tool_names" in agent_response:
                agent_actions["used_tools"] = agent_response["tool_names"]

        except requests.exceptions.RequestException as e:
            print(
                f"      [Engine] ❌ ERROR: Could not connect to agent at {AGENT_API_URL}. Details: {e}"
            )
        except json.JSONDecodeError:
            print("      [Engine] ❌ ERROR: Failed to decode JSON response from agent.")

        # --- METRIC CALCULATION ---
        task_results = {"task_id": task_id, "metrics": []}

        for criterion in task.get("success_criteria", []):
            metric_name = criterion.get("metric")

            # This is a simplified dispatch. A more robust solution might use a
            # dictionary mapping metric names to functions.
            if metric_name == "tool_call_correctness":
                score = metrics.calculate_tool_call_correctness(
                    task.get("required_tools", []), agent_actions["used_tools"]
                )
            elif metric_name == "information_retrieval_accuracy":
                score = metrics.calculate_generic_accuracy()  # Simulate
            elif metric_name == "instructional_clarity":
                score = metrics.calculate_generic_accuracy()  # Simulate
            elif metric_name == "problem_resolution_effectiveness":
                score = metrics.calculate_generic_accuracy()  # Simulate
            elif metric_name == "process_adherence":
                score = metrics.calculate_generic_accuracy()  # Simulate
            elif metric_name == "root_cause_analysis_correctness":
                score = metrics.calculate_generic_accuracy()  # Simulate
            elif metric_name == "communication_clarity":
                score = metrics.calculate_communication_clarity()  # Simulate
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
