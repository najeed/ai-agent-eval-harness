"""
explainer.py

Analyze trace logs (run.jsonl) to diagnose root causes and suggest fixes.
"""

import json
from pathlib import Path

def explain_trace(trace_path: Path) -> dict:
    """
    Parses a run.jsonl file and identifies failure patterns.
    """
    events = []
    try:
        with open(trace_path, "r", encoding="utf-8") as f:
            for line in f:
                events.append(json.loads(line))
    except Exception as e:
        return {"root_cause": f"Error reading trace: {e}", "suggestion": "Check file permissions or JSON format."}

    # Heuristic analysis
    diagnosis = {
        "root_cause": "Unknown",
        "suggestion": "No specific suggestion found."
    }

    # 1. Check for infinite loops (repeated prompts/responses)
    prompts = [e.get("content") for e in events if e.get("event") == "prompt"]
    if len(prompts) > 10 and len(set(prompts)) < len(prompts) / 2:
        diagnosis = {
            "root_cause": "Infinite Loop Detected (Repetitive Prompts)",
            "suggestion": "Review agent logic for circular reasoning or missing termination guards."
        }
        return diagnosis

    # 2. Check for tool timeouts or errors
    tool_results = [e for e in events if e.get("event") == "tool_result"]
    for res in tool_results:
        result_val = str(res.get("result", "")).lower()
        if "timeout" in result_val:
            diagnosis = {
                "root_cause": f"Tool Timeout: {res.get('tool')}",
                "suggestion": "Increase the tool sandbox timeout or optimize the backend service."
            }
            return diagnosis
        if "error" in result_val or "exception" in result_val:
            diagnosis = {
                "root_cause": f"Tool Error in {res.get('tool')}: {res.get('result')}",
                "suggestion": "Debug the tool implementation or check for missing environment variables."
            }
            return diagnosis

    # 3. Check for policy violations
    evaluations = [e for e in events if e.get("event") == "evaluation"]
    for ev in evaluations:
        if ev.get("metric") == "policy_compliance" and ev.get("value") == 0.0:
            diagnosis = {
                "root_cause": "Policy Violation (Safety/Privacy Guardrail)",
                "suggestion": "Check if the agent is leaking sensitive data (PII) or attempting forbidden actions."
            }
            return diagnosis

    # 4. Check for pass@k failure
    if not any(e.get("event") == "run_end" and e.get("status") == "success" for e in events):
        diagnosis = {
            "root_cause": "Target Task Not Completed",
            "suggestion": "Increase EVAL_MAX_TURNS or refine the agent's prompt to be more specific."
        }

    return diagnosis
