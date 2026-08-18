---
title: Public Extension Families
description: Architecture, abstract base classes, and reference implementations for the 6 core AgentV extension families and Phase 1 storage interfaces.
---

The **AgentV OS Runtime** provides core **Public Extension Families** under the standardized, top-level namespace `agentv_runtime.interfaces` (and `eval_runner.interfaces`). These abstract base classes (ABCs) decouple enterprise control planes, custom orchestrators, and governance systems from internal engine details, guaranteeing **Zero-Touch Hot-Swap** compatibility.

---

## Subsystem Contract Versioning

Each subsystem contract publishes an authoritative version dunder in `agentv_runtime` and `eval_runner` to guarantee backward compatibility:

```python
import agentv_runtime

assert agentv_runtime.__runtime_api_version__ == "2.0"
assert agentv_runtime.__plugin_api_version__ == "1.0"
assert agentv_runtime.__config_schema_version__ == "1.0"
assert agentv_runtime.__aes_schema_version__ == "1.4"
assert agentv_runtime.__certificate_schema_version__ == "3.0.0"
assert agentv_runtime.__event_schema_version__ == "1.0"
```

---

## 1. ExecutionBackend

The `ExecutionBackend` family defines synchronous and asynchronous submission, polling, cancellation, and resumption of evaluation runs across local compute, background worker threads, or distributed execution meshes.

### Abstract Contract

```python
from abc import ABC, abstractmethod
from typing import Any


class ExecutionBackend(ABC):
    """Abstract execution backend contract."""

    @abstractmethod
    def submit(
        self,
        run_id: str,
        scenario_data: dict[str, Any],
        config: dict[str, Any] | None = None,
        background: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Submit a scenario execution run."""
        raise NotImplementedError

    @abstractmethod
    def status(self, run_id: str) -> dict[str, Any]:
        """Query status and execution metadata of a submitted run."""
        raise NotImplementedError

    @abstractmethod
    def cancel(self, run_id: str, reason: str | None = None) -> bool:
        """Cancel an in-flight execution run."""
        raise NotImplementedError

    @abstractmethod
    def resume(self, run_id: str, resumption_token: str | None = None) -> dict[str, Any] | None:
        """Resume an interrupted or human-in-the-loop paused execution run."""
        raise NotImplementedError
```

### OSS Reference Implementation: `InProcessExecutionBackend`

Ships out of the box in `eval_runner.reference.InProcessExecutionBackend` (and `agentv_runtime.reference`):

```python
from agentv_runtime.interfaces import ExecutionBackend
from agentv_runtime.reference import InProcessExecutionBackend

backend: ExecutionBackend = InProcessExecutionBackend()
res = backend.submit("run_123", scenario_data, background=False)
status_info = backend.status("run_123")
```

---

## 2. CheckpointStore

The `CheckpointStore` family provides durable session persistence, turn snapshotting before Human-in-the-Loop (HITL) approval gates, and state resumption.

### Abstract Contract

```python
from abc import ABC, abstractmethod
from typing import Any


class CheckpointStore(ABC):
    """Abstract checkpoint persistence store contract."""

    @abstractmethod
    def save(
        self,
        run_id: str,
        checkpoint_id: str,
        state: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persist a turn checkpoint state. Returns a durable URI."""
        raise NotImplementedError

    @abstractmethod
    def load(self, run_id: str, checkpoint_id: str | None = None) -> dict[str, Any] | None:
        """Load state for a specific checkpoint or the latest turn."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, run_id: str, checkpoint_id: str | None = None) -> bool:
        """Delete specific checkpoint or all checkpoints for a run."""
        raise NotImplementedError

    @abstractmethod
    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        """List checkpoint summaries for a given run."""
        raise NotImplementedError
```

### OSS Reference Implementation: `SQLiteCheckpointStore`

Ships in `eval_runner.reference.SQLiteCheckpointStore`, featuring lazy SQLite initialization, thread concurrency safety, and durable recovery:

```python
from agentv_runtime.interfaces import CheckpointStore
from agentv_runtime.reference import SQLiteCheckpointStore

store: CheckpointStore = SQLiteCheckpointStore(db_path="runs/checkpoints.db")
chk_uri = store.save("run_101", "chk_001", {"turn": 1, "messages": ["hello"]})
state = store.load("run_101", checkpoint_id="chk_001")
```

