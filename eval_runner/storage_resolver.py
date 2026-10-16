"""
Resolution of the active authoritative run storage provider (delegated to agentv_runtime.discovery).
"""

from __future__ import annotations

from agentv_runtime.discovery import (
    reset_extensions,
    resolve_extension,
    set_extension,
)
from agentv_runtime.interfaces import RunStorageProvider
from eval_runner.reference.local_run_store import LocalFileRunStore


def resolve_run_storage_provider() -> RunStorageProvider:
    """Return the active provider, discovering it once when none is configured."""
    return resolve_extension(
        "run_stores",
        env_var="AGENTV_RUN_STORE_PROVIDER",
        default_factory=LocalFileRunStore,
    )


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
    "set_active_run_storage_provider",
    "reset_run_storage_provider",
]
