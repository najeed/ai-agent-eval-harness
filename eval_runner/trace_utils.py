import json
from pathlib import Path
from typing import List, Dict, Any, Union
import datetime


class AESJsonEncoder(json.JSONEncoder):
    """
    Custom JSON encoder to handle non-standard types like Path, datetime, and Mock objects.
    """
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        # Handle Mock objects (specifically for testing environments)
        if hasattr(obj, "__class__") and "Mock" in obj.__class__.__name__:
            return f"<Mock name={getattr(obj, '_mock_name', 'None')}>"
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)


def load_events(path: Union[Path, str]) -> List[Dict[Any, Any]]:
    """
    Loads events from a trace file. Supports both JSONL and standard JSON array formats.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Trace file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
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
    """Helper to reconstruct results structure from JSONL events."""
    from .triage import TriageEngine
    results_map = {}
    for event in events:
        task_id = event.get("task_id", "unknown")
        ev_type = event.get("event")
        if task_id not in results_map:
            results_map[task_id] = {"task_id": task_id, "metrics": [], "conversation_history": [], "triage_tag": "SUCCESS"}
        res = results_map[task_id]
        if ev_type == "evaluation":
            res["metrics"].append({"metric": event.get("metric"), "score": event.get("value"), "threshold": event.get("threshold", 0.5), "success": event.get("success", False)})
        elif ev_type in ["prompt", "agent_response", "tool_result"]:
            role = "agent" if ev_type == "agent_response" else "user"
            content = event.get("content") or {"action": event.get("tool"), "status": event.get("status")}
            res["conversation_history"].append({"role": role, "content": content})
    final_results = list(results_map.values())
    TriageEngine.apply_triage(final_results)
    return final_results
