"""
enterprise_extension_plugin.plugin
Implementation of all 6 Extension Families and 3 Storage Interfaces via agentv_runtime.interfaces.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agentv_runtime.interfaces import (
    ArtifactStore,
    AuthorizationBackend,
    AuthPrincipal,
    CatalogStore,
    CheckpointStore,
    ExecutionBackend,
    LeaderboardStore,
    PolicyEvaluationResult,
    PolicyEvaluator,
    RunStore,
    SigningBackend,
)


class EnterpriseExecutionBackend(ExecutionBackend):
    def __init__(self):
        self.submissions = []
        self.active_runs = {}

    def submit(self, run_id: str, scenario_data: dict[str, Any], **kwargs: Any) -> Any:
        self.submissions.append(run_id)
        self.active_runs[run_id] = {"status": "RUNNING", "scenario_data": scenario_data}
        return {"status": "submitted", "run_id": run_id, "backend": "EnterpriseExecutionBackend"}

    def status(self, run_id: str) -> dict[str, Any]:
        return self.active_runs.get(run_id, {"status": "UNKNOWN"})

    def cancel(self, run_id: str, reason: str | None = None) -> bool:
        if run_id in self.active_runs:
            self.active_runs[run_id]["status"] = "ABORTED"
            return True
        return False

    def resume(self, run_id: str, resumption_token: str | None = None, **kwargs: Any) -> Any:
        if run_id in self.active_runs:
            self.active_runs[run_id]["status"] = "RUNNING"
            return {"status": "RESUMED", "run_id": run_id}
        return {"status": "NOT_FOUND"}


class EnterpriseCheckpointStore(CheckpointStore):
    def __init__(self):
        self.checkpoints = {}
        self.save_count = 0
        self.load_count = 0

    def save(
        self,
        run_id: str,
        checkpoint_id: str,
        state: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self.save_count += 1
        key = f"{run_id}:{checkpoint_id}"
        self.checkpoints[key] = state
        return f"enterprise-cp://{run_id}/{checkpoint_id}"

    def load(self, run_id: str, checkpoint_id: str | None = None) -> dict[str, Any] | None:
        self.load_count += 1
        key = f"{run_id}:{checkpoint_id}" if checkpoint_id else f"{run_id}:latest"
        return self.checkpoints.get(key)

    def delete(self, run_id: str, checkpoint_id: str | None = None) -> bool:
        key = f"{run_id}:{checkpoint_id}"
        return self.checkpoints.pop(key, None) is not None

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        return [
            {"checkpoint_id": k.split(":")[1]}
            for k in self.checkpoints
            if k.startswith(f"{run_id}:")
        ]


class EnterpriseArtifactStore(ArtifactStore):
    def __init__(self):
        self.vault = {}
        self.sealed_runs = set()
        self.store_call_count = 0

    def store_artifact(
        self,
        run_id: str,
        artifact_name: str,
        content: bytes | str,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        if self.is_sealed(run_id):
            raise PermissionError(f"Run vault {run_id} is sealed (WORM).")
        self.store_call_count += 1
        self.vault[f"{run_id}/{artifact_name}"] = content
        return f"enterprise-s3://audit-vault/{run_id}/{artifact_name}"

    def get_artifact(self, run_id: str, artifact_name: str) -> bytes | None:
        val = self.vault.get(f"{run_id}/{artifact_name}")
        return val.encode() if isinstance(val, str) else val

    def exists(self, run_id: str, artifact_name: str) -> bool:
        return f"{run_id}/{artifact_name}" in self.vault

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        return [{"name": k.split("/")[1]} for k in self.vault if k.startswith(f"{run_id}/")]

    def seal(self, run_id: str, metadata: dict[str, Any] | None = None) -> None:
        self.sealed_runs.add(run_id)

    def is_sealed(self, run_id: str) -> bool:
        return run_id in self.sealed_runs


class EnterprisePolicyEvaluator(PolicyEvaluator):
    def __init__(self):
        self.evaluated_actions = []

    def evaluate_policy(
        self,
        policy_spec: dict[str, Any] | str,
        input_data: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> PolicyEvaluationResult:
        data = input_data or {}
        self.evaluated_actions.append(data)
        if data.get("amount", 0) > 1000:
            return PolicyEvaluationResult(
                allowed=False,
                policy_id="ent_pol_001",
                reason="Enterprise policy: amount exceeds $1000 threshold",
                violations=[{"field": "amount", "limit": 1000, "actual": data.get("amount")}],
            )
        return PolicyEvaluationResult(allowed=True, policy_id="ent_pol_001")

    def validate_policy(self, policy_spec: dict[str, Any]) -> bool:
        return isinstance(policy_spec, (dict, str))


class EnterpriseSigningBackend(SigningBackend):
    def __init__(self):
        self.signed_payloads = []

    def sign_payload(
        self, payload: bytes, key_identifier: str | Path | Any = None, **kwargs: Any
    ) -> str:
        self.signed_payloads.append(payload)
        sig = hashlib.sha256(payload + b"::enterprise-kms-key").hexdigest()
        return sig

    def verify_signature(
        self,
        payload: bytes,
        signature: str | dict[str, Any],
        public_key_identifier: str | Path | Any = None,
        **kwargs: Any,
    ) -> bool:
        expected = hashlib.sha256(payload + b"::enterprise-kms-key").hexdigest()
        return signature == expected


class EnterpriseAuthBackend(AuthorizationBackend):
    def validate_token(self, token: str) -> AuthPrincipal | None:
        if token.startswith("ent_token_"):
            return AuthPrincipal(
                principal_id="enterprise-sec-principal",
                roles=["enterprise_admin"],
                permissions=["scenarios:read", "scenarios:write", "runs:read", "runs:delete"],
            )
        return None

    def check_permission(self, principal: AuthPrincipal, resource: str, action: str = "") -> bool:
        return "enterprise_admin" in principal.roles


class EnterpriseCatalogStore(CatalogStore):
    def __init__(self):
        self.catalog = {}

    def list_scenarios(self, category: str | None = None) -> list[dict[str, Any]]:
        return list(self.catalog.values())

    def get_scenario(self, scenario_id: str) -> dict[str, Any] | None:
        return self.catalog.get(scenario_id)

    def save_scenario(self, scenario_id: str, scenario_data: dict[str, Any]) -> str:
        self.catalog[scenario_id] = scenario_data
        return f"ent-catalog://{scenario_id}"

    def delete_scenario(self, scenario_id: str) -> bool:
        return self.catalog.pop(scenario_id, None) is not None


class EnterpriseRunStore(RunStore):
    def __init__(self):
        self.runs = {}
        self.events = {}
        self.manifest_count = 0
        self._certification_leases: dict[str, tuple[str, str]] = {}
        self._submissions: dict[str, dict[str, Any]] = {}

    def reserve_submission(self, run_id, scenario_id, agent_id, metadata, context, idempotency_key):
        record = self._submissions.setdefault(
            run_id,
            {
                "run_id": run_id,
                "scenario_id": scenario_id,
                "agent_id": agent_id,
                "metadata": dict(metadata),
                "context": dict(context),
                "idempotency_key": idempotency_key,
                "state": "RESERVED",
            },
        )
        return dict(record)

    def get_submission(self, run_id, context=None):
        record = self._submissions.get(run_id)
        return dict(record) if self._in_scope(record, context) else None

    def transition_submission(self, run_id, expected_state, state, context):
        record = self.get_submission(run_id, context=context)
        if record is None:
            raise KeyError(run_id)
        expected = {expected_state} if isinstance(expected_state, str) else set(expected_state)
        if record["state"] not in expected:
            raise ValueError("submission state conflict")
        self._submissions[run_id]["state"] = state
        return dict(self._submissions[run_id])

    @staticmethod
    def _in_scope(run: dict[str, Any] | None, context: dict[str, Any] | None) -> bool:
        if run is None or not context:
            return run is not None
        record_context = run.get("context") or {}
        return all(record_context.get(key) in (None, value) for key, value in context.items())

    def create_run(
        self, run_id, scenario_id, agent_id=None, metadata=None, status="OPEN", context=None
    ):
        return self.runs.setdefault(
            run_id,
            {
                "run_id": run_id,
                "scenario_id": scenario_id,
                "agent_id": agent_id,
                "metadata": metadata or {},
                "context": context or {},
                "status": status,
                "lifecycle": status,
            },
        )

    def get_run(self, run_id: str, context=None) -> dict[str, Any] | None:
        run = self.runs.get(run_id)
        return run if self._in_scope(run, context) else None

    def get_manifest(self, run_id, context=None):
        run = self.get_run(run_id, context=context)
        return run.get("manifest") if run else None

    def get_events(self, run_id, offset=0, limit=1000, context=None):
        if self.get_run(run_id, context=context) is None:
            return []
        return self.events.get(run_id, [])[offset : offset + limit]

    def get_trace_bytes(self, run_id, context=None):
        """Fixture implementation of the exact provider-owned trace contract."""
        if self.get_run(run_id, context=context) is None:
            return None
        return b"".join(
            json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
            for event in self.events.get(run_id, [])
        )

    def update_run_status(self, run_id, status, details=None, context=None):
        run = self.get_run(run_id, context=context)
        if run is None:
            return False
        run["status"] = status
        if details:
            run["status_details"] = details
        return True

    def acquire_certification_lease(
        self, run_id, *, owner_id, fencing_token, timeout_seconds, context=None
    ) -> bool:
        del timeout_seconds
        run = self.get_run(run_id, context=context)
        if run is None or run_id in self._certification_leases:
            return False
        self._certification_leases[run_id] = (owner_id, fencing_token)
        return True

    def verify_certification_lease(self, run_id, *, owner_id, fencing_token, context=None) -> bool:
        return self.get_run(run_id, context=context) is not None and self._certification_leases.get(
            run_id
        ) == (owner_id, fencing_token)

    def renew_certification_lease(
        self, run_id, *, owner_id, fencing_token, timeout_seconds, context=None
    ) -> bool:
        del timeout_seconds
        return self.verify_certification_lease(
            run_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            context=context,
        )

    def release_certification_lease(self, run_id, *, owner_id, fencing_token, context=None) -> bool:
        if not self.verify_certification_lease(
            run_id, owner_id=owner_id, fencing_token=fencing_token, context=context
        ):
            return False
        del self._certification_leases[run_id]
        return True

    def is_certification_leased(self, run_id, *, context=None) -> bool:
        return (
            self.get_run(run_id, context=context) is not None
            and run_id in self._certification_leases
        )

    def append_events(self, run_id, events, context=None):
        if self.get_run(run_id, context=context) is None:
            return 0
        self.events.setdefault(run_id, []).extend(events)
        return len(events)

    def list_runs(self, limit: int = 100, offset: int = 0, context=None) -> list[dict[str, Any]]:
        scoped = [run for run in self.runs.values() if self._in_scope(run, context)]
        return scoped[offset : offset + limit]

    def search_runs(self, query="", filters=None, limit=100, offset=0, context=None):
        matches = [
            run
            for run in self.runs.values()
            if self._in_scope(run, context) and query.lower() in str(run).lower()
        ]
        return matches[offset : offset + limit]

    def stream_events(self, run_id, from_seq=0, context=None):
        yield from self.get_events(run_id, offset=from_seq, limit=10_000_000, context=context)

    def save_run_manifest(self, run_id: str, manifest: dict[str, Any], context=None) -> str:
        run = self.get_run(run_id, context=context)
        if run is None:
            if run_id in self.runs:
                return ""
            run = self.create_run(run_id, manifest.get("scenario_id", "unknown"), context=context)
        self.manifest_count += 1
        run.update(manifest)
        run["manifest"] = manifest
        return f"ent-runs://{run_id}"

    def commit_certification(
        self,
        run_id,
        manifest,
        *,
        owner_id,
        fencing_token,
        context=None,
    ) -> bool:
        """Fixture analogue of the Enterprise database transaction.

        The manifest and SEALED lifecycle are updated while the matching
        provider lease is held.  Core interacts only with this generic
        capability; it neither imports nor names this implementation.
        """
        if not self.verify_certification_lease(
            run_id, owner_id=owner_id, fencing_token=fencing_token, context=context
        ):
            return False
        run = self.runs[run_id]
        existing = run.get("manifest")
        if run.get("lifecycle") == "SEALED":
            return existing == manifest
        if existing is not None and existing != manifest:
            return False
        self.manifest_count += 1
        run.update(manifest)
        run["manifest"] = manifest
        run["status"] = "SEALED"
        run["lifecycle"] = "SEALED"
        return True

    def delete_run(self, run_id: str, context=None) -> bool:
        if self.get_run(run_id, context=context) is None:
            return False
        self.events.pop(run_id, None)
        return self.runs.pop(run_id, None) is not None


class EnterpriseLeaderboardStore(LeaderboardStore):
    def __init__(self):
        self.board = []

    def get_leaderboard(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return list(self.board)

    def record_run_summary(
        self, run_id_or_summary: str | dict[str, Any], summary: dict[str, Any] | None = None
    ) -> None:
        record = summary if summary is not None else run_id_or_summary
        if isinstance(record, dict):
            self.board.append(record)
