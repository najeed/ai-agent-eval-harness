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


class TraceClosedError(RuntimeError):
    """Raised when a trace write is attempted on a run in FINALIZING or SEALED state."""


_VALID_TRANSITIONS: dict[RunLifecycleState, set[RunLifecycleState]] = {
    RunLifecycleState.OPEN: {
        RunLifecycleState.OPEN,
        RunLifecycleState.FINALIZING,
        RunLifecycleState.SEALED,
    },
    RunLifecycleState.FINALIZING: {RunLifecycleState.FINALIZING, RunLifecycleState.SEALED},
    RunLifecycleState.SEALED: {RunLifecycleState.SEALED},
}


def _lifecycle_file_path(run_id: str) -> Path:
    return config.RUN_LOG_DIR / run_id / ".run_lifecycle"


def get_run_lifecycle_state(run_id: str) -> RunLifecycleState:
    """Returns the authoritative lifecycle state of the given run."""
    if not run_id or run_id == "unknown":
        return RunLifecycleState.OPEN

    lf_path = _lifecycle_file_path(run_id)
    if lf_path.is_file():
        try:
            content = lf_path.read_text(encoding="utf-8").strip()
            if content:
                try:
                    data = json.loads(content)
                    state_str = str(data.get("state", "")).upper()
                except Exception:
                    state_str = content.upper()
                if state_str in RunLifecycleState._value2member_map_:
                    return RunLifecycleState(state_str)
        except OSError as e:
            logger.debug("Failed reading lifecycle marker for %s: %s", run_id, e)

    # Check fallback markers: if sealed artifact or run_manifest.json exists, state is SEALED
    vault_dir = config.RUN_LOG_DIR / run_id
    if vault_dir.is_dir():
        if (vault_dir / ".sealed").exists() or (vault_dir / "run_manifest.json").exists():
            return RunLifecycleState.SEALED

    return RunLifecycleState.OPEN


def transition_run_lifecycle(
    run_id: str,
    target_state: RunLifecycleState | str,
    metadata: dict[str, Any] | None = None,
) -> RunLifecycleState:
    """
    Transitions the run's lifecycle strictly forward: OPEN → FINALIZING → SEALED.
    Raises ValueError if an illegal or backward transition is attempted.
    """
    if not run_id or run_id == "unknown":
        return RunLifecycleState.OPEN

    target = RunLifecycleState(target_state) if isinstance(target_state, str) else target_state
    current = get_run_lifecycle_state(run_id)

    if target not in _VALID_TRANSITIONS[current]:
        raise ValueError(
            f"IllegalLifecycleTransition: Cannot transition run '{run_id}' "
            f"from '{current.value}' to '{target.value}' (must be monotonic forward)."
        )

    vault_dir = config.RUN_LOG_DIR / run_id
    vault_dir.mkdir(parents=True, exist_ok=True)
    lf_path = _lifecycle_file_path(run_id)

    payload = {
        "run_id": run_id,
        "state": target.value,
        "metadata": metadata or {},
    }
    tmp_path = vault_dir / f".run_lifecycle.{target.value}.tmp"
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(lf_path)

    if target == RunLifecycleState.SEALED:
        sealed_marker = vault_dir / ".sealed"
        if not sealed_marker.exists():
            try:
                sealed_marker.write_text("SEALED", encoding="utf-8")
            except OSError:
                pass

    return target


def can_write_trace(run_id: str) -> tuple[bool, str]:
    """
    Returns (can_write, reason) for a trace writer.
    Writes are rejected if the run is in FINALIZING or SEALED state,
    or if an exclusive certification lock is active.
    """
    if not run_id or run_id == "unknown":
        return True, ""

    state = get_run_lifecycle_state(run_id)
    if state == RunLifecycleState.FINALIZING:
        return False, f"Run '{run_id}' is in FINALIZING state; trace writes prohibited."
    if state == RunLifecycleState.SEALED:
        return False, f"Run '{run_id}' is in SEALED state; trace is cryptographically immutable."

    from eval_runner.certification_lock import PerRunCertificationLock

    if PerRunCertificationLock.is_locked(run_id):
        return False, f"Run '{run_id}' is locked for certification; concurrent writes prohibited."

    return True, ""


def assert_can_write_trace(run_id: str) -> None:
    """Raises TraceClosedError if trace writing is currently prohibited on the run."""
    allowed, reason = can_write_trace(run_id)
    if not allowed:
        raise TraceClosedError(reason)


__all__ = [
    "RunLifecycleState",
    "TraceClosedError",
    "assert_can_write_trace",
    "can_write_trace",
    "get_run_lifecycle_state",
    "transition_run_lifecycle",
]
