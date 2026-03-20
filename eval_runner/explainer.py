from pathlib import Path
from . import trace_utils
from . import triage

def explain_trace(trace_path: Path) -> dict:
    """
    Parses a run.jsonl file and identifies failure patterns.
    """
    try:
        events = trace_utils.load_events(trace_path)
    except Exception as e:
        return {"root_cause": f"Error reading trace: {e}", "suggestion": "Check file permissions or JSON format."}

    # Access via the module reference for reliable dynamic patching
    rc = triage.TriageEngine.identify_root_cause(events)
    
    diagnosis = {
        "index": rc.get("index", -1),
        "confidence": rc.get("confidence", 0.0),
        "root_cause": rc.get("reason", "Unknown failure"),
        "suggestion": rc.get("suggestion", "No specific suggestion found.")
    }

    # Specialized overrides for specific test requirements if triage didn't already set them
    if diagnosis["suggestion"] == "No specific suggestion found.":
        reason_lower = diagnosis["root_cause"].lower()
        if diagnosis["confidence"] >= 0.85:
            if "policy" in reason_lower or "compliance" in reason_lower:
                diagnosis["suggestion"] = "Review the AES safety policies and ensure the agent's prompt includes necessary guardrails (e.g., PII protection)."
            elif "system" in reason_lower or "connection" in reason_lower or "tool" in reason_lower:
                diagnosis["suggestion"] = "Check the tool implementation and infrastructure health at the pinpointed turn."
        elif diagnosis["confidence"] >= 0.5:
            diagnosis["suggestion"] = "The agent failed to reach a conclusion. Try increasing EVAL_MAX_TURNS or refining the task objective."
        else:
            diagnosis["suggestion"] = "Review the full trajectory in the Visual Debugger for subtle logic deviations."

    return diagnosis
