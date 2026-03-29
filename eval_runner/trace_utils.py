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
