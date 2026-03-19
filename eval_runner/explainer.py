import json
from pathlib import Path
from .trace_utils import load_events

def explain_trace(trace_path: Path) -> dict:
    """
    Parses a run.jsonl file and identifies failure patterns.
    """
    from .triage import TriageEngine
    try:
        events = load_events(trace_path)
    except Exception as e:
        return {"root_cause": f"Error reading trace: {e}", "suggestion": "Check file permissions or JSON format."}

    # Use the high-fidelity TriageEngine
    rc = TriageEngine.identify_root_cause(events)
    
    diagnosis = {
        "index": rc["index"],
        "confidence": rc["confidence"],
        "root_cause": rc["reason"],
        "suggestion": "No specific suggestion found."
    }

    # Enhance logic with suggestions
    if rc["confidence"] >= 0.85:
        if "policy" in rc["reason"].lower():
             diagnosis["suggestion"] = "Review the AES safety policies and ensure the agent's prompt includes necessary guardrails."
        elif "system error" in rc["reason"].lower() or "tool" in rc["reason"].lower():
             diagnosis["suggestion"] = "Check the tool implementation and environment state at the pinpointed turn."
    elif rc["confidence"] >= 0.5:
         diagnosis["suggestion"] = "The agent failed to reach a conclusion. Try increasing EVAL_MAX_TURNS or refining the task objective."
    else:
         diagnosis["suggestion"] = "Review the full trajectory in the Visual Debugger for subtle logic deviations."

    return diagnosis
