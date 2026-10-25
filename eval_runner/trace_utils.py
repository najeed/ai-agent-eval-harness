import datetime
import json
from pathlib import Path
from typing import Any


class AESJsonEncoder(json.JSONEncoder):
    """
    Custom JSON encoder to handle non-standard types like Path, datetime, and Mock objects.
    """

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, datetime.datetime | datetime.date):
            return obj.isoformat()
        # Handle Mock objects (specifically for testing environments)
        if hasattr(obj, "__class__") and "Mock" in obj.__class__.__name__:
            return f"<Mock name={getattr(obj, '_mock_name', 'None')}>"
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)


def load_events(path: Path | str) -> list[dict[Any, Any]]:
    """
    Loads events from a trace file. Supports both JSONL and standard JSON array formats.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Trace file not found: {path}")

    with open(path, encoding="utf-8-sig") as f:
        content = f.read().strip()
        if not content:
            return []

        # Try to parse as a standard JSON array first if it looks like one
        if content.startswith("["):
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    return data
                return [data]
            except json.JSONDecodeError:
                # If it's not a valid JSON array, maybe it's just a JSONL file
                # where the first event happens to start with '[' (e.g. metadata)
                pass

        # Fallback to JSONL (line-by-line)
        events = []
        for line in content.splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    # Skip malformed lines in a JSONL file
                    continue

        if not events and content:
            raise ValueError("No valid JSON events could be parsed from the trace file.")

        return events


def reconstruct_results_from_events(events: list) -> list:
    """Reconstruct task results from authoritative, task-scoped trace events.

    A run trace includes run-level events (``run_start``, strategy transitions,
    and similar telemetry) that do not identify a workflow node.  They are
    evidence about the run, not task results, and must not become a synthetic
    ``unknown`` task in diagnostics.  Graph node events use
    ``scenario_node_id`` rather than ``task_id``; that identifier is the
    canonical task reference for compiled workflows.
    """
    from .triage import TriageEngine

    results_map: dict[str, dict[str, Any]] = {}

    def task_reference(event: dict[str, Any]) -> str | None:
        """Return the canonical node reference carried by a trace event."""
        for key in ("scenario_node_id", "task_id", "node_id"):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    def result_for(task_id: str) -> dict[str, Any]:
        return results_map.setdefault(
            task_id,
            {
                "task_id": task_id,
                "metrics": [],
                "conversation_history": [],
                "status": "success",
                "triage_tag": "SUCCESS",
            },
        )

    for event in events:
        if not isinstance(event, dict):
            continue
        task_id = task_reference(event)
        if task_id is None:
            continue
        ev_type = event.get("event")
        res = result_for(task_id)
        if ev_type == "evaluation":
            res["metrics"].append(
                {
                    "metric": event.get("metric"),
                    "score": event.get("value"),
                    "threshold": event.get("threshold", 0.5),
                    "success": event.get("success", False),
                }
            )
        elif ev_type in ["prompt", "agent_response", "tool_result"]:
            role = "agent" if ev_type == "agent_response" else "user"
            content = event.get("content") or {
                "action": event.get("tool"),
                "status": event.get("status"),
            }
            res["conversation_history"].append(
                {"role": role, "content": content, "_seq": event.get("_seq")}
            )
        elif ev_type == "execution_graph_node":
            status = str(event.get("status", "")).lower()
            res["conversation_history"].append(event)
            if status == "completed":
                res["status"] = "success"
                res["triage_tag"] = "SUCCESS"
            elif status in {"failed", "failure", "error"}:
                res["status"] = "failed"
                res["triage_tag"] = str(event.get("failure_class") or "UNKNOWN_FAILURE").upper()
            elif status:
                res["status"] = status
        elif ev_type == "hitl_pause":
            res["conversation_history"].append(event)
            if str(event.get("status", "")).upper() == "PAUSED_FOR_APPROVAL":
                res["status"] = "paused_for_approval"
                res["triage_tag"] = "PAUSED_FOR_APPROVAL"
    final_results = list(results_map.values())
    TriageEngine.apply_triage(final_results)
    return final_results
