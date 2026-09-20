"""
eval_runner.run_lifecycle — Authoritative Per-Run Lifecycle Boundary (AgentV v2.0.0).

Enforces the single authoritative lifecycle state machine:
    OPEN → FINALIZING → SEALED

Invariants:
1. State transitions are strictly monotonic and forward-only.
2. All trace writers must reject writes after transitioning to FINALIZING.
3. Once SEALED, the evidence vault is cryptographically frozen and immutable.
"""

from __future__ import annotations

import json
import logging
from enum import StrEnum
from pathlib import Path
from typing import Any

from eval_runner import config

logger = logging.getLogger(__name__)


class RunLifecycleState(StrEnum):
    OPEN = "OPEN"
    FINALIZING = "FINALIZING"
    SEALED = "SEALED"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"


class TraceClosedError(RuntimeError):
    """Raised when a trace write is attempted on a run in FINALIZING, SEALED, or INVALID state."""


_VALID_TRANSITIONS: dict[RunLifecycleState, set[RunLifecycleState]] = {
    RunLifecycleState.OPEN: {
        RunLifecycleState.OPEN,
        RunLifecycleState.FINALIZING,
    },
    RunLifecycleState.FINALIZING: {RunLifecycleState.FINALIZING, RunLifecycleState.SEALED},
    RunLifecycleState.SEALED: {RunLifecycleState.SEALED},
    RunLifecycleState.UNKNOWN: set(),
    RunLifecycleState.INVALID: set(),
}


def _lifecycle_file_path(run_id: str, log_dir: Path | None = None) -> Path:
    base = log_dir if log_dir is not None else config.RUN_LOG_DIR
    return base / run_id / ".run_lifecycle"


def get_run_lifecycle_state(run_id: str, log_dir: Path | None = None) -> RunLifecycleState:
    """
    Returns the authoritative lifecycle state of the given run.
    Fails closed to INVALID if the lifecycle marker exists but is corrupted or unparseable.

    ``log_dir`` scopes the filesystem probe to a specific directory. When None (the
    default) the global ``config.RUN_LOG_DIR`` is used, which is the production path.
    """
    if not run_id or run_id == "unknown":
        return RunLifecycleState.OPEN

    lf_path = _lifecycle_file_path(run_id, log_dir)
    if lf_path.exists():
        if not lf_path.is_file():
            return RunLifecycleState.INVALID
        try:
            content = lf_path.read_text(encoding="utf-8").strip()
            if not content:
                return RunLifecycleState.INVALID
            try:
                data = json.loads(content)
                if not isinstance(data, dict):
                    return RunLifecycleState.INVALID
                state_str = str(data.get("state", "")).upper()
            except Exception:
                state_str = content.upper()
            if state_str in RunLifecycleState._value2member_map_:
                return RunLifecycleState(state_str)
            return RunLifecycleState.INVALID
        except OSError as e:
            logger.error("Failed reading lifecycle marker for %s: %s", run_id, e)
            return RunLifecycleState.INVALID

    # Check fallback markers: if sealed artifact exists, state is SEALED
    base = log_dir if log_dir is not None else config.RUN_LOG_DIR
    vault_dir = base / run_id
    if vault_dir.is_dir():
        if (vault_dir / ".sealed").exists() or (vault_dir / "trace_seal.json").exists():
            return RunLifecycleState.SEALED

    return RunLifecycleState.OPEN


