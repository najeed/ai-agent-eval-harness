"""Provider-owned retention utilities for evaluation runs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any


def _created_at(record: dict[str, Any]) -> datetime | None:
    value = record.get("created_at") or record.get("started_at") or record.get("timestamp")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def cleanup_traces(
    *, run_store: Any, days: int = 7, force: bool = False, context: dict[str, Any] | None = None
) -> list[str]:
    """Delete expired provider-owned runs; callers never enumerate trace files."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    affected: list[str] = []
    for record in run_store.list_runs(limit=100_000, context=context):
        run_id = record.get("run_id") or record.get("id")
        created = _created_at(record)
        if not isinstance(run_id, str) or created is None or created >= cutoff:
            continue
        affected.append(run_id)
        if force:
            run_store.delete_run(run_id, context=context)
        else:
            print(f"[CLEANUP] Would remove expired provider run: {run_id}")
    return affected
