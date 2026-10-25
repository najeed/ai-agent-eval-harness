"""Runtime composition helpers for pluggable services.

Core callers resolve contracts here; reference implementations are selected only
as the local development fallback at the composition boundary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentv_runtime.discovery import get_registered_extension, resolve_extension
from agentv_runtime.interfaces import (
    ApprovalStore,
    ArtifactStore,
    AuthorizationBackend,
    CatalogStore,
    CheckpointStore,
    ExecutionBackend,
    LeaderboardStore,
    PolicyEvaluator,
    RunStorageProvider,
    SigningBackend,
)

# Reference adapters are intentionally re-exported only from this composition
# boundary. Core modules consume these names here, never from ``reference``.
from eval_runner.reference.field_policy import BasicFieldPolicyEvaluator
from eval_runner.reference.local_artifact import LocalFileArtifactStore
from eval_runner.reference.local_catalog import LocalFileCatalogStore
from eval_runner.reference.local_leaderboard import LocalLeaderboardStore
from eval_runner.reference.signing import LocalEd25519SigningBackend, NullSigningBackend
from eval_runner.reference.sqlite_checkpoint import SQLiteCheckpointStore


def resolve_run_store(*, explicit: RunStorageProvider | None = None) -> RunStorageProvider:
    """Resolve the run-storage contract at the runtime composition boundary."""
    if explicit is not None:
        return explicit

    def _local_default() -> RunStorageProvider:
        from eval_runner.reference.local_run_store import LocalFileRunStore

        return LocalFileRunStore()

    return resolve_extension(
        "run_stores", env_var="AGENTV_RUN_STORE_PROVIDER", default_factory=_local_default
    )


def compose_local_run_store(log_dir: str | Path) -> RunStorageProvider:
    """Explicit local-reference composition for tests and local tooling only."""
    from eval_runner.reference.local_run_store import LocalFileRunStore

    return LocalFileRunStore(Path(log_dir))


def resolve_artifact_store(
    *, explicit: ArtifactStore | None = None, default_factory: Any | None = None
) -> ArtifactStore:
    """Resolve artifact storage at the runtime composition boundary."""
    if explicit is not None:
        return explicit

    def _local_default() -> ArtifactStore:
        if default_factory is not None:
            return default_factory()
        from eval_runner.reference.local_artifact import LocalFileArtifactStore

        return LocalFileArtifactStore()

    return resolve_extension("artifact_stores", default_factory=_local_default)


def compose_local_artifact_store(base_dir: str | Path) -> ArtifactStore:
    """Explicit local-reference composition for isolated recorder/test scopes."""
    return LocalFileArtifactStore(base_dir=base_dir)


def resolve_signing_backend(*, explicit: SigningBackend | None = None) -> SigningBackend:
    """Resolve signing at the runtime composition boundary."""

    def _local_default() -> SigningBackend:
        return LocalEd25519SigningBackend()

    return resolve_extension("signing_backends", explicit=explicit, default_factory=_local_default)


def resolve_plugin_registry() -> Any:
    """Return the canonical multi-load plugin registry."""
    registry = get_registered_extension("plugins")
    if registry is None:
        # Importing a cached module does not replay its registration side
        # effect after a test reset.  Re-register the singleton
        # explicitly so discovery remains the single source of truth.
        from agentv_runtime.discovery import set_extension
        from eval_runner.plugins import manager

        set_extension("plugins", manager)
        registry = manager
    if registry is None:
        raise RuntimeError("Plugin registry was not registered with runtime discovery.")
    return registry


def resolve_catalog_store(
    *, explicit: CatalogStore | None = None, base_dir: str | Path | None = None
) -> CatalogStore:
    def _local_default() -> CatalogStore:
        return (
            LocalFileCatalogStore(base_dir=base_dir)
            if base_dir is not None
            else LocalFileCatalogStore()
        )

    return resolve_extension("catalog_stores", explicit=explicit, default_factory=_local_default)


def resolve_checkpoint_store(*, explicit: CheckpointStore | None = None) -> CheckpointStore:
    return resolve_extension(
        "checkpoint_stores", explicit=explicit, default_factory=SQLiteCheckpointStore
    )


def resolve_leaderboard_store(*, explicit: LeaderboardStore | None = None) -> LeaderboardStore:
    return resolve_extension(
        "leaderboard_stores", explicit=explicit, default_factory=LocalLeaderboardStore
    )


def resolve_policy_evaluator(*, explicit: PolicyEvaluator | None = None) -> PolicyEvaluator:
    return resolve_extension(
        "policy_evaluators", explicit=explicit, default_factory=BasicFieldPolicyEvaluator
    )


def resolve_approval_store(
    *,
    explicit: ApprovalStore | None = None,
    store_type: str | None = None,
    base_dir: str | Path | None = None,
) -> ApprovalStore:
    """Resolve the active approval-store contract or an explicitly requested local store."""
    if explicit is not None:
        return explicit

    # ``store_type`` and ``base_dir`` are explicit CLI composition choices.
    if store_type is not None or base_dir is not None:
        from eval_runner.reference.approval_store import FileApprovalStore, SQLiteApprovalStore

        if store_type == "sqlite":
            return (
                SQLiteApprovalStore(db_path=base_dir)
                if base_dir is not None
                else SQLiteApprovalStore()
            )
        return FileApprovalStore(base_dir=base_dir)

    def _local_default() -> ApprovalStore:
        from eval_runner.reference.approval_store import get_default_approval_store

        return get_default_approval_store()

    return resolve_extension("approval_stores", default_factory=_local_default)


def resolve_execution_backend(*, explicit: ExecutionBackend | None = None) -> ExecutionBackend:
    """Resolve the active execution backend through the canonical extension family."""

    def _local_default() -> ExecutionBackend:
        from eval_runner.reference.inprocess_backend import get_execution_backend

        return get_execution_backend()

    return resolve_extension(
        "execution_backends", explicit=explicit, default_factory=_local_default
    )


def resolve_authorization_backend(
    *, explicit: AuthorizationBackend | None = None, master_key: str | None = None
) -> AuthorizationBackend:
    """Resolve the active authorization contract with the OSS backend as fallback."""

    def _local_default() -> AuthorizationBackend:
        from eval_runner.reference.auth import SimpleAPIKeyAuthBackend

        return SimpleAPIKeyAuthBackend(master_key=master_key)

    return resolve_extension(
        "authorization_backends", explicit=explicit, default_factory=_local_default
    )


__all__ = [
    "compose_local_run_store",
    "compose_local_artifact_store",
    "BasicFieldPolicyEvaluator",
    "LocalEd25519SigningBackend",
    "LocalFileCatalogStore",
    "LocalFileArtifactStore",
    "LocalLeaderboardStore",
    "NullSigningBackend",
    "resolve_artifact_store",
    "resolve_approval_store",
    "resolve_authorization_backend",
    "resolve_execution_backend",
    "resolve_run_store",
    "resolve_plugin_registry",
    "resolve_catalog_store",
    "resolve_checkpoint_store",
    "resolve_leaderboard_store",
    "resolve_policy_evaluator",
    "resolve_signing_backend",
    "SQLiteCheckpointStore",
]
