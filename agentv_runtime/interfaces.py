"""
agentv_runtime.interfaces
Authoritative Public Extension Families and Architecture Contracts (v2.0.0).

Neutral contract layer defining the 6 Extension Families and 3 Storage Interfaces
for AgentV OS Runtime and Control Plane seams.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

# ==============================================================================
# 1. ExecutionBackend Contract
# ==============================================================================


class ExecutionBackend(ABC):
    """
    Neutral abstraction for evaluation run execution.
    OSS Reference: InProcessExecutionBackend
    Control Plane / Enterprise: TemporalExecutionBackend / KubernetesExecutionBackend
    """

    @abstractmethod
    def submit(self, run_id: str, scenario_data: dict[str, Any], **kwargs: Any) -> Any:
        """Submits an evaluation run for execution."""
        raise NotImplementedError

    @abstractmethod
    def status(self, run_id: str) -> dict[str, Any]:
        """Returns the current execution status and metadata for a run."""
        raise NotImplementedError

    @abstractmethod
    def cancel(self, run_id: str, reason: str | None = None) -> bool:
        """Cancels an in-progress evaluation run."""
        raise NotImplementedError

    @abstractmethod
    def resume(self, run_id: str, resumption_token: str | None = None, **kwargs: Any) -> Any:
        """Resumes a paused or checkpointed evaluation run."""
        raise NotImplementedError


# ==============================================================================
# 2. CheckpointStore Contract
# ==============================================================================


class CheckpointStore(ABC):
    """
    Abstraction for persisting and loading evaluation session checkpoints.
    OSS Reference: SQLiteCheckpointStore / LocalFileCheckpointStore
    Control Plane / Enterprise: PostgresCheckpointStore / DynamoDBCheckpointStore
    """

    @abstractmethod
    def save(
        self,
        run_id: str,
        checkpoint_id: str,
        state: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persists a session state checkpoint. Returns the checkpoint ID or URI."""
        raise NotImplementedError

    @abstractmethod
    def load(self, run_id: str, checkpoint_id: str | None = None) -> dict[str, Any] | None:
        """Loads the latest or specific session checkpoint state for a run."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, run_id: str, checkpoint_id: str | None = None) -> bool:
        """Deletes checkpoints for a given run."""
        raise NotImplementedError

    @abstractmethod
    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        """Lists metadata for all checkpoints recorded for a run."""
        raise NotImplementedError


# ==============================================================================
# 3. SigningBackend Contract
# ==============================================================================


class SigningBackend(ABC):
    """
    Abstraction for cryptographic signing and signature verification of evaluation traces.
    OSS Reference: LocalEd25519SigningBackend
    Control Plane / Enterprise: KMSSigningBackend / VaultSigningBackend
    """

    @abstractmethod
    def sign_payload(
        self, payload: bytes, key_identifier: str | Path | Any = None, **kwargs: Any
    ) -> str | dict[str, Any]:
        """
        Signs a raw bytes payload and returns a cryptographic signature string or metadata dict.
        """
        raise NotImplementedError

    @abstractmethod
    def verify_signature(
        self,
        payload: bytes,
        signature: str | dict[str, Any],
        public_key_identifier: str | Path | Any = None,
        **kwargs: Any,
    ) -> bool:
        """Verifies that the signature matches the payload under the public key."""
        raise NotImplementedError


# ==============================================================================
# 4. ArtifactStore Contract
# ==============================================================================


class ArtifactStore(ABC):
    """
    Abstraction for persisting and retrieving evaluation artifacts, trajectories, and blobs.
    OSS Reference: LocalFileArtifactStore
    Control Plane / Enterprise: S3ArtifactStore / GCSArtifactStore / AzureBlobArtifactStore
    """

    @abstractmethod
    def store_artifact(
        self,
        run_id: str,
        artifact_name: str,
        content: bytes | str,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Stores an artifact and returns its persistent URI / path."""
        raise NotImplementedError

    @abstractmethod
    def get_artifact(self, run_id: str, artifact_name: str) -> bytes | None:
        """Retrieves raw artifact content by run ID and name."""
        raise NotImplementedError

    @abstractmethod
    def exists(self, run_id: str, artifact_name: str) -> bool:
        """Checks if a given artifact exists for a run."""
        raise NotImplementedError

    @abstractmethod
    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        """Lists all artifacts associated with a run."""
        raise NotImplementedError

    @abstractmethod
    def seal(self, run_id: str, metadata: dict[str, Any] | None = None) -> None:
        """Seals the artifact vault for a run, transitioning it to immutable READ_ONLY state."""
        raise NotImplementedError

    @abstractmethod
    def is_sealed(self, run_id: str) -> bool:
        """Returns True if the run artifact vault has been sealed against further mutations."""
        raise NotImplementedError


# ==============================================================================
# 5. PolicyEvaluator & PolicyEvaluationResult Contract
# ==============================================================================


