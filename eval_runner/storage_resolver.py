"""
Resolution of the active authoritative run storage provider (delegated to agentv_runtime.discovery).
"""

from __future__ import annotations

from pathlib import Path

from agentv_runtime.discovery import (
    reset_extensions,
    set_extension,
)
from agentv_runtime.interfaces import RunStorageProvider


def resolve_run_storage_provider() -> RunStorageProvider:
    """Return the active provider, discovering it once when none is configured."""
    from eval_runner.runtime_services import resolve_run_store

    return resolve_run_store()


def compose_local_run_storage_provider(log_dir: Path) -> RunStorageProvider:
    """Construct the OSS local adapter at the composition boundary only.

    Kernel lifecycle code calls this solely for an explicitly supplied local
    test/reference scope; it never imports a reference implementation.
    """
    from eval_runner.runtime_services import compose_local_run_store

    return compose_local_run_store(log_dir)


def set_active_run_storage_provider(provider: RunStorageProvider) -> None:
    """Sets the process-wide authoritative provider used by every runtime subsystem."""
    if not isinstance(provider, RunStorageProvider):
        raise TypeError("Active run storage provider must implement RunStorageProvider")
    set_extension("run_stores", provider)


def reset_run_storage_provider() -> None:
    """Clears the active provider; intended for isolated tests and controlled reconfiguration."""
    reset_extensions()


__all__ = [
    "resolve_run_storage_provider",
    "compose_local_run_storage_provider",
    "set_active_run_storage_provider",
    "reset_run_storage_provider",
]
