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
    Executes the evaluation for a given scenario.

    This function iterates through the tasks defined in the scenario,
    simulates an AI agent performing those tasks, and evaluates the
    outcome against the defined success criteria.

    Args:
        scenario: A dictionary containing the loaded scenario data.

    Returns:
        A list of dictionaries, where each dictionary contains the
        results for a single task.
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