class PolicyEvaluationResult:
    """Standard result structure for a policy evaluation decision."""

    def __init__(
        self,
        allowed: bool,
        policy_id: str,
        reason: str | None = None,
        violations: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.allowed = allowed
        self.policy_id = policy_id
        self.reason = reason or ("Policy passed" if allowed else "Policy violated")
        self.violations = violations or []
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "policy_id": self.policy_id,
            "reason": self.reason,
            "violations": self.violations,
            "metadata": self.metadata,
        }


class PolicyEvaluator(ABC):
    """
    Abstraction for policy rule evaluation and runtime sandbox constraint gating.
    OSS Reference: BasicFieldPolicyEvaluator
    Control Plane / Enterprise: OPAPolicyEvaluator / CedarPolicyEvaluator
    """

    @abstractmethod
    def evaluate_policy(
        self,
        policy_spec: dict[str, Any] | str,
        input_data: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> PolicyEvaluationResult:
        """Evaluates input data against a policy specification."""
        raise NotImplementedError

    @abstractmethod
    def validate_policy(self, policy_spec: dict[str, Any]) -> bool:
        """Validates that a policy specification schema is syntactically correct and supported."""
        raise NotImplementedError


# ==============================================================================
# 6. AuthorizationBackend & AuthPrincipal Contract
# ==============================================================================


class AuthPrincipal:
    """Represents an authenticated principal (user, service account, api token)."""

    def __init__(
        self,
        principal_id: str,
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.principal_id = principal_id
        self.roles = roles or []
        self.permissions = permissions or []
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "principal_id": self.principal_id,
            "roles": self.roles,
            "permissions": self.permissions,
            "metadata": self.metadata,
        }


class AuthorizationBackend(ABC):
    """
    Abstraction for access control, token validation, and permission checks.
    OSS Reference: SimpleAPIKeyAuthBackend
    Control Plane / Enterprise: OIDC_SCIM_AuthBackend
    """

    @abstractmethod
    def validate_token(self, token: str) -> AuthPrincipal | None:
        """Validates an incoming bearer/API token and returns the principal if valid."""
        raise NotImplementedError

    @abstractmethod
    def check_permission(self, principal: AuthPrincipal, resource: str, action: str = "") -> bool:
        """Checks if the principal is authorized to perform action on resource."""
        raise NotImplementedError


# ==============================================================================
# 7. CatalogStore Contract
# ==============================================================================


class CatalogStore(ABC):
    """
    Abstraction for scenario discovery, catalog management, and scenario resolution.
    OSS Reference: LocalFileCatalogStore
    Control Plane / Enterprise: RemoteCatalogStore / PostgresCatalogStore
    """

    @abstractmethod
    def list_scenarios(self, category: str | None = None) -> list[dict[str, Any]]:
        """Lists available scenario metadata in the catalog."""
        raise NotImplementedError

    @abstractmethod
    def get_scenario(self, scenario_id: str) -> dict[str, Any] | None:
        """Retrieves parsed scenario definition by identifier."""
        raise NotImplementedError

    @abstractmethod
    def save_scenario(self, scenario_id: str, scenario_data: dict[str, Any]) -> str:
        """Persists or updates a scenario in the catalog."""
        raise NotImplementedError

    @abstractmethod
    def delete_scenario(self, scenario_id: str) -> bool:
        """Removes a scenario from the catalog."""
        raise NotImplementedError


# ==============================================================================
# 8. RunStore Contract
# ==============================================================================


class RunStore(ABC):
    """
    Abstraction for evaluation run metadata, manifest retrieval, and run lifecycle query.
    OSS Reference: LocalFileRunStore
    Control Plane / Enterprise: PostgresRunStore / ClickHouseRunStore
    """

    @abstractmethod
    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Retrieves run summary, manifest, and status by run ID."""
        raise NotImplementedError

    @abstractmethod
    def list_runs(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Lists runs with pagination."""
        raise NotImplementedError

    @abstractmethod
    def save_run_manifest(self, run_id: str, manifest: dict[str, Any]) -> str:
        """Saves a run manifest and returns the record ID or URI."""
        raise NotImplementedError

    @abstractmethod
    def delete_run(self, run_id: str) -> bool:
        """Deletes a run and its metadata."""
        raise NotImplementedError


# ==============================================================================
# 9. LeaderboardStore Contract
# ==============================================================================


class LeaderboardStore(ABC):
    """
    Abstraction for leaderboard statistical aggregation, model rankings, and benchmark comparisons.
    OSS Reference: LocalLeaderboardStore
    Control Plane / Enterprise: DistributedLeaderboardStore
    """

    @abstractmethod
    def get_leaderboard(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Computes and returns aggregated leaderboard rows."""
        raise NotImplementedError

    @abstractmethod
    def record_run_summary(
        self, run_id_or_summary: str | dict[str, Any], summary: dict[str, Any] | None = None
    ) -> None:
        """Records or updates a run summary in the leaderboard index."""
        raise NotImplementedError


__all__ = [
    "ExecutionBackend",
    "CheckpointStore",
    "SigningBackend",
    "ArtifactStore",
    "PolicyEvaluator",
    "PolicyEvaluationResult",
    "AuthorizationBackend",
    "AuthPrincipal",
    "CatalogStore",
    "RunStore",
    "LeaderboardStore",
]
