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
    """Helper to reconstruct results structure from JSONL events."""
    from .triage import TriageEngine

    results_map = {}
    for event in events:
        task_id = event.get("task_id", "unknown")
        ev_type = event.get("event")
        if task_id not in results_map:
            results_map[task_id] = {
                "task_id": task_id,
                "metrics": [],
                "conversation_history": [],
                "triage_tag": "SUCCESS",
            }
        res = results_map[task_id]
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
            res["conversation_history"].append({"role": role, "content": content})
    final_results = list(results_map.values())
    TriageEngine.apply_triage(final_results)
    return final_results


def resolve_trace_path(run_id: str, allow_master_recovery: bool = True) -> Path | None:
    """
    Authoritative trace resolver for AgentV.
    Resolves the canonical path to a run's trace log across vaults, direct files,
    and master-log projection.
    """
    if not run_id or not isinstance(run_id, str):
        return None
    import re

    from . import config
    from .utils import is_path_safe

    if not re.match(r"^[a-zA-Z0-9_\-]+$", run_id):
        return None

    base_dir = Path(config.RUN_LOG_DIR).resolve()
    candidates = [
        base_dir / run_id / "run.jsonl",
        base_dir / run_id / f"{run_id}.jsonl",
        base_dir / f"{run_id}.jsonl",
        base_dir / run_id,
    ]
    for c in candidates:
        if c.exists() and c.is_file() and is_path_safe(c, base_dir):
            return c

    # Fallback / Recovery from master log (Defect 3)
    if allow_master_recovery:
        master_log = base_dir / "run.jsonl"
        if master_log.exists() and master_log.is_file() and is_path_safe(master_log, base_dir):
            matching_lines: list[str] = []
            try:
                with open(master_log, encoding="utf-8") as f:
                    for line in f:
                        line_str = line.strip()
                        if not line_str:
                            continue
                        try:
                            ev = json.loads(line_str)
                            if ev.get("run_id") == run_id:
                                matching_lines.append(line_str)
                        except Exception:
                            continue
            except Exception as read_err:
                import logging

                logging.getLogger(__name__).debug(
                    "Error reading master log for recovery: %s", read_err
                )

            if matching_lines:
                vault_dir = base_dir / run_id
                vault_dir.mkdir(parents=True, exist_ok=True)
                vault_trace = vault_dir / "run.jsonl"
                try:
                    with open(vault_trace, "w", encoding="utf-8") as out:
                        out.write("\n".join(matching_lines) + "\n")
                    return vault_trace
                except Exception as write_err:
                    import logging

                    logging.getLogger(__name__).error(
                        "Failed projecting master log trace: %s", write_err
                    )

    return None
