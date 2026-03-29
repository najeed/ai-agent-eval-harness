"""
cleaner.py

Utility for cleaning up old trace files and logs.
"""

import os
import time
from pathlib import Path

def cleanup_traces(dir_path: str = "runs", days: int = 7, force: bool = False):
    """
    Removes run traces older than the specified number of days.
    """
    path = Path(dir_path)
    if not path.exists():
        return

    now = time.time()
    cutoff = now - (days * 86400)

    for f in path.glob("*.jsonl"):
        if f.stat().st_mtime < cutoff:
            if force:
                f.unlink()
            else:
                print(f"[CLEANUP] Would remove old trace: {f.name}")
