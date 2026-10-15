"""
eval_runner.services.config_revision
Authoritative Server-Side Configuration Revision Consumption and Observation Provider (v2.0.0).

Provides generic, server-side configuration-revision lifecycle governance:
  1. Accepts immutable desired fingerprints and derives target scope strictly from server context.
  2. Tracks separate, durable states:
     PROVIDER_ACCEPTED, DEPLOYED, OBSERVED, PARTIALLY_APPLIED, FAILED.
  3. Records per-instance Runtime observation (consumed fingerprint, reload outcome, diagnostics).
  4. Enforces fail-closed cross-scope access control without leaking target existence.
  5. Implements auditable rollback by creating new desired revisions (append-only history).
  6. Binds observed configuration state and reload diagnostics to execution and audit evidence.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentv_runtime.config import (
    ConfigDiagnosticError,
    ConfigurationRevisionRecord,
    ConfigurationRevisionState,
    InstanceObservation,
    RuntimeWorkerConfigConsumer,
)

logger = logging.getLogger(__name__)

# Required scope keys for strict server-side context binding
REQUIRED_SCOPE_KEYS = ("org_id", "tenant_id", "workspace_id", "active_environment")


class ScopeAccessDeniedError(PermissionError):
    """Raised when cross-scope read/write access is attempted."""


class StaleRevisionError(ValueError):
    """Raised when an update/rollback references an outdated base revision."""


def derive_verified_scope(context: Mapping[str, Any]) -> dict[str, str]:
    """
    Extracts and strictly verifies the scope tuple from server-side context.
    Prevents browser or untrusted callers from injecting arbitrary tenant/org parameters.
    """
    scope: dict[str, str] = {}
    missing: list[str] = []

    for key in REQUIRED_SCOPE_KEYS:
        val = context.get(key)
        if not val or not isinstance(val, str) or not val.strip():
            missing.append(key)
        else:
            scope[key] = val.strip()

    if missing:
        raise ValueError(
            f"Missing required server-side scope parameters: {', '.join(missing)}. "
            "Scope must be authoritatively established by server context."
        )

    return scope


class ConfigurationRevisionService:
    """
    Authoritative server-side service for configuration revision consumption,
    rollout tracking, and Runtime observation.
    """

    def __init__(self, storage_root: Path | str | None = None) -> None:
        if storage_root is not None:
            self._root = Path(storage_root)
        else:
            base_dir = Path(os.getenv("AGENTV_CONFIG_DIR") or ".aes")
            self._root = base_dir / "revisions"
        self._lock = threading.Lock()

    def _scope_dir(self, scope: dict[str, str]) -> Path:
        """Returns the isolated directory path for a verified scope tuple."""
        # Sanitize scope components to prevent directory traversal
        sanitized_parts = [Path(scope[k]).name for k in REQUIRED_SCOPE_KEYS]
        return self._root.joinpath(*sanitized_parts)

    def _active_pointer_file(self, scope: dict[str, str]) -> Path:
        return self._scope_dir(scope) / ".active_revision.json"

    def _record_file(self, scope: dict[str, str], revision_id: str) -> Path:
        safe_id = Path(revision_id).name
        return self._scope_dir(scope) / f"{safe_id}.json"

    def accept_revision(
        self,
        context: Mapping[str, Any],
        desired_fingerprint: str,
        expected_base_revision_id: str | None = None,
        target_instances: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ConfigurationRevisionRecord:
        """
        Accepts a desired configuration revision for the verified server-side scope.
        Validates desired_fingerprint, checks optimistic concurrency, and enters PROVIDER_ACCEPTED.
        """
        scope = derive_verified_scope(context)

        if (
            not desired_fingerprint
            or not isinstance(desired_fingerprint, str)
            or not desired_fingerprint.strip()
        ):
            raise ValueError("desired_fingerprint must be a non-empty string identifier.")

        clean_fingerprint = desired_fingerprint.strip()

        with self._lock:
            s_dir = self._scope_dir(scope)
            s_dir.mkdir(parents=True, exist_ok=True)

            active_rec = self._load_active_revision_locked(scope)
            active_id = active_rec.revision_id if active_rec else None

            # Concurrency check against expected base revision
            if expected_base_revision_id is not None:
                if active_id != expected_base_revision_id:
                    raise StaleRevisionError(
                        f"Expected base revision '{expected_base_revision_id}' does not match "
                        f"current active revision '{active_id}' for scope."
                    )

            revision_id = f"rev_{uuid.uuid4().hex[:12]}"
            now_iso = datetime.now(UTC).isoformat()

            record = ConfigurationRevisionRecord(
                revision_id=revision_id,
                target_scope=dict(scope),
                desired_fingerprint=clean_fingerprint,
                status=ConfigurationRevisionState.PROVIDER_ACCEPTED.value,
                provider_acknowledged=False,
                expected_base_revision_id=expected_base_revision_id,
                previous_revision_id=active_id,
                target_instances=list(target_instances or []),
                instances={},
                diagnostics=[],
                created_at=now_iso,
                updated_at=now_iso,
                is_rollback=False,
                metadata=dict(metadata or {}),
            )

            rec_file = self._record_file(scope, revision_id)
            rec_file.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")
            logger.info("Configuration revision %s accepted for scope %s", revision_id, scope)
            return record

    def acknowledge_deployment(
        self,
        context: Mapping[str, Any],
        revision_id: str,
        provider_acknowledged: bool = True,
    ) -> ConfigurationRevisionRecord:
        """
        Records deployment provider acknowledgement.
        Transitions state from PROVIDER_ACCEPTED to DEPLOYED.
        """
        scope = derive_verified_scope(context)

        with self._lock:
            record = self._load_record_locked(scope, revision_id)
            if not record:
                raise ScopeAccessDeniedError(f"Revision '{revision_id}' not found in active scope.")

            record.provider_acknowledged = bool(provider_acknowledged)
            record.updated_at = datetime.now(UTC).isoformat()

            if (
                record.provider_acknowledged
                and record.status == ConfigurationRevisionState.PROVIDER_ACCEPTED.value
            ):
                record.status = ConfigurationRevisionState.DEPLOYED.value

            self._save_record_locked(scope, record)
            return record

    def record_instance_observation(
        self,
        context: Mapping[str, Any],
        revision_id: str,
        instance_id: str,
        consumed_fingerprint: str,
        reload_status: str = "reloaded",
        failure_reason: str | None = None,
        diagnostics: list[ConfigDiagnosticError] | None = None,
    ) -> ConfigurationRevisionRecord:
        """
        Records per-instance observation of a consumed revision.
        Aggregates observations across targeted instances into authoritative status:
          - OBSERVED: All target instances consumed desired fingerprint successfully.
          - PARTIALLY_APPLIED: Multi-instance mismatch, in-progress reload, or partial failure.
          - FAILED: All reporting instances failed reload or critical error.
        """
        scope = derive_verified_scope(context)

        if not instance_id or not isinstance(instance_id, str):
            raise ValueError("instance_id must be a non-empty string.")

        with self._lock:
            record = self._load_record_locked(scope, revision_id)
            if not record:
                raise ScopeAccessDeniedError(f"Revision '{revision_id}' not found in active scope.")

            now_iso = datetime.now(UTC).isoformat()
            obs = InstanceObservation(
                instance_id=instance_id.strip(),
                consumed_fingerprint=str(consumed_fingerprint or "").strip(),
                reload_status=reload_status,
                observed_at=now_iso,
                failure_reason=failure_reason,
                diagnostics=list(diagnostics or []),
            )
            record.instances[obs.instance_id] = obs
            record.updated_at = now_iso

            # Authoritative State Aggregation
            all_targets = set(record.target_instances)
            if not all_targets:
                # If no static target instances were declared, aggregate reporting instances
                all_targets = set(record.instances.keys())

            successful_targets: set[str] = set()
            failed_targets: set[str] = set()

            for t_id in all_targets:
                inst_obs = record.instances.get(t_id)
                if not inst_obs:
                    continue
                if (
                    inst_obs.consumed_fingerprint == record.desired_fingerprint
                    and inst_obs.reload_status in ("reloaded", "restarted")
                    and not inst_obs.failure_reason
                ):
                    successful_targets.add(t_id)
                elif (
                    inst_obs.reload_status == "failed"
                    or inst_obs.failure_reason
                    or (inst_obs.consumed_fingerprint != record.desired_fingerprint)
                ):
                    failed_targets.add(t_id)

            if len(successful_targets) == len(all_targets) and len(all_targets) > 0:
                record.status = ConfigurationRevisionState.OBSERVED.value
                # Update active revision pointer on full verified observation
                self._set_active_pointer_locked(scope, record)
            elif failed_targets:
                if successful_targets:
                    record.status = ConfigurationRevisionState.PARTIALLY_APPLIED.value
                else:
                    record.status = ConfigurationRevisionState.FAILED.value
            elif successful_targets and len(successful_targets) < len(all_targets):
                record.status = ConfigurationRevisionState.PARTIALLY_APPLIED.value
            else:
                if record.provider_acknowledged:
                    record.status = ConfigurationRevisionState.DEPLOYED.value

            self._save_record_locked(scope, record)
            return record

    def rollback(
        self,
        context: Mapping[str, Any],
        target_revision_id: str,
        expected_base_revision_id: str | None = None,
    ) -> ConfigurationRevisionRecord:
        """
        Rolls back configuration by creating a NEW auditable revision referencing
        the previous target's desired fingerprint.
        Never alters or overwrites historical records.
        """
        scope = derive_verified_scope(context)

        with self._lock:
            target_record = self._load_record_locked(scope, target_revision_id)
            if not target_record:
                raise ScopeAccessDeniedError(
                    f"Target revision '{target_revision_id}' not found in active scope."
                )

            active_rec = self._load_active_revision_locked(scope)
            active_id = active_rec.revision_id if active_rec else None

            if expected_base_revision_id is not None:
                if active_id != expected_base_revision_id:
                    raise StaleRevisionError(
                        f"Expected base revision '{expected_base_revision_id}' does not match "
                        f"current active revision '{active_id}' for rollback."
                    )

            now_iso = datetime.now(UTC).isoformat()
            new_id = f"rev_rb_{uuid.uuid4().hex[:10]}"

            rollback_record = ConfigurationRevisionRecord(
                revision_id=new_id,
                target_scope=dict(scope),
                desired_fingerprint=target_record.desired_fingerprint,
                status=ConfigurationRevisionState.PROVIDER_ACCEPTED.value,
                provider_acknowledged=False,
                expected_base_revision_id=expected_base_revision_id,
                previous_revision_id=active_id,
                target_instances=list(target_record.target_instances),
                instances={},
                diagnostics=[],
                created_at=now_iso,
                updated_at=now_iso,
                is_rollback=True,
                metadata={
                    "rollback_source_revision_id": target_revision_id,
                    "target_fingerprint": target_record.desired_fingerprint,
                },
            )

            self._save_record_locked(scope, rollback_record)
            logger.info(
                "Rollback revision %s created for scope %s pointing to fingerprint %s",
                new_id,
                scope,
                target_record.desired_fingerprint,
            )
            return rollback_record

    def get_revision(
        self,
        context: Mapping[str, Any],
        revision_id: str,
    ) -> ConfigurationRevisionRecord | None:
        """
        Retrieves a revision record for the verified scope.
        Fails closed with None if non-existent or cross-scope (prevents existence leakage).
        """
        try:
            scope = derive_verified_scope(context)
        except ValueError:
            return None

        with self._lock:
            return self._load_record_locked(scope, revision_id)

    def get_active_revision(
        self,
        context: Mapping[str, Any],
    ) -> ConfigurationRevisionRecord | None:
        """Retrieves the currently active (verified OBSERVED) revision for the scope."""
        try:
            scope = derive_verified_scope(context)
        except ValueError:
            return None

        with self._lock:
            return self._load_active_revision_locked(scope)

    def get_pending_or_active_revision(
        self,
        context: Mapping[str, Any],
        instance_id: str | None = None,
    ) -> ConfigurationRevisionRecord | None:
        """
        Retrieves the latest revision requiring observation by this worker instance,
        or falls back to the active revision for the verified scope.
        """
        try:
            scope = derive_verified_scope(context)
        except ValueError:
            return None

        revisions = self.list_revisions(scope)
        for rev in revisions:
            if rev.status in (
                ConfigurationRevisionState.DEPLOYED.value,
                ConfigurationRevisionState.PROVIDER_ACCEPTED.value,
                ConfigurationRevisionState.PARTIALLY_APPLIED.value,
            ):
                if (
                    not instance_id
                    or not rev.target_instances
                    or instance_id in rev.target_instances
                ):
                    return rev
        return self.get_active_revision(scope)

    def list_revisions(
        self,
        context: Mapping[str, Any],
    ) -> list[ConfigurationRevisionRecord]:
        """Lists all revisions within the caller's verified scope, sorted newest first."""
        try:
            scope = derive_verified_scope(context)
        except ValueError:
            return []

        with self._lock:
            s_dir = self._scope_dir(scope)
            if not s_dir.exists():
                return []

            recs: list[ConfigurationRevisionRecord] = []
            for f in s_dir.glob("rev_*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    rec = ConfigurationRevisionRecord.from_dict(data)
                    # Verify scope match
                    if rec.target_scope == scope:
                        recs.append(rec)
                except Exception:
                    continue

            recs.sort(key=lambda r: r.created_at, reverse=True)
            return recs

    def get_deployment_adapter(self) -> RuntimeDeploymentProviderAdapter:
        """Returns a deployment provider adapter wired to this revision service."""
        return RuntimeDeploymentProviderAdapter(self)

    # Internal helpers (called while holding self._lock)
    def _load_record_locked(
        self,
        scope: dict[str, str],
        revision_id: str,
    ) -> ConfigurationRevisionRecord | None:
        rf = self._record_file(scope, revision_id)
        if not rf.exists():
            return None
        try:
            data = json.loads(rf.read_text(encoding="utf-8"))
            rec = ConfigurationRevisionRecord.from_dict(data)
            if rec.target_scope != scope:
                return None
            return rec
        except Exception:
            return None

    def _save_record_locked(
        self,
        scope: dict[str, str],
        record: ConfigurationRevisionRecord,
    ) -> None:
        s_dir = self._scope_dir(scope)
        s_dir.mkdir(parents=True, exist_ok=True)
        rf = self._record_file(scope, record.revision_id)
        rf.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")

    def _load_active_revision_locked(
        self,
        scope: dict[str, str],
    ) -> ConfigurationRevisionRecord | None:
        ptr = self._active_pointer_file(scope)
        if not ptr.exists():
            return None
        try:
            data = json.loads(ptr.read_text(encoding="utf-8"))
            active_id = data.get("active_revision_id")
            if not active_id:
                return None
            return self._load_record_locked(scope, active_id)
        except Exception:
            return None

    def _set_active_pointer_locked(
        self,
        scope: dict[str, str],
        record: ConfigurationRevisionRecord,
    ) -> None:
        ptr = self._active_pointer_file(scope)
        ptr.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "active_revision_id": record.revision_id,
            "desired_fingerprint": record.desired_fingerprint,
            "status": record.status,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        ptr.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def bind_revision_to_evidence(
    manifest_or_evidence: dict[str, Any],
    revision: ConfigurationRevisionRecord,
) -> dict[str, Any]:
    """
    Binds observed configuration revision metadata, fingerprints, and instance reload status
    to an ExecutionManifest or EvidencePackage dict for audit defensibility.
    """
    manifest_or_evidence["config_revision"] = {
        "revision_id": revision.revision_id,
        "desired_fingerprint": revision.desired_fingerprint,
        "status": revision.status,
        "provider_acknowledged": revision.provider_acknowledged,
        "target_scope": dict(revision.target_scope),
        "instances": {k: v.to_dict() for k, v in revision.instances.items()},
        "diagnostics": [
            d.to_dict() if hasattr(d, "to_dict") else dict(d) for d in revision.diagnostics
        ],
        "is_rollback": revision.is_rollback,
    }
    return manifest_or_evidence


class RuntimeDeploymentProviderAdapter:
    """
    Generic deployment provider adapter for coordinating configuration revision
    rollouts across Runtime worker instances and tracking observation lifecycle.
    """

    def __init__(self, service: ConfigurationRevisionService | None = None) -> None:
        self.service = service or ConfigurationRevisionService()

    def deploy_and_observe(
        self,
        context: Mapping[str, Any],
        revision_id: str,
        workers: list[RuntimeWorkerConfigConsumer],
        config_payload: dict[str, Any] | None = None,
        mandates: dict[str, Any] | None = None,
    ) -> ConfigurationRevisionRecord:
        """
        Coordinates full deployment and observation:
          1. Submits deployment acknowledgement to provider (transitions to DEPLOYED).
          2. Dispatches desired revision to workers for reload.
          3. Collects and records per-instance observations into ConfigurationRevisionService.
          4. Returns authoritative aggregated record (OBSERVED, PARTIALLY_APPLIED, or FAILED).
        """
        # 1. Acknowledge deployment
        record = self.service.acknowledge_deployment(
            context, revision_id, provider_acknowledged=True
        )

        # 2. Dispatch to workers and record observation
        for worker in workers:
            obs = worker.consume_and_reload(
                record,
                config_dict=config_payload,
                mandates=mandates,
            )
            record = self.service.record_instance_observation(
                context=context,
                revision_id=revision_id,
                instance_id=obs.instance_id,
                consumed_fingerprint=obs.consumed_fingerprint,
                reload_status=obs.reload_status,
                failure_reason=obs.failure_reason,
                diagnostics=obs.diagnostics,
            )

        return record

    def report_worker_observation(
        self,
        context: Mapping[str, Any],
        revision_id: str,
        observation: InstanceObservation,
    ) -> ConfigurationRevisionRecord:
        """
        Directly registers an externally reported Runtime worker observation into the service.
        """
        return self.service.record_instance_observation(
            context=context,
            revision_id=revision_id,
            instance_id=observation.instance_id,
            consumed_fingerprint=observation.consumed_fingerprint,
            reload_status=observation.reload_status,
            failure_reason=observation.failure_reason,
            diagnostics=observation.diagnostics,
        )

    def get_pending_or_active_revision(
        self,
        context: Mapping[str, Any],
        instance_id: str | None = None,
    ) -> ConfigurationRevisionRecord | None:
        """
        Retrieves the latest revision requiring observation by this worker instance,
        or falls back to the active revision for the verified scope.
        """
        return self.service.get_pending_or_active_revision(context, instance_id=instance_id)
