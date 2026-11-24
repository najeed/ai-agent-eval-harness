---
title: Public Extension Families
description: Architecture, abstract base classes, and reference implementations for the complete AgentV public extension families and storage interfaces.
---

The public contracts are defined in `agentv_runtime.interfaces` and re-exported
through `eval_runner.interfaces`. The inventories below show the current method
signatures; `abstractmethod` entries must be implemented by a provider. Concrete
capability methods also carry behavior required by their consumers.

## Scope and ownership

`AuthPrincipal` includes principal ID, roles, permissions, metadata and optional
`context_version`, `context`, `authorized_contexts`. A ScopePolicy resolves the
provider-owned ScopeToken. Scope tags are normalized and committed by digest;
preserve that scope across run reads, approvals, checkpoints and certification.
Caller-selected tenant identifiers cannot override ownership.

## Signing and evidence persistence

SigningBackend supports opaque/default key identifiers, `can_sign()` and
`requires_private_key_material`. Low-level raw Ed25519 hex is not a sufficient
artifact signature. Authoritative artifacts require a complete
[versioned digest envelope](/spec/digest-signature-envelope/) and its purpose and
external SignaturePolicy. Wrap a deliberately selected RAW provider with
`DigestEnvelopeSigningBackend`; provider failures must propagate, not select a
different signing authority.

ArtifactStore must implement `seal` and `is_sealed`. A provider that cannot
participate in atomic certification sealing must not claim transactional-seal
support. Local logical sealing is tamper-evident; physical WORM requires an
external retention-enforcing implementation.

`RunStore` is an alias for `RunStorageProvider`, not a filesystem directory API.
The provider owns scoped records, exact committed trace bytes, event streams,
submission reservation/transitions, leases and atomic certificate publication.
`commit_certification` must publish the certificate and sealed lifecycle together;
failed operations must not expose a partially committed certificate. Exact trace
bytes cannot be reconstructed from parsed event objects for authoritative checks.

## Approval request data

`ApprovalRequest` is a class, not the older node/tool dataclass. Its constructor
accepts approval_token, run_id, turn_index, outbound_payload_hash, required_role,
reviewer_credentials, status, rule_id, checkpoint_id, action_payload, prompt,
created_at, decision, decision_reason, decided_by, decided_at, metadata, scope,
scope_digest, manifest_id and idempotency_key. Node/tool attribution can be
carried in the action or metadata, not nonexistent node_id/tool_name constructor
parameters. Durable decisions are `APPROVED`/`REJECTED`. Scope, payload and
checkpoint bindings protect against replay and cross-context resolution.

## Current method inventory

### ExecutionBackend

```python
@abstractmethod
def submit(self, run_id: str, scenario_data: dict[str, Any], **kwargs: Any) -> Any: ...

@abstractmethod
def status(self, run_id: str) -> dict[str, Any]: ...

@abstractmethod
def cancel(self, run_id: str, reason: str | None=None) -> bool: ...

@abstractmethod
def resume(self, run_id: str, resumption_token: str | None=None, **kwargs: Any) -> Any: ...
```

### CheckpointStore

```python
@abstractmethod
def save(self, run_id: str, checkpoint_id: str, state: dict[str, Any], metadata: dict[str, Any] | None=None) -> str: ...

@abstractmethod
def load(self, run_id: str, checkpoint_id: str | None=None) -> dict[str, Any] | None: ...

@abstractmethod
def delete(self, run_id: str, checkpoint_id: str | None=None) -> bool: ...

@abstractmethod
def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]: ...
```

### SigningBackend

```python
def can_sign(self) -> bool: ...

@abstractmethod
def sign_payload(self, payload: bytes, key_identifier: str | Path | Any=None, **kwargs: Any) -> str | dict[str, Any]: ...

@abstractmethod
def verify_signature(self, payload: bytes, signature: str | dict[str, Any], public_key_identifier: str | Path | Any=None, **kwargs: Any) -> bool: ...
```

### ArtifactStore