def transition_run_lifecycle(
    run_id: str,
    target_state: RunLifecycleState | str,
    metadata: dict[str, Any] | None = None,
    log_dir: Path | None = None,
) -> RunLifecycleState:
    """
    Transitions the run's lifecycle strictly forward: OPEN → FINALIZING → SEALED.
    Raises ValueError if an illegal or backward transition is attempted.

    ``log_dir`` scopes the lifecycle marker to a specific directory. When None (the
    default) the global ``config.RUN_LOG_DIR`` is used.
    """
    if not run_id or run_id == "unknown":
        return RunLifecycleState.OPEN

    target = RunLifecycleState(target_state) if isinstance(target_state, str) else target_state
    current = get_run_lifecycle_state(run_id, log_dir)

    if current in (RunLifecycleState.INVALID, RunLifecycleState.UNKNOWN):
        raise ValueError(
            f"IllegalLifecycleTransition: Cannot transition run '{run_id}' "
            f"from corrupted/untrusted state '{current.value}'."
        )

    if target not in _VALID_TRANSITIONS[current]:
        raise ValueError(
            f"IllegalLifecycleTransition: Cannot transition run '{run_id}' "
            f"from '{current.value}' to '{target.value}' (must be monotonic forward)."
        )

    base = log_dir if log_dir is not None else config.RUN_LOG_DIR
    vault_dir = base / run_id
    vault_dir.mkdir(parents=True, exist_ok=True)
    lf_path = _lifecycle_file_path(run_id, log_dir)

    payload = {
        "run_id": run_id,
        "state": target.value,
        "updated_at": config.now_iso() if hasattr(config, "now_iso") else "",
        "metadata": metadata or {},
    }
    tmp_path = vault_dir / f".run_lifecycle.tmp_{run_id}"
    try:
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.replace(lf_path)
    except OSError as e:
        logger.error("Failed writing lifecycle marker for %s: %s", run_id, e)
        raise

    if target == RunLifecycleState.SEALED:
        sealed_marker = vault_dir / ".sealed"
        if not sealed_marker.exists():
            try:
                sealed_marker.write_text("SEALED", encoding="utf-8")
            except OSError as seal_err:
                logger.debug("Failed writing secondary .sealed marker for %s: %s", run_id, seal_err)

    return target


def can_write_trace(run_id: str, log_dir: Path | None = None) -> tuple[bool, str]:
    """
    Returns (can_write, reason) for a trace writer.
    Writes are rejected if the run is in FINALIZING, SEALED, or INVALID state,
    or if an exclusive certification lock is active.

    ``log_dir`` scopes the filesystem probe. When None (the default) the global
    ``config.RUN_LOG_DIR`` is used.
    """
    if not run_id or run_id == "unknown":
        return True, ""

    state = get_run_lifecycle_state(run_id, log_dir)
    if state == RunLifecycleState.FINALIZING:
        return False, f"Run '{run_id}' is in FINALIZING state; trace writes prohibited."
    if state == RunLifecycleState.SEALED:
        return False, f"Run '{run_id}' is in SEALED state; trace is cryptographically immutable."
    if state == RunLifecycleState.INVALID:
        return (
            False,
            f"Run '{run_id}' has an INVALID/corrupted lifecycle marker; writes prohibited.",
        )
    if state == RunLifecycleState.UNKNOWN:
        return False, f"Run '{run_id}' has UNKNOWN lifecycle state; writes prohibited."

    from eval_runner.certification_lock import PerRunCertificationLock

    if PerRunCertificationLock.is_locked(run_id):
        return False, f"Run '{run_id}' is locked for certification; concurrent writes prohibited."

    return True, ""


def assert_can_write_trace(run_id: str, log_dir: Path | None = None) -> None:
    """Raises TraceClosedError if trace writing is currently prohibited on the run."""
    allowed, reason = can_write_trace(run_id, log_dir)
    if not allowed:
        raise TraceClosedError(reason)


def rollback_run_lifecycle_to_open(run_id: str, log_dir: Path | None = None) -> RunLifecycleState:
    """
    Rolls back run lifecycle from FINALIZING back to OPEN if certification failed prior to SEALED.
    SEALED runs are immutable and cannot be rolled back.
    """
    if not run_id or run_id == "unknown":
        return RunLifecycleState.OPEN

    current = get_run_lifecycle_state(run_id, log_dir)
    if current == RunLifecycleState.SEALED:
        raise ValueError(f"Cannot rollback lifecycle for SEALED run '{run_id}'.")

    lf_path = _lifecycle_file_path(run_id, log_dir)
    try:
        lf_path.unlink(missing_ok=True)
    except OSError as e:
        logger.debug("Failed unlinking lifecycle marker during rollback: %s", e)

    return RunLifecycleState.OPEN


__all__ = [
    "RunLifecycleState",
    "TraceClosedError",
    "assert_can_write_trace",
    "can_write_trace",
    "get_run_lifecycle_state",
    "rollback_run_lifecycle_to_open",
    "transition_run_lifecycle",
]
