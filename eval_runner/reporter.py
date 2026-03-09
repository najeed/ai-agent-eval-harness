"""
reporter.py

This module provides reporting utilities for the AI Agent Evaluation Harness.
It generates summary reports, exports detailed trajectories, and generates Mermaid visualizations.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

def save_trajectory(scenario: dict, results: list, base_dir: Optional[Path] = None):
    """
    Saves a detailed JSON trajectory of the evaluation run.
    """
    # Systemic path resolution (Guardrail 4.7)
    if base_dir is None:
        base_dir = Path(__file__).parent.parent
    
    # mypy fix: base_dir is now definitely Path
    report_dir = base_dir / "reports" / "trajectories"
    report_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scenario_id = scenario.get("scenario_id", "unknown")
    filename = f"{scenario_id}_{timestamp}.json"
    
    output = {
        "metadata": {
            "scenario_id": scenario_id,
            "title": scenario.get("title"),
            "industry": scenario.get("industry"),
            "timestamp": timestamp
        },
        "results": results
    }
    
    filepath = report_dir / filename
    with open(filepath, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"\n[Reporter] Trajectory exported to: {filepath}")

def generate_mermaid_trajectory(task_results: dict) -> str:
    """
    Generates a Mermaid graph TD string representing the agent's path.
    """
    history = task_results.get("conversation_history", [])
    if not history:
        return ""
    
    mermaid = ["graph TD"]
    mermaid.append("  Start((Start))")
    
    prev_node = "Start"
    turn_idx = 1
    
    for entry in history:
        role = entry.get("role")
        content = entry.get("content")
        if not isinstance(content, dict):
            content = {}
        
        node_id = f"Turn_{turn_idx}_{role}"
        
        if role == "agent":
            action = content.get("action", "unknown")
            label = f"{turn_idx}: {action}"
            mermaid.append(f'  {node_id}["{label}"]')
            mermaid.append(f"  {prev_node} --> {node_id}")
            prev_node = node_id
        elif role == "environment":
            status = content.get("status", "success")
            label = f"Env: {status}"
            
            # Special styling for violations
            if status == "policy_violation":
                mermaid.append(f"  {node_id}((Violation))")
                mermaid.append(f"  style {node_id} fill:#f96,stroke:#333,stroke-width:4px")
            else:
                mermaid.append(f'  {node_id}["{label}"]')
            
            mermaid.append(f"  {prev_node} --> {node_id}")
            prev_node = node_id
            turn_idx += 1
            
    mermaid.append(f"  {prev_node} --> End((End))")
    return "\n".join(mermaid)

def generate_report(scenario: dict, results: list, export_trajectory: bool = False):
    """
    Generates and prints a summary report of the evaluation results.
    """
    print("\n" + "=" * 50)
    print("EVALUATION REPORT")
    print("=" * 50)
    print(f"Scenario: {scenario.get('title')} ({scenario.get('scenario_id')})")
    print(f"Industry: {scenario.get('industry')}")
    print(f"Description: {scenario.get('description')}")
    print("-" * 50)

    total_tasks = len(results)
    successful_tasks = 0

    for task_result in results:
        task_id = task_result["task_id"]
        task_is_overall_success = all(m["success"] for m in task_result["metrics"])

        if task_is_overall_success:
            status = "SUCCESS"
            successful_tasks += 1
        else:
            status = "FAILURE"

        print(f"\nTask: {task_id} [{status}]")

        for metric in task_result["metrics"]:
            metric_status = "PASSED" if metric["success"] else "FAILED"
            print(
                f"  {metric_status} Metric: {metric['metric']:<35} "
                f"| Score: {metric['score']:.2f} "
                f"| Threshold: {metric['threshold']:.2f}"
            )
            
        # Add Mermaid snippet for failed tasks or if requested
        if not task_is_overall_success:
            print("\n  Trajectory Map (Mermaid):")
            print("  ---")
            print(generate_mermaid_trajectory(task_result))
            print("  ---")

    print("\n" + "-" * 50)
    print("SUMMARY")
    print("-" * 50)

    success_rate = (successful_tasks / total_tasks) * 100 if total_tasks > 0 else 0

    print(f"Total Tasks: {total_tasks}")
    print(f"Successful Tasks: {successful_tasks}")
    print(f"Failed Tasks: {total_tasks - successful_tasks}")
    print(f"Overall Success Rate: {success_rate:.2f}%")
    print("=" * 50 + "\n")
    
    if export_trajectory:
        save_trajectory(scenario, results)
