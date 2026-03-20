from __future__ import annotations

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
from . import config


def save_trajectory(scenario: dict, results: list, base_dir: Optional[Path] = None):
    """
    Saves a detailed JSON trajectory of the evaluation run.
    """
    # Systemic path resolution (Guardrail 4.7)
    if base_dir:
        report_dir = base_dir / "reports" / "trajectories"
    else:
        report_dir = config.TRAJECTORIES_DIR

    report_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scenario_id = scenario.get("scenario_id", "unknown")
    filename = f"{scenario_id}_{timestamp}.json"

    output = {
        "metadata": {
            "scenario_id": scenario_id,
            "title": scenario.get("title"),
            "industry": scenario.get("industry"),
            "timestamp": timestamp,
        },
        "results": results,
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
            framework = content.get("metadata", {}).get("framework", "")
            protocol = entry.get("protocol", "")
            agent = entry.get("agent", "")
            agent_name = entry.get("agent_name")

            label = f"{turn_idx}: {action}"
            if action == "unknown":
                if framework:
                    label = f"{turn_idx}: {framework}"
                elif protocol:
                    label = f"{turn_idx}: {protocol}"

            if agent_name:
                label += f" ({agent_name})"
            elif agent:
                # Add a truncated agent info for clarity if it's long
                agent_display = agent.split("://")[-1] if "://" in agent else agent
                if len(agent_display) > 20:
                    agent_display = agent_display[:17] + "..."
                label += f" ({agent_display})"

            mermaid.append(f'  {node_id}["{label}"]')
            mermaid.append(f"  {prev_node} --> {node_id}")
            prev_node = node_id
        elif role == "environment":
            status = content.get("status", "success")
            label = f"Env: {status}"

            # Special styling for violations
            if status == "policy_violation":
                mermaid.append(f"  {node_id}((Violation))")
                mermaid.append(
                    f"  style {node_id} fill:#f96,stroke:#333,stroke-width:4px"
                )
            else:
                mermaid.append(f'  {node_id}["{label}"]')

            mermaid.append(f"  {prev_node} --> {node_id}")
            prev_node = node_id
            turn_idx += 1

    mermaid.append(f"  {prev_node} --> End((End))")
    return "\n".join(mermaid)


def generate_html_report(
    scenario: dict, results: list, metadata: Optional[dict] = None
) -> Path:
    """
    Generates a premium HTML report for the evaluation results.
    """
    report_dir = config.HTML_REPORTS_DIR
    report_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    scenario_id = scenario.get("scenario_id", "unknown")
    filename = f"report_{scenario_id}_{timestamp}.html"
    filepath = report_dir / filename

    protocol = (metadata or {}).get("protocol", "unknown")
    agent = (metadata or {}).get("agent", "unknown")
    if agent == "unknown" or agent is None:
        if protocol == "http":
            agent = config.AGENT_API_URL
        elif protocol == "local":
            agent = os.getenv("AGENT_LOCAL_CMD") or "local-subprocess"
        elif protocol == "socket":
            agent = os.getenv("AGENT_SOCKET_ADDR") or "socket-connection"

    agent_name = (metadata or {}).get("agent_name")

    # Discovery: If not in metadata, scan results for a discovered name
    if not agent_name:
        for tr in results:
            for entry in tr.get("conversation_history", []):
                if entry.get("role") == "agent" and entry.get("agent_name"):
                    agent_name = entry["agent_name"]
                    break
            if agent_name:
                break

    total_tasks = len(results)
    successful_tasks = sum(
        1
        for tr in results
        if tr.get("metrics") and all(m["success"] for m in tr["metrics"])
    )
    success_rate = (successful_tasks / total_tasks * 100) if total_tasks > 0 else 0

    tasks_html = ""
    for tr in results:
        task_id = tr["task_id"]
        metrics = tr.get("metrics", [])
        is_success = bool(metrics) and all(m["success"] for m in metrics)
        status_class = "success" if is_success else "failure"
        status_text = (
            "PASSED" if is_success else f"FAILED [{tr.get('triage_tag', 'UNKNOWN')}]"
        )

        metrics_html = ""
        for m in tr["metrics"]:
            m_status = "pass" if m["success"] else "fail"
            metrics_html += f"""
                <div class="metric {m_status}">
                    <span class="m-name">{m['metric']}</span>
                    <span class="m-score">{m['score']:.2f} / {m['threshold']:.2f}</span>
                </div>
            """

        mermaid_code = generate_mermaid_trajectory(tr)

        tasks_html += f"""
            <div class="task-card {status_class}">
                <div class="task-header">
                    <h3>Task: {task_id}</h3>
                    <span class="badge {status_class}">{status_text}</span>
                </div>
                <div class="metrics-grid">
                    {metrics_html}
                </div>
                <div class="mermaid-container">
                    <pre class="mermaid">
{mermaid_code}
                    </pre>
                </div>
            </div>
        """

    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Eval Report: {scenario.get('title')}</title>
    <script src="{config.MERMAID_CDN}"></script>
    <script>mermaid.initialize({{startOnLoad:true, theme: '{config.MERMAID_THEME}'}});</script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: {config.HTML_BG_COLOR}; --card: {config.HTML_CARD_COLOR}; --text: {config.HTML_TEXT_COLOR}; --sub: {config.HTML_SUB_TEXT_COLOR};
            --success: {config.HTML_SUCCESS_COLOR}; --failure: {config.HTML_FAILURE_COLOR}; --accent: {config.HTML_ACCENT_COLOR};
        }}
        body {{ font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); padding: 40px; line-height: 1.6; }}
        .header {{ border-bottom: 2px solid var(--card); padding-bottom: 20px; margin-bottom: 40px; }}
        h1 {{ margin: 0; color: var(--accent); font-size: 2.5rem; }}
        .summary-box {{ display: flex; gap: 20px; margin-bottom: 40px; }}
        .stat {{ background: var(--card); padding: 20px; border-radius: 12px; flex: 1; border: 1px solid rgba(255,255,255,0.05); }}
        .stat-val {{ font-size: 2rem; font-weight: 700; display: block; }}
        .task-card {{ background: var(--card); border-radius: 16px; padding: 30px; margin-bottom: 30px; border-left: 6px solid var(--sub); }}
        .task-card.success {{ border-left-color: var(--success); }}
        .task-card.failure {{ border-left-color: var(--failure); }}
        .task-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }}
        .badge {{ padding: 6px 12px; border-radius: 20px; font-weight: 600; font-size: 0.8rem; }}
        .badge.success {{ background: rgba(16, 185, 129, 0.2); color: var(--success); }}
        .badge.failure {{ background: rgba(239, 68, 68, 0.2); color: var(--failure); }}
        .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 15px; margin-bottom: 25px; }}
        .metric {{ background: rgba(0,0,0,0.2); padding: 12px; border-radius: 8px; display: flex; flex-direction: column; }}
        .metric.pass {{ border: 1px solid var(--success); }}
        .metric.fail {{ border: 1px solid var(--failure); }}
        .m-name {{ font-size: 0.7rem; color: var(--sub); text-transform: uppercase; font-weight: bold; }}
        .m-score {{ font-family: 'JetBrains Mono', monospace; font-size: 1.1rem; }}
        .mermaid-container {{ background: rgba(15, 23, 42, 0.5); padding: 20px; border-radius: 8px; overflow-x: auto; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Evaluation Report</h1>
        <p style="color: var(--sub)">Scenario: {scenario.get('title')} ({scenario_id}) • {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
    </div>
    
    <div class="summary-box">
        <div class="stat">
            <span class="m-name">Success Rate</span>
            <span class="stat-val" style="color: var(--accent);">{success_rate:.1f}%</span>
        </div>
        <div class="stat">
            <span class="m-name">Tasks</span>
            <span class="stat-val">{successful_tasks} / {total_tasks}</span>
        </div>
        <div class="stat">
            <span class="m-name">Industry</span>
            <span class="stat-val">{scenario.get('industry', 'N/A').title()}</span>
        </div>
        <div class="stat">
            <span class="m-name">Protocol</span>
            <span class="stat-val" style="color: var(--accent);">{protocol.upper()}</span>
        </div>
        <div class="stat">
            <span class="m-name">Agent {"Name" if agent_name else "Target"}</span>
            <span class="stat-val" style="font-size: 1rem; overflow-wrap: break-word;">{agent_name or agent}</span>
        </div>
    </div>

    {tasks_html}
</body>
</html>
    """
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)

    return filepath


def generate_report(
    scenario: dict,
    results: list,
    export_trajectory: bool = False,
    export_html: bool = True,
    metadata: Optional[dict] = None,
):
    """
    Generates and prints a summary report of the evaluation results.
    """
    print("\n" + "=" * 50)
    print("EVALUATION REPORT")
    print("=" * 50)
    scenario_id = scenario.get("scenario_id")
    print(f"Scenario: {scenario.get('title')} ({scenario_id})")

    protocol = (metadata or {}).get("protocol", "http")
    agent_target = (metadata or {}).get("agent", "Unknown")

    # Defaulting: Resolve from system defaults if metadata is missing
    if agent_target == "Unknown" or agent_target is None:
        if protocol == "http":
            agent_target = config.AGENT_API_URL
        elif protocol == "local":
            agent_target = os.getenv("AGENT_LOCAL_CMD") or "local-subprocess"
        elif protocol == "socket":
            agent_target = os.getenv("AGENT_SOCKET_ADDR") or "socket-connection"

    agent_name = (metadata or {}).get("agent_name")

    # Discovery: Scan results if not in metadata
    if not agent_name:
        for tr in results:
            for entry in tr.get("conversation_history", []):
                if entry.get("role") == "agent" and entry.get("agent_name"):
                    agent_name = entry["agent_name"]
                    break
            if agent_name:
                break

    print(f"Protocol: {protocol.upper()}")
    print(f"Agent: {agent_name or agent_target}")
    print("-" * 50)

    total_tasks = len(results)
    successful_tasks = 0

    for task_result in results:
        task_id = task_result["task_id"]
        metrics_list = task_result.get("metrics", [])
        task_is_overall_success = bool(metrics_list) and all(
            m["success"] for m in metrics_list
        )

        if task_is_overall_success:
            status = "SUCCESS"
            successful_tasks += 1
        else:
            status = f"FAILURE [{task_result.get('triage_tag', 'UNKNOWN')}]"

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

    if export_html:
        html_path = generate_html_report(scenario, results, metadata=metadata)
        print(f"[Reporter] HTML report generated: {html_path}")
