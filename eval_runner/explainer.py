from . import triage


def explain_run(
    run_id: str,
    *,
    run_store: object,
    context: dict | None = None,
) -> dict:
    """Explain the authoritative event stream owned by ``run_store``."""
    get_events = getattr(run_store, "get_events", None)
    if not callable(get_events):
        raise TypeError("explain_run requires a RunStorageProvider")
    events = get_events(run_id, offset=0, limit=10_000_000, context=context)
    if not events:
        raise LookupError(f"Run '{run_id}' has no provider-owned events")
    return explain_events(events)


def explain_events(events: list[dict]) -> dict:
    """Identify failure patterns from authoritative run events."""
    # Access via the module reference for reliable dynamic patching
    rc = triage.TriageEngine.identify_root_cause(events)

    diagnosis = {
        "index": rc.get("index", -1),
        "_seq": rc.get("_seq"),
        "event_id": rc.get("event_id"),
        "confidence": rc.get("confidence", 0.0),
        "root_cause": rc.get("reason", "Unknown failure"),
        "suggestion": rc.get("suggestion", "No specific suggestion found."),
    }

    # Specialized overrides for specific test requirements if triage didn't already set them
    if diagnosis["suggestion"] == "No specific suggestion found.":
        reason_lower = diagnosis["root_cause"].lower()
        if diagnosis["confidence"] >= 0.85:
            if "policy" in reason_lower or "compliance" in reason_lower:
                diagnosis["suggestion"] = (
                    "Review the AES safety policies and ensure the agent's prompt includes necessary guardrails (e.g., PII protection)."  # noqa: E501
                )
            elif "system" in reason_lower or "connection" in reason_lower or "tool" in reason_lower:
                diagnosis["suggestion"] = (
                    "Check the tool implementation and infrastructure health at the pinpointed turn."  # noqa: E501
                )
        elif diagnosis["confidence"] >= 0.5:
            diagnosis["suggestion"] = (
                "The agent failed to reach a conclusion. Try increasing EVAL_MAX_TURNS or refining the task objective."  # noqa: E501
            )
        else:
            diagnosis["suggestion"] = (
                "Review the full trajectory in the Visual Debugger for subtle logic deviations."
            )

    return diagnosis