---

## 3. SigningBackend

The `SigningBackend` family abstracts asymmetric cryptographic signing, Verification Certificate (VC v3.0.0) sealing, and signature verification (Ed25519, Post-Quantum ML-DSA-65, Cloud HSMs, KMS).

### Abstract Contract

```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class SigningBackend(ABC):
    """Abstract asymmetric signing and verification backend."""

    @abstractmethod
    def sign_payload(self, payload: bytes, key_identifier: str | Path, **kwargs: Any) -> str:
        """Sign a raw binary payload. Returns a hex-encoded signature string."""
        raise NotImplementedError

    @abstractmethod
    def verify_signature(
        self, payload: bytes, signature: str, public_key_identifier: str | Path, **kwargs: Any
    ) -> bool:
        """Verify signature over raw binary payload against the public key."""
        raise NotImplementedError
```

### OSS Reference Implementations

1. **`LocalEd25519SigningBackend`**: Classical Ed25519 PEM signing and verification on local disk.
2. **`PQCSigningBackend`**: Quantum-safe Zero-Exposure Signing (ZES) via SHAKE-256 local hashing and ML-DSA-65 (FIPS 204) delegating to `IdentityService.get_pqc_client()`.
3. **`NullSigningBackend`**: Null implementation for disabled signing environments.

```python
from agentv_runtime.reference import LocalEd25519SigningBackend, PQCSigningBackend

signer = LocalEd25519SigningBackend()
sig_hex = signer.sign_payload(b'{"eval":"success"}', "keys/system_id/private_key.pem")
is_valid = signer.verify_signature(b'{"eval":"success"}', sig_hex, "keys/system_id/public_key.pem")
```

> [!IMPORTANT]
> **Fail-Closed Policy**: When `EVAL_REQUIRE_SIGNING=true` or `AUDIT_LEVEL >= 2` and no valid signing key or backend is configured, the runtime immediately raises a `RuntimeError` ("CryptographicSigningError: Signing is mandatory..."), preventing unsealed evaluations.

---

## 4. ArtifactStore

The `ArtifactStore` family abstracts blob and forensic artifact persistence (e.g. local run vaults, S3, GCS, Azure Blob).

### Abstract Contract

```python
from abc import ABC, abstractmethod
from typing import Any


class ArtifactStore(ABC):
    """Abstract forensic artifact store contract."""

    @abstractmethod
    def store_artifact(
        self,
        run_id: str,
        artifact_name: str,
        content: bytes | str,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store an artifact. Returns the physical file path or URI."""
        raise NotImplementedError

    @abstractmethod
    def get_artifact(self, run_id: str, artifact_name: str) -> bytes | None:
        """Retrieve binary content of an artifact by name."""
        raise NotImplementedError

    @abstractmethod
    def exists(self, run_id: str, artifact_name: str) -> bool:
        """Check if an artifact exists."""
        raise NotImplementedError

    @abstractmethod
    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        """List metadata for all artifacts recorded for a run."""
        raise NotImplementedError
```

### OSS Reference Implementation: `LocalFileArtifactStore`

Ships in `eval_runner.reference.LocalFileArtifactStore`:

```python
from agentv_runtime.reference import LocalFileArtifactStore

store = LocalFileArtifactStore(base_dir="runs")
path = store.store_artifact(
    "run_101", "trace.jsonl", b'{"event":"start"}', metadata={"type": "trace"}
)
```

---

## 5. PolicyEvaluator & PolicyEvaluationResult

The `PolicyEvaluator` family enables real-time governance, tool call parameter constraints, and regulatory boundary validation without raising unhandled exceptions in control flow.

### Abstract Contract & Return Model

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PolicyEvaluationResult:
    """Standardized policy evaluation outcome."""

    allowed: bool
    policy_id: str = "default_policy"
    reason: str = ""
    violations: list[dict[str, Any]] = field(default_factory=list)


