---
title: Public Extension Families
description: Architecture, abstract base classes, and reference implementations for the 6 core AgentV extension families.
---

The **AgentV OS Runtime** provides six core **Public Extension Families** under the standardized, top-level namespace `agentv_runtime.interfaces`. These abstract base classes (ABCs) decouple enterprise control planes, custom orchestrators, and governance systems from internal engine details, guaranteeing **Zero-Touch Hot-Swap** compatibility.

---

## Subsystem Contract Versioning

Each subsystem contract publishes an independent version attribute to guarantee backward compatibility:

```python
import eval_runner

assert eval_runner.__runtime_api_version__ == "1.9"
assert eval_runner.__plugin_api_version__ == "1.0"
assert eval_runner.__config_schema_version__ == "1.0"
assert eval_runner.__aes_schema_version__ == "1.4"
```

---

## 1. ExecutionBackend

The `ExecutionBackend` family defines asynchronous submission, polling, cancellation, and resumption of evaluation runs across local compute, containers, or distributed execution meshes (e.g. Ray, Temporal).

### Abstract Contract

```python
from abc import ABC, abstractmethod
from typing import Any


class ExecutionBackend(ABC):
    """Abstract execution backend contract."""

    @abstractmethod
    async def submit(self, run_id: str, scenario: dict[str, Any], config: dict[str, Any]) -> str:
        """Submit a scenario execution job. Returns the unique job or task identifier."""
        pass

    @abstractmethod
    async def status(self, job_id: str) -> dict[str, Any]:
        """Query current execution status of a submitted job."""
        pass

    @abstractmethod
    async def cancel(self, job_id: str) -> bool:
        """Cancel an in-flight execution job."""
        pass

    @abstractmethod
    async def resume(self, job_id: str, checkpoint_id: str) -> bool:
        """Resume execution from a persisted checkpoint."""
        pass
```

### OSS Reference Implementation: `InProcessExecutionBackend`

Ships out of the box in `eval_runner.reference.InProcessExecutionBackend`:

```python
from agentv_runtime.interfaces import ExecutionBackend
from eval_runner.reference import InProcessExecutionBackend

backend: ExecutionBackend = InProcessExecutionBackend()
job_id = await backend.submit("run_123", scenario_data, {})
status_info = await backend.status(job_id)
```

---

## 2. CheckpointStore

The `CheckpointStore` family provides durable session persistence, checkpoint serialization, and timeline query capabilities.

### Abstract Contract

```python
from abc import ABC, abstractmethod
from typing import Any


class CheckpointStore(ABC):
    """Abstract checkpoint persistence store contract."""

    @abstractmethod
    async def save_checkpoint(
        self,
        run_id: str,
        turn_number: int,
        state: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persist a turn checkpoint. Returns the unique checkpoint identifier."""
        pass

    @abstractmethod
    async def load_checkpoint(self, checkpoint_id: str) -> dict[str, Any] | None:
        """Load full checkpoint state and metadata by checkpoint ID."""
        pass

    @abstractmethod
    async def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        """List checkpoint summaries for a given evaluation run."""
        pass
```

### OSS Reference Implementation: `SQLiteCheckpointStore`

Ships in `eval_runner.reference.SQLiteCheckpointStore`, featuring lazy SQLite initialization, concurrency safety, and zero unclosed resource warnings:

```python
from agentv_runtime.interfaces import CheckpointStore
from eval_runner.reference import SQLiteCheckpointStore

store: CheckpointStore = SQLiteCheckpointStore(db_path=":memory:")
cp_id = await store.save_checkpoint("run_101", 1, {"turn": 1}, {"timestamp": 1234567890})
checkpoints = await store.list_checkpoints("run_101")
```

---

## 3. SigningBackend

The `SigningBackend` family abstracts asymmetric cryptographic signing and verification (e.g. Ed25519, cloud HSMs, KMS).

### Abstract Contract

