"""Durable, scope-bearing registration records for asynchronously accepted runs."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentv_runtime.scope import ScopeToken
from eval_runner import config

_CONTEXT_FIELDS = ("org_id", "tenant_id", "workspace_id", "active_environment")


def run_index_path(run_id: str, root: Path | None = None) -> Path:
    """Return the control-plane index location, outside the evidence vault."""
    if not run_id or Path(run_id).name != run_id:
        raise ValueError("run_id must be a single safe identifier")
    # A run vault's mere existence is a collision signal to the runner.  The
    # asynchronous registration record must therefore never reserve that
    # directory before execution has claimed it.
    return (root or config.RUN_LOG_DIR) / ".index" / f"{run_id}.json"


def read_run_index(run_id: str, root: Path | None = None) -> dict[str, Any] | None:
    path = run_index_path(run_id, root)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def create_run_index(
    *,
    run_id: str,
    context: Mapping[str, Any] | None,
    scenario_id: str,
    root: Path | None = None,
) -> dict[str, Any]:
    """Atomically register an accepted run before dispatching asynchronous work."""
    if context is None or not isinstance(context, Mapping):
        raise ValueError("run context must be a valid mapping")

    is_empty_tuple = all(context.get(k) == "" for k in _CONTEXT_FIELDS)
    if not is_empty_tuple and any(k in context for k in _CONTEXT_FIELDS):
        if any(
            not isinstance(context.get(field), str) or not context.get(field)
            for field in _CONTEXT_FIELDS
        ):
            raise ValueError("run context must contain the complete verified context tuple")

    path = run_index_path(run_id, root)
    if path.exists():
        raise ValueError(f"run index already exists for {run_id}")

    token = ScopeToken.from_tags(context)
    record = {
        "run_id": run_id,
        "status": "PENDING",
        "scenario_id": scenario_id,
        "created_at": datetime.now(UTC).isoformat(),
        "scope_digest": token.digest,
        "context": token.tags,
    }
    _write_atomic(path, record)
    return record


def update_run_index_status(
    run_id: str, status: str, root: Path | None = None
) -> dict[str, Any] | None:
    """Update lifecycle state without ever replacing the immutable scope tuple."""
    record = read_run_index(run_id, root)
    if record is None:
        return None
    record["status"] = status
    record["updated_at"] = datetime.now(UTC).isoformat()
    _write_atomic(run_index_path(run_id, root), record)
    return record