class PolicyEvaluator(ABC):
    """Abstract policy evaluator contract."""

    @abstractmethod
    def evaluate_policy(
        self,
        policy_spec: dict[str, Any],
        input_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> PolicyEvaluationResult:
        """Evaluate input data and tool arguments against policy rules."""
        raise NotImplementedError

    @abstractmethod
    def validate_policy(self, policy_spec: dict[str, Any]) -> bool:
        """Validate syntax and schema of a policy specification."""
        raise NotImplementedError
```

### OSS Reference Implementation: `BasicFieldPolicyEvaluator`

Ships in `eval_runner.reference.BasicFieldPolicyEvaluator`, enforcing numeric thresholds (`max_limit`, `constrained_params`), required fields, and allowed values:

```python
from agentv_runtime.reference import BasicFieldPolicyEvaluator

evaluator = BasicFieldPolicyEvaluator()
policy_spec = {"max_limit": 500, "constrained_params": ["transfer_amount"]}
result = evaluator.evaluate_policy(policy_spec, {"transfer_amount": 750})
assert not result.allowed
assert result.violations[0]["field"] == "transfer_amount"
```

---

## 6. AuthorizationBackend & AuthPrincipal

The `AuthorizationBackend` family decouples agent identity, role-based access control (RBAC), and permission checks from specific identity providers.

### Abstract Contract & Principal Model

```python
from abc import ABC, abstractmethod
from typing import Any


class AuthPrincipal:
    """Security principal definition."""

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


class AuthorizationBackend(ABC):
    """Abstract authorization backend contract."""

    @abstractmethod
    def validate_token(self, token: str) -> AuthPrincipal | None:
        """Validates incoming bearer/API token and returns principal if valid."""
        raise NotImplementedError

    @abstractmethod
    def check_permission(self, principal: AuthPrincipal, resource: str, action: str = "") -> bool:
        """Check if principal has permission on resource:action."""
        raise NotImplementedError
```

### OSS Reference Implementation: `SimpleAPIKeyAuthBackend`

Ships in `eval_runner.reference.SimpleAPIKeyAuthBackend`:

```python
from agentv_runtime.reference import SimpleAPIKeyAuthBackend

auth = SimpleAPIKeyAuthBackend()
auth.register_key(
    key="auditor_key",
    principal_id="auditor_1",
    roles=["auditor"],
    permissions=["scenarios:read", "runs:*"],
)
principal = auth.validate_token("auditor_key")
assert auth.check_permission(principal, "runs:read") is True
assert auth.check_permission(principal, "scenarios:write") is False
```

---

## 7. Phase 1 Storage Extension Families

The runtime also exposes three specialized store interfaces for metadata, runs, and leaderboards:

### `CatalogStore` & `LocalFileCatalogStore`
Abstract scenario discovery, search, and storage.
```python
from agentv_runtime.interfaces import CatalogStore
from agentv_runtime.reference import LocalFileCatalogStore

catalog: CatalogStore = LocalFileCatalogStore(base_dir=".")
scenarios = catalog.list_scenarios(category="finance")
```

### `RunStore` & `LocalFileRunStore`
Abstract run vault persistence, manifest reading, and deletion.
```python
from agentv_runtime.interfaces import RunStore
from agentv_runtime.reference import LocalFileRunStore

run_store: RunStore = LocalFileRunStore(log_dir="runs")
run_info = run_store.get_run("run-101")
```

### `LeaderboardStore` & `LocalLeaderboardStore`
Abstract leaderboard metric aggregation and historical tracking.
```python
from agentv_runtime.interfaces import LeaderboardStore
from agentv_runtime.reference import LocalLeaderboardStore

lb_store: LeaderboardStore = LocalLeaderboardStore(runs_dir="runs")
leaderboard_rows = lb_store.get_leaderboard(filters={"min_pass_rate": 50})
```

---

## Immutability & Zero-Touch Hot-Swap Guarantee

The `agentv_runtime.interfaces` namespace is sealed under semantic versioning:
1. **Public Stability**: Abstract methods and dataclass models will not undergo breaking signature changes within the `v2.x` release lifecycle.
2. **Seamless Upgrades**: Control Planes importing `agentv_runtime.interfaces` can pull new runtime revisions without codebase modifications or monkey-patching.