```python
from abc import ABC, abstractmethod
from pathlib import Path


class SigningBackend(ABC):
    """Abstract asymmetric signing and verification backend."""

    @abstractmethod
    def sign(self, payload: bytes, key_identifier: str | Path) -> str:
        """Sign a raw binary payload. Returns base64-encoded signature string."""
        pass

    @abstractmethod
    def verify(self, payload: bytes, signature: str, public_key_identifier: str | Path) -> bool:
        """Verify signature over raw binary payload using the public key."""
        pass
```

---

## 4. ArtifactStore

The `ArtifactStore` family abstracts blob and forensic artifact persistence (e.g. local directory vaults, S3, GCS, Azure Blob).

### Abstract Contract

```python
from abc import ABC, abstractmethod
from pathlib import Path


class ArtifactStore(ABC):
    """Abstract forensic artifact store contract."""

    @abstractmethod
    async def store_artifact(
        self,
        run_id: str,
        name: str,
        content: bytes | str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Store an artifact. Returns an authoritative URI or relative path."""
        pass

    @abstractmethod
    async def retrieve_artifact(self, artifact_uri: str) -> bytes | None:
        """Retrieve binary content of an artifact by URI."""
        pass

    @abstractmethod
    async def delete_artifact(self, artifact_uri: str) -> bool:
        """Delete an artifact from the store."""
        pass
```

### OSS Reference Implementation: `LocalFileArtifactStore`

Ships in `eval_runner.reference.LocalFileArtifactStore`:

```python
from agentv_runtime.interfaces import ArtifactStore
from eval_runner.reference import LocalFileArtifactStore

store: ArtifactStore = LocalFileArtifactStore(base_dir=Path("./vault"))
uri = await store.store_artifact("run_101", "report.json", b'{"status": "ok"}', "application/json")
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
    policy_id: str
    reason: str = ""
    violations: list[str] = field(default_factory=list)


class PolicyEvaluator(ABC):
    """Abstract policy evaluator contract."""

    @abstractmethod
    def evaluate_policy(
        self,
        tool_name: str,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> PolicyEvaluationResult:
        """Evaluate a tool invocation against active policies."""
        pass
```

### OSS Reference Implementation: `BasicFieldPolicyEvaluator`

Ships in `eval_runner.reference.BasicFieldPolicyEvaluator`, enforcing numeric thresholds and field constraints:

```python
from agentv_runtime.interfaces import PolicyEvaluator, PolicyEvaluationResult
from eval_runner.reference import BasicFieldPolicyEvaluator

evaluator: PolicyEvaluator = BasicFieldPolicyEvaluator({"max_limit": 100.0})
result: PolicyEvaluationResult = evaluator.evaluate_policy("refund", {"amount": 250.0})
assert not result.allowed
assert "exceeds limit" in result.reason
```

---

## 6. AuthorizationBackend & AuthPrincipal

The `AuthorizationBackend` family decouples agent identity, role-based access control (RBAC), and policy-based access control (PBAC) from specific identity providers (Okta, Entra ID, PingFederate).

### Abstract Contract & Principal Model

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AuthPrincipal:
    """Security principal definition."""

    principal_id: str
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class AuthorizationBackend(ABC):
    """Abstract authorization backend contract."""

    @abstractmethod
    def authorize(self, principal: AuthPrincipal, resource: str, action: str) -> bool:
        """Determine whether the principal is authorized to perform action on resource."""
        pass
```

---

## Immutability & Zero-Touch Hot-Swap Guarantee

The `agentv_runtime.interfaces` namespace is sealed under standard semantic versioning:
1. **Public Stability**: Abstract methods and dataclass models will not undergo breaking signature changes within the `v1.x` release lifecycle.
2. **Seamless Upgrades**: Control Planes importing `agentv_runtime.interfaces` can pull new runtime revisions (`git checkout public/dev`) without codebase modifications or monkey-patching.