```python
@abstractmethod
def store_artifact(self, run_id: str, artifact_name: str, content: bytes | str, content_type: str | None=None, metadata: dict[str, Any] | None=None, **kwargs: Any) -> str: ...

@abstractmethod
def get_artifact(self, run_id: str, artifact_name: str) -> bytes | None: ...

@abstractmethod
def exists(self, run_id: str, artifact_name: str) -> bool: ...

@abstractmethod
def list_artifacts(self, run_id: str) -> list[dict[str, Any]]: ...

@abstractmethod
def seal(self, run_id: str, metadata: dict[str, Any] | None=None) -> None: ...

@abstractmethod
def is_sealed(self, run_id: str) -> bool: ...

def supports_transactional_seal(self) -> bool: ...
```

### PolicyEvaluator

```python
@abstractmethod
def evaluate_policy(self, policy_spec: dict[str, Any] | str, input_data: dict[str, Any] | None=None, context: dict[str, Any] | None=None, **kwargs: Any) -> PolicyEvaluationResult: ...

@abstractmethod
def validate_policy(self, policy_spec: dict[str, Any]) -> bool: ...
```

### AuthorizationBackend

```python
@abstractmethod
def validate_token(self, token: str) -> AuthPrincipal | None: ...

@abstractmethod
def check_permission(self, principal: AuthPrincipal, resource: str, action: str='') -> bool: ...

def get_service_credential(self) -> str | None: ...
```

### CatalogStore

```python
@abstractmethod
def list_scenarios(self, category: str | None=None) -> list[dict[str, Any]]: ...

@abstractmethod
def get_scenario(self, scenario_id: str) -> dict[str, Any] | None: ...

@abstractmethod
def save_scenario(self, scenario_id: str, scenario_data: dict[str, Any]) -> str: ...

@abstractmethod
def delete_scenario(self, scenario_id: str) -> bool: ...
```

### RunStorageProvider

```python
@abstractmethod
def create_run(self, run_id: str, scenario_id: str, agent_id: str | None=None, metadata: dict[str, Any] | None=None, status: str='OPEN', context: dict[str, Any] | None=None) -> dict[str, Any]: ...

@abstractmethod
def reserve_submission(self, run_id: str, scenario_id: str, agent_id: str | None, metadata: dict[str, Any], context: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...

@abstractmethod
def get_submission(self, run_id: str, context: dict[str, Any] | None=None) -> dict[str, Any] | None: ...

@abstractmethod
def transition_submission(self, run_id: str, expected_state: str | tuple[str, ...], state: str, context: dict[str, Any]) -> dict[str, Any]: ...

@abstractmethod
def get_run(self, run_id: str, context: dict[str, Any] | None=None) -> dict[str, Any] | None: ...

@abstractmethod
def get_manifest(self, run_id: str, context: dict[str, Any] | None=None) -> dict[str, Any] | None: ...

@abstractmethod
def get_events(self, run_id: str, offset: int=0, limit: int=1000, context: dict[str, Any] | None=None) -> list[dict[str, Any]]: ...

@abstractmethod
def get_trace_bytes(self, run_id: str, context: dict[str, Any] | None=None) -> bytes | None: ...

@abstractmethod
def update_run_status(self, run_id: str, status: str, details: dict[str, Any] | None=None, context: dict[str, Any] | None=None) -> bool: ...

@abstractmethod
def append_events(self, run_id: str, events: list[dict[str, Any]], context: dict[str, Any] | None=None) -> int: ...

@abstractmethod
def save_run_manifest(self, run_id: str, manifest: dict[str, Any], context: dict[str, Any] | None=None) -> str: ...

@abstractmethod
def delete_run(self, run_id: str, context: dict[str, Any] | None=None) -> bool: ...

@abstractmethod
def list_runs(self, limit: int=100, offset: int=0, context: dict[str, Any] | None=None) -> list[dict[str, Any]]: ...

@abstractmethod
def search_runs(self, query: str='', filters: dict[str, Any] | None=None, limit: int=100, offset: int=0, context: dict[str, Any] | None=None) -> list[dict[str, Any]]: ...

@abstractmethod
def stream_events(self, run_id: str, from_seq: int=0, context: dict[str, Any] | None=None) -> Generator[dict[str, Any], None, None]: ...

def get_lifecycle(self, run_id: str, context: dict[str, Any] | None=None) -> str | None: ...

def acquire_certification_lease(self, run_id: str, *, owner_id: str, fencing_token: str, timeout_seconds: float, context: dict[str, Any] | None=None) -> bool: ...

def verify_certification_lease(self, run_id: str, *, owner_id: str, fencing_token: str, context: dict[str, Any] | None=None) -> bool: ...

def renew_certification_lease(self, run_id: str, *, owner_id: str, fencing_token: str, timeout_seconds: float, context: dict[str, Any] | None=None) -> bool: ...

def release_certification_lease(self, run_id: str, *, owner_id: str, fencing_token: str, context: dict[str, Any] | None=None) -> bool: ...

def is_certification_leased(self, run_id: str, *, context: dict[str, Any] | None=None) -> bool: ...

def commit_certification(self, run_id: str, manifest: dict[str, Any], *, owner_id: str, fencing_token: str, context: dict[str, Any] | None=None) -> bool: ...
```

