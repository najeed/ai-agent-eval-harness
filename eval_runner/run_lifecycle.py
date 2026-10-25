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

import logging
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class RunLifecycleState(StrEnum):
    OPEN = "OPEN"
    PAUSED_FOR_APPROVAL = "PAUSED_FOR_APPROVAL"
    FINALIZING = "FINALIZING"
    SEALED = "SEALED"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"


class TraceClosedError(RuntimeError):
    """Raised when a trace write is attempted on a run in FINALIZING, SEALED, or INVALID state."""


class RunSuspendedForApproval(InterruptedError):
    """
    Authoritative suspension signal raised when a run enters durable HITL approval gate.
    Bypasses standard node-level failure handling to preserve PAUSED_FOR_APPROVAL state.
    Inherits from InterruptedError for backward compatibility with direct callers.
    """

    def __init__(
        self,
        run_id: str,
        task_id: str,
        approval_token: str,
        turn_index: int = 0,
        checkpoint_id: str | None = None,
        prompt: str = "",
        checkpoint: dict[str, Any] | None = None,
        action_payload: dict[str, Any] | None = None,
    ):
        super().__init__(
            f"Run '{run_id}' paused for approval on task '{task_id}'. Token: {approval_token}"
        )
        self.run_id = run_id
        self.task_id = task_id
        self.approval_token = approval_token
        self.turn_index = turn_index
        self.checkpoint_id = checkpoint_id
        self.prompt = prompt
        self.checkpoint = checkpoint or {}
        self.action_payload = action_payload or {}


_VALID_TRANSITIONS: dict[RunLifecycleState, set[RunLifecycleState]] = {
    RunLifecycleState.OPEN: {
        RunLifecycleState.OPEN,
        RunLifecycleState.PAUSED_FOR_APPROVAL,
        RunLifecycleState.FINALIZING,
    },
    RunLifecycleState.PAUSED_FOR_APPROVAL: {
        RunLifecycleState.PAUSED_FOR_APPROVAL,
        RunLifecycleState.OPEN,
        RunLifecycleState.FINALIZING,
        RunLifecycleState.SEALED,
    },
    RunLifecycleState.FINALIZING: {RunLifecycleState.FINALIZING, RunLifecycleState.SEALED},
    RunLifecycleState.SEALED: {RunLifecycleState.SEALED},
    RunLifecycleState.UNKNOWN: set(),
    RunLifecycleState.INVALID: set(),
}


def _lifecycle_provider(run_store: Any | None) -> Any:
    """Return the execution owner's authoritative storage provider."""
    if run_store is None:
        raise ValueError("RunStorageProvider is required for lifecycle operations.")
    return run_store


def get_run_lifecycle_state(
    run_id: str,
    *,
    run_store: Any,
    context: dict[str, Any] | None = None,
) -> RunLifecycleState:
    """
    Returns the authoritative lifecycle state from the active storage provider.

    The execution owner supplies ``run_store``.
    """
    if not run_id or run_id == "unknown":
        return RunLifecycleState.OPEN

    provider = _lifecycle_provider(run_store)
    record = provider.get_run(run_id, context=context)
    if record is None or not isinstance(record, Mapping):
        return RunLifecycleState.OPEN
    state = str(record.get("lifecycle") or record.get("status") or "OPEN").upper()
    if state in ("PENDING", "RUNNING", "STARTED", "QUEUED"):
        return RunLifecycleState.OPEN
    # Execution completion is not a certificate seal.  Backends retain their
    # user-facing terminal status (COMPLETED/FAILED/etc.) in the run record,
    # while lifecycle consumers must treat that evidence as closed pending the
    # provider-owned certification transaction.
    if state in ("COMPLETED", "FAILED", "ABORTED", "CANCELLED"):
        return RunLifecycleState.FINALIZING
    if state in RunLifecycleState._value2member_map_:
        return RunLifecycleState(state)
    return RunLifecycleState.INVALID


def transition_run_lifecycle(
    run_id: str,
    target_state: RunLifecycleState | str,
    metadata: dict[str, Any] | None = None,
    *,
    run_store: Any,
    context: dict[str, Any] | None = None,
) -> RunLifecycleState:
    """
    Transitions the run's lifecycle strictly forward: OPEN → FINALIZING → SEALED.
    Raises ValueError if an illegal or backward transition is attempted.

    The execution owner supplies ``run_store``.
    """
    if not run_id or run_id == "unknown":
        return RunLifecycleState.OPEN

    target = RunLifecycleState(target_state) if isinstance(target_state, str) else target_state
    current = get_run_lifecycle_state(run_id, run_store=run_store, context=context)

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

    provider = _lifecycle_provider(run_store)
    if not provider.update_run_status(run_id, target.value, metadata, context=context):
        raise RuntimeError(f"RunStorageProvider rejected lifecycle update for '{run_id}'.")

    return target


def can_write_trace(
    run_id: str,
    *,
    run_store: Any,
    context: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """
    Returns (can_write, reason) for a trace writer.
    Writes are rejected if the run is in FINALIZING, SEALED, or INVALID state,
    or if an exclusive certification lock is active.

    The execution owner supplies ``run_store``.
    """
    if not run_id or run_id == "unknown":
        return True, ""

    state = get_run_lifecycle_state(run_id, run_store=run_store, context=context)
    if state == RunLifecycleState.PAUSED_FOR_APPROVAL:
        return (
            False,
            (
                f"Run '{run_id}' is in PAUSED_FOR_APPROVAL state; "
                "trace writes prohibited until resumed."
            ),
        )
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

    if PerRunCertificationLock.is_locked(run_id, run_store=run_store, context=context):
        return False, f"Run '{run_id}' is locked for certification; concurrent writes prohibited."

    return True, ""


def assert_can_write_trace(
    run_id: str,
    *,
    run_store: Any,
    context: dict[str, Any] | None = None,
) -> None:
    """Raises TraceClosedError if trace writing is currently prohibited on the run."""
    allowed, reason = can_write_trace(run_id, run_store=run_store, context=context)
    if not allowed:
        raise TraceClosedError(reason)


def rollback_run_lifecycle_to_open(
    run_id: str,
    *,
    run_store: Any,
    context: dict[str, Any] | None = None,
) -> RunLifecycleState:
    """
    Rolls back run lifecycle from FINALIZING back to OPEN if certification failed prior to SEALED.
    SEALED runs are immutable and cannot be rolled back.
    """
    if not run_id or run_id == "unknown":
        return RunLifecycleState.OPEN

    current = get_run_lifecycle_state(run_id, run_store=run_store, context=context)
    if current == RunLifecycleState.SEALED:
        raise ValueError(f"Cannot rollback lifecycle for SEALED run '{run_id}'.")

    provider = _lifecycle_provider(run_store)
    if not provider.update_run_status(run_id, RunLifecycleState.OPEN.value, context=context):
        raise RuntimeError(f"RunStorageProvider rejected lifecycle rollback for '{run_id}'.")

    return RunLifecycleState.OPEN


__all__ = [
    "RunLifecycleState",
    "RunSuspendedForApproval",
    "TraceClosedError",
    "assert_can_write_trace",
    "can_write_trace",
    "get_run_lifecycle_state",
    "rollback_run_lifecycle_to_open",
    "transition_run_lifecycle",
]
