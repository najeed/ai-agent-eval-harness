import json
from pathlib import Path
from typing import List, Dict, Any, Union

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