### LeaderboardStore

```python
@abstractmethod
def get_leaderboard(self, filters: dict[str, Any] | None=None) -> list[dict[str, Any]]: ...

@abstractmethod
def record_run_summary(self, run_id_or_summary: str | dict[str, Any], summary: dict[str, Any] | None=None) -> None: ...
```

### ApprovalStore

```python
@abstractmethod
def create_request(self, request: ApprovalRequest) -> ApprovalRequest: ...

@abstractmethod
def get_request(self, approval_token: str, scope: ScopeToken | None=None) -> ApprovalRequest | None: ...

def get(self, approval_token: str) -> ApprovalRequest | None: ...

@abstractmethod
def get_request_by_run_id(self, run_id: str, scope: ScopeToken | None=None) -> ApprovalRequest | None: ...

@abstractmethod
def resolve_request(self, approval_token: str, decision: str, decided_by: str | None=None, decision_reason: str | None=None, scope: ScopeToken | None=None) -> ApprovalRequest: ...

@abstractmethod
def list_pending(self, run_id: str | None=None, scope: ScopeToken | None=None) -> list[ApprovalRequest]: ...

def stream_pending(self, scope: ScopeToken) -> Iterator[ApprovalEvent]: ...

@abstractmethod
def delete_request(self, approval_token: str, scope: ScopeToken | None=None) -> bool: ...
```

### MutationEngine

```python
@abstractmethod
def mutate_scenario(self, scenario_data: dict[str, Any], mutation_spec: str | dict[str, Any], seed: int | None=None, **kwargs: Any) -> dict[str, Any]: ...

@abstractmethod
def apply_in_run(self, context: Any, mutation_spec: str | dict[str, Any] | Any, **kwargs: Any) -> Any: ...

@abstractmethod
def list_supported_mutators(self) -> list[dict[str, Any]]: ...

@abstractmethod
def list_mutation_catalog(self, org_id: str | None=None) -> list[MutationDescriptor]: ...
```

### BoundedStateProvider

```python
@abstractmethod
def query_bounded_reference(self, scope: str, selector: dict[str, Any] | str, max_items: int | None=None, max_bytes: int | None=None, **kwargs: Any) -> Any: ...

@abstractmethod
def commit_state_transition(self, scope: str, operation: str, delta: dict[str, Any] | None=None, **kwargs: Any) -> Any: ...

def get_all_state(self) -> Any: ...
```


## Reference composition

```python
from agentv_runtime.reference import LocalFileRunStore, LocalLeaderboardStore
from agentv_runtime.contracts import MutationDescriptor

run_store = LocalFileRunStore(log_dir="runs")
leaderboard = LocalLeaderboardStore(run_store=run_store)
rows = leaderboard.get_leaderboard(filters={"min_pass_rate": 50})
```

Other reference providers include `InProcessExecutionBackend`,
`SQLiteCheckpointStore`, `LocalFileArtifactStore`, `LocalFileCatalogStore`,
`BasicFieldPolicyEvaluator`, `SimpleAPIKeyAuthBackend`, and local/null/PQC signing
primitives. File/SQLite approval stores are exported by `eval_runner.reference`.
Reference imports can load runtime dependencies; the neutral public contract
namespace does not imply a dependency-free distribution.

`BoundedStateProvider.get_all_state()` deliberately rejects unbounded state
materialization. Use declared bounded selectors and limits; implementations must
not dump the entire state before trimming the result. Mutation catalog presence
does not prove executable delivery; `concurrent` remains unsupported in Core.
