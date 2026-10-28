import asyncio
import hashlib
import logging
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from agentv_runtime.interfaces import (
    ApprovalRequest,
    ApprovalStore,
    MandatoryScopeMissingError,
    ScopeMismatchError,
)
from agentv_runtime.scope import ScopeToken, get_active_scope_policy
from eval_runner.runtime_services import resolve_approval_store

logger = logging.getLogger(__name__)


class ApprovalBoundaryRejected(PermissionError):
    """A policy rejection at the durable HITL boundary.

    This is deliberately distinct from an ordinary permission error so the
    execution layer can emit a terminal, root-cause-marked evidence event
    rather than presenting the run as waiting for a human decision.
    """

    def __init__(
        self,
        reason: str,
        *,
        phase: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(reason)
        self.phase = phase
        self.details = dict(details or {})


def _provider_context(scope: ScopeToken | Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Normalize scope values before passing them to a storage provider."""
    if isinstance(scope, ScopeToken):
        return dict(scope.tags)
    if isinstance(scope, Mapping):
        return dict(scope)
    return None


class SessionApprovalManager:
    """Coordinates Human-In-The-Loop approval gates, tokens, and pause state."""

    def __init__(
        self,
        run_id: str,
        checkpoint_manager: Any | None = None,
        state_provider: Any | None = None,
        plugin_manager: Any | None = None,
        approval_store: ApprovalStore | None = None,
        event_bus: Any | None = None,
        scope: ScopeToken | None = None,
        run_store: Any | None = None,
    ):
        self.run_id = run_id
        self.checkpoint_manager = checkpoint_manager
        self.state_provider = state_provider
        self.plugin_manager = plugin_manager
        self._approval_store = approval_store
        self.event_bus = event_bus
        self.scope = scope
        self.run_store = run_store

    @property
    def approval_store(self) -> ApprovalStore:
        if self._approval_store is None:
            self._approval_store = resolve_approval_store()
        return self._approval_store

    def create_durable_request(
        self,
        turn_index: int,
        outbound_payload_hash: str = "",
        required_role: str | None = None,
        reviewer_credentials: dict[str, Any] | None = None,
        rule_id: str | None = None,
        action_payload: dict[str, Any] | None = None,
        prompt: str | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        manifest_id: str | None = None,
    ) -> ApprovalRequest:
        """
        Creates a durable ApprovalRequest, snapshots state into a checkpoint with
        PAUSED_FOR_APPROVAL status, and persists the record to the ApprovalStore.
        Binds verified ScopeToken across execution manifest, run index, checkpoint,
        and persisted approval record.
        """
        meta = dict(metadata or {})
        task_id = meta.get("task_id", "unknown")

        # 1. Resolve active ScopePolicy
        policy = get_active_scope_policy()

        # 2. Extract / resolve candidate scope
        candidate_scope: ScopeToken | None = None
        if isinstance(meta.get("scope_token"), ScopeToken):
            candidate_scope = meta["scope_token"]
        elif self.scope is not None:
            candidate_scope = self.scope
        else:
            raw_ctx = meta.get("runtime_context") or meta.get("context") or meta.get("scope")
            if not raw_ctx and callable(self.state_provider):
                try:
                    st = self.state_provider()
                    if isinstance(st, dict):
                        st_meta = st.get("metadata") or {}
                        raw_ctx = (
                            st_meta.get("runtime_context")
                            or st_meta.get("context")
                            or st_meta.get("scope")
                            or st.get("scenario_data", {}).get("runtime_context")
                            or st.get("scenario_data", {}).get("context")
                        )
                except Exception as exc:
                    logger.debug("Failed checking state_provider for scope: %s", exc)
            if not raw_ctx and self.run_store is not None:
                try:
                    m = self.run_store.get_manifest(self.run_id, context=raw_ctx)
                    if m and isinstance(m.get("context"), Mapping):
                        raw_ctx = m["context"]
                except Exception as exc:
                    logger.debug("Failed checking injected run_store for scope: %s", exc)

            if isinstance(raw_ctx, ScopeToken):
                candidate_scope = raw_ctx
            elif isinstance(raw_ctx, Mapping):
                candidate_scope = ScopeToken.from_tags(raw_ctx)

        # 3. Enforce mandatory scope if required by policy
        is_mandatory = False
        try:
            is_mandatory = policy.is_scope_mandatory()
        except Exception as exc:
            logger.debug("Failed querying policy.is_scope_mandatory: %s", exc)

        if is_mandatory:
            if candidate_scope is None or not candidate_scope.digest:
                raise MandatoryScopeMissingError(
                    f"MandatoryScopeMissing: Cannot persist durable approval pause for "
                    f"run '{self.run_id}' without verified scope."
                )

        if candidate_scope is not None and candidate_scope.digest:
            policy.validate_scope(candidate_scope)
            verified_token = candidate_scope
        else:
            verified_token = ScopeToken(tags={}, digest="", is_system=False)

        scope = dict(verified_token.tags)
        scope_digest = verified_token.digest

        if not outbound_payload_hash and action_payload:
            payload_str = str(sorted(action_payload.items()))
            outbound_payload_hash = hashlib.sha3_256(payload_str.encode("utf-8")).hexdigest()

        if not idempotency_key:
            idempotency_key = meta.get("idempotency_key") or (
                f"{self.run_id}:{turn_index}:{rule_id or 'default'}:"
                f"{outbound_payload_hash[:16] if outbound_payload_hash else 'pause'}"
            )

        # Durable approvals are the authoritative HITL boundary.
        # Pass through the interceptor before checkpoint or token creation.
        if self.plugin_manager:
            approval_data = {
                "task_id": task_id,
                "turn_index": turn_index,
                "required_role": required_role,
                "action_payload": action_payload or {},
                "metadata": meta,
                "durable": True,
                "scope": scope,
                "scope_digest": scope_digest,
                "idempotency_key": idempotency_key,
            }
            intercept = self.plugin_manager.trigger_interceptor(
                "on_approval_request", self, approval_data
            )
            if intercept is False or (
                isinstance(intercept, dict) and intercept.get("allowed") is False
            ):
                plugin_reason = getattr(self.plugin_manager, "last_rejection_reason", None)
                err_msg = (
                    (plugin_reason if isinstance(plugin_reason, str) and plugin_reason else None)
                    or (intercept.get("error") if isinstance(intercept, dict) else None)
                    or "Durable approval rejected by security policy"
                )
                raise ApprovalBoundaryRejected(
                    err_msg,
                    phase="request",
                    details=getattr(self.plugin_manager, "last_rejection_details", None),
                )

        token = secrets.token_urlsafe(24)
        created_at = datetime.now(UTC)
        resolved_manifest_id = manifest_id or meta.get("manifest_id")

        # The execution provider owns both the manifest and lifecycle state.
        # Approval handling may validate immutable scope, but must never
        # recover or mutate a local run projection.
        if self.run_store is None:
            raise RuntimeError(
                "RunStorageProviderBindingRequired: approval lifecycle requires "
                f"the execution owner's provider for '{self.run_id}'."
            )
        provider_context = _provider_context(scope)
        try:
            # Scope must establish ownership before an approval credential is
            # created.  An empty manifest is not proof that an out-of-scope
            # run may receive a durable approval record.
            if self.run_store.get_run(self.run_id, context=provider_context) is None:
                raise RuntimeError(
                    "RunStorageProviderScopeViolation: approval run is unavailable "
                    "from the supplied provider scope."
                )
            store_manifest = (
                self.run_store.get_manifest(self.run_id, context=provider_context) or {}
            )
            execution_manifest = store_manifest.get("execution_manifest")
            if not isinstance(execution_manifest, Mapping):
                execution_manifest = {}
            resolved_manifest_id = resolved_manifest_id or execution_manifest.get("manifest_id")
            manifest_digest = execution_manifest.get("scope_digest", "")
            if manifest_digest and scope_digest and manifest_digest != scope_digest:
                raise ScopeMismatchError(
                    "Scope digest mismatch between provider execution manifest "
                    f"({manifest_digest}) and approval ({scope_digest})."
                )
        except ScopeMismatchError:
            raise
        except RuntimeError as exc:
            if str(exc).startswith("RunStorageProviderScopeViolation:"):
                raise
            raise RuntimeError(
                "RunStorageProviderBindingRequired: approval scope could not be "
                f"validated for '{self.run_id}'."
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                "RunStorageProviderBindingRequired: approval scope could not be "
                f"validated for '{self.run_id}'."
            ) from exc
        resolved_manifest_id = resolved_manifest_id or f"man_{self.run_id}"

        # 2. Checkpoint
        checkpoint_id = None
        if self.checkpoint_manager:
            checkpoint_state = {
                "turn": turn_index,
                "task_id": task_id,
                "prompt": prompt,
                "status": "PAUSED_FOR_APPROVAL",
                "approval_token": token,
                "action_payload": action_payload or {},
                "scope": scope,
                "scope_digest": scope_digest,
                "manifest_id": resolved_manifest_id,
                "idempotency_key": idempotency_key,
            }
            if callable(self.state_provider):
                try:
                    state_data = self.state_provider()
                    if isinstance(state_data, dict):
                        checkpoint_state.update(state_data)
                except Exception as exc:
                    logger.debug("Failed extracting state snapshot for durable approval: %s", exc)
            checkpoint_id = self.checkpoint_manager.create_checkpoint(
                checkpoint_state,
                metadata={
                    "hitl_gate": True,
                    "task_id": task_id,
                    "status": "PAUSED_FOR_APPROVAL",
                    "approval_token": token,
                    "turn": turn_index,
                    "rule_id": rule_id,
                    "scope": scope,
                    "scope_digest": scope_digest,
                    "manifest_id": resolved_manifest_id,
                    "idempotency_key": idempotency_key,
                },
            )

        # 3. Persisted Approval Record
        req = ApprovalRequest(
            approval_token=token,
            run_id=self.run_id,
            turn_index=turn_index,
            outbound_payload_hash=outbound_payload_hash,
            required_role=required_role,
            reviewer_credentials=reviewer_credentials or {},
            status="PENDING",
            rule_id=rule_id,
            checkpoint_id=checkpoint_id,
            action_payload=action_payload or {},
            prompt=prompt or f"Approval required for run '{self.run_id}' turn {turn_index}",
            metadata=meta,
            scope=scope,
            scope_digest=scope_digest,
            manifest_id=resolved_manifest_id,
            idempotency_key=idempotency_key,
            created_at=created_at,
        )
        persisted = self.approval_store.create_request(req)

        # Emit the approval evidence while the run remains writable.  The
        # session emits HITL_PAUSE immediately afterwards and only then
        # transitions the provider record to PAUSED_FOR_APPROVAL.  Reversing
        # that order drops both events because a paused run rejects trace
        # writes, leaving the debugger's last graph node as RUNNING.
        # Trigger on_approval_created hook (best-effort, fail-safe)
        if self.plugin_manager:
            try:
                self.plugin_manager.trigger("on_approval_created", self, persisted)
            except Exception as exc:
                logger.warning(
                    "[SessionApprovalManager] Plugin hook on_approval_created failed: %s",
                    exc,
                )

        # Emit CoreEvents.APPROVAL_CREATED event (best-effort, fail-safe)
        try:
            from eval_runner.events import CoreEvents, EventEmitter

            bus = self.event_bus or EventEmitter.get_global()
            bus.emit(CoreEvents.APPROVAL_CREATED, persisted.to_dict())
        except Exception as exc:
            logger.warning(
                "[SessionApprovalManager] Failed to emit APPROVAL_CREATED event: %s",
                exc,
            )

        return persisted

    def resolve_durable_request(
        self,
        approval_token: str,
        decision: str,
        decided_by: str | None = None,
        decision_reason: str | None = None,
        scope: ScopeToken | None = None,
    ) -> ApprovalRequest:
        """Resolves a durable approval request in the persistent store."""
        active_scope = scope or self.scope
        if self.plugin_manager:
            pending = self.approval_store.get_request(approval_token, scope=active_scope)
            approval_data = {
                "approval_token": approval_token,
                "decision": decision,
                "decided_by": decided_by,
                "decision_reason": decision_reason,
                "durable": True,
                "phase": "resolution",
            }
            if pending is not None:
                approval_data.update(
                    {
                        "task_id": pending.metadata.get("task_id", "unknown"),
                        "required_role": pending.required_role,
                        "action_payload": pending.action_payload,
                        "metadata": pending.metadata,
                        "scope": dict(pending.scope),
                        "scope_digest": pending.scope_digest,
                    }
                )
            intercept = self.plugin_manager.trigger_interceptor(
                "on_approval_resolution", self, approval_data
            )
            if intercept is False or (
                isinstance(intercept, dict) and intercept.get("allowed") is False
            ):
                plugin_reason = getattr(self.plugin_manager, "last_rejection_reason", None)
                err_msg = (
                    (plugin_reason if isinstance(plugin_reason, str) and plugin_reason else None)
                    or (intercept.get("error") if isinstance(intercept, dict) else None)
                    or "Durable approval resolution rejected by security policy"
                )
                raise ApprovalBoundaryRejected(
                    err_msg,
                    phase="resolution",
                    details=getattr(self.plugin_manager, "last_rejection_details", None),
                )

        resolved = self.approval_store.resolve_request(
            approval_token=approval_token,
            decision=decision,
            decided_by=decided_by,
            decision_reason=decision_reason,
            scope=active_scope,
        )

        # Approval resolution is part of the run's evidence stream.  Reopen
        # only an approved run, through its bound provider, before emitting
        # that event; a paused provider correctly rejects ordinary trace
        # writes.  Rejected decisions remain durably recorded in the approval
        # ledger and leave the execution trace closed.
        if str(resolved.status).upper() == "APPROVED" and self.run_store is not None:
            from eval_runner.flight_recorder import FlightRecorderPlugin
            from eval_runner.run_lifecycle import RunLifecycleState, transition_run_lifecycle

            run_context = _provider_context(active_scope)
            FlightRecorderPlugin.bind_active_recorder(
                self.run_id, self.run_store, context=run_context
            )
            transition_run_lifecycle(
                self.run_id,
                RunLifecycleState.OPEN,
                run_store=self.run_store,
                context=run_context,
            )

        # Trigger on_approval_resolved hook (best-effort, fail-safe)
        if self.plugin_manager:
            try:
                self.plugin_manager.trigger("on_approval_resolved", self, resolved)
            except Exception as exc:
                logger.warning(
                    "[SessionApprovalManager] Plugin hook on_approval_resolved failed: %s",
                    exc,
                )

        # A rejected request leaves the run paused/closed.  Its authoritative
        # approval-ledger record is retained, but it must not cause a trace
        # append that would violate the paused lifecycle.
        try:
            from eval_runner.events import CoreEvents, EventEmitter

            bus = self.event_bus or EventEmitter.get_global()
            bus.emit(CoreEvents.APPROVAL_RESOLVED, resolved.to_dict())
        except Exception as exc:
            logger.warning(
                "[SessionApprovalManager] Failed to emit APPROVAL_RESOLVED event: %s",
                exc,
            )

        return resolved

    def get_durable_request(
        self, approval_token: str, scope: ScopeToken | None = None
    ) -> ApprovalRequest | None:
        """Retrieves a durable approval request by token, optionally filtering by scope."""
        return self.approval_store.get_request(approval_token, scope=scope or self.scope)

    def list_durable_pending(self, scope: ScopeToken | None = None) -> list[ApprovalRequest]:
        """Lists active pending approval requests for this run, optionally filtering by scope."""
        return self.approval_store.list_pending(self.run_id, scope=scope or self.scope)

    async def wait_for_durable_resolution(
        self,
        approval_token: str,
        *,
        timeout_seconds: float,
        poll_seconds: float = 0.25,
    ) -> ApprovalRequest:
        """Wait for the authoritative ApprovalStore record to leave PENDING.

        The store remains the durable authority across process restarts.  A
        provider may later override this bounded polling implementation with a
        native stream without changing session semantics.
        """
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            request = self.get_durable_request(approval_token)
            if request is None:
                raise LookupError(f"Approval request '{approval_token}' is unavailable")
            if str(request.status).upper() != "PENDING":
                return request
            if asyncio.get_running_loop().time() >= deadline:
                return self.resolve_durable_request(
                    approval_token,
                    "REJECTED",
                    decided_by="system_timeout",
                    decision_reason="Approval window expired",
                )
            await asyncio.sleep(poll_seconds)
