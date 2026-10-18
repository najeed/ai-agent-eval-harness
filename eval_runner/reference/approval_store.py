"""
eval_runner.reference.approval_store
Reference storage implementations for the ApprovalStore contract (HITL Queue).
Neutral, lightweight, zero-dependency implementations.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentv_runtime.interfaces import (
    ApprovalEvent,
    ApprovalRequest,
    ApprovalStorageDegradedError,
    ApprovalStore,
    ScopeMismatchError,
)
from agentv_runtime.scope import ScopeToken
from eval_runner import config

logger = logging.getLogger(__name__)


def _matches_scope(req: ApprovalRequest, scope: ScopeToken | None) -> bool:
    """Helper to verify whether an approval request is accessible by the given scope."""
    if scope is None:
        return True
    if scope.is_system:
        return True
    if req.is_legacy_unscoped:
        # Unscoped legacy approvals must NOT appear in a tenant queue
        return False
    if req.scope_digest and scope.digest:
        return req.scope_digest == scope.digest
    req_token = ScopeToken.from_tags(req.scope_tags)
    return req_token.matches(scope)


class FileApprovalStore(ApprovalStore):
    """
    Lightweight, atomic, zero-dependency file-based approval queue store.
    Persists approval records to local JSON files in .agentv/approvals/<run_id>.json.
    """

    def __init__(self, base_dir: Path | str | None = None):
        if base_dir is None:
            configured_dir = os.getenv("AGENTV_APPROVALS_DIR")
            if configured_dir:
                self.base_dir = Path(configured_dir).resolve()
            else:
                self.base_dir = (config.PROJECT_ROOT / ".agentv" / "approvals").resolve()
        else:
            self.base_dir = Path(base_dir).resolve()

        self._lock = threading.Lock()
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.debug("Failed creating approval base dir: %s", exc)

    def _atomic_write(self, target_path: Path, data: dict[str, Any]) -> None:
        self._ensure_dir()
        temp_path = target_path.with_suffix(".tmp")
        payload_bytes = json.dumps(data, indent=2, sort_keys=True, default=str).encode("utf-8")
        try:
            with open(temp_path, "wb") as f:
                f.write(payload_bytes)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, target_path)
        except OSError as exc:
            raise ApprovalStorageDegradedError(
                f"Failed writing approval record to '{target_path}': {exc}"
            ) from exc

    def create_request(self, request: ApprovalRequest) -> ApprovalRequest:
        with self._lock:
            data = request.to_dict()
            # 1. Primary persistence: <run_id>.json
            run_file = self.base_dir / f"{request.run_id}.json"
            self._atomic_write(run_file, data)

            # 2. Token index file: token_<approval_token>.json for O(1) lookup
            token_file = self.base_dir / f"token_{request.approval_token}.json"
            self._atomic_write(token_file, data)

            return request

    def get_request(
        self, approval_token: str, scope: ScopeToken | None = None
    ) -> ApprovalRequest | None:
        if not approval_token:
            return None
        with self._lock:
            # 1. Fast O(1) path via token file
            token_file = self.base_dir / f"token_{approval_token}.json"
            if token_file.exists():
                try:
                    with open(token_file, encoding="utf-8") as f:
                        data = json.load(f)
                    req = ApprovalRequest.from_dict(data)
                    return req if _matches_scope(req, scope) else None
                except (json.JSONDecodeError, OSError) as exc:
                    logger.debug(
                        "Error reading token file %s: %s, falling back to scan",
                        token_file,
                        exc,
                    )

            # 2. Fallback scan of run files
            try:
                for file_path in self.base_dir.glob("*.json"):
                    if file_path.name.startswith("token_") or file_path.name.endswith(".tmp"):
                        continue
                    try:
                        with open(file_path, encoding="utf-8") as f:
                            data = json.load(f)
                        if data.get("approval_token") == approval_token:
                            req = ApprovalRequest.from_dict(data)
                            return req if _matches_scope(req, scope) else None
                    except (json.JSONDecodeError, OSError):
                        continue
            except OSError as scan_exc:
                if scope is not None:
                    raise ApprovalStorageDegradedError(
                        f"Error scanning approval directory '{self.base_dir}': {scan_exc}"
                    ) from scan_exc
                logger.debug("Error scanning approval directory: %s", scan_exc)

            return None

    def get_request_by_run_id(
        self, run_id: str, scope: ScopeToken | None = None
    ) -> ApprovalRequest | None:
        if not run_id:
            return None
        with self._lock:
            run_file = self.base_dir / f"{run_id}.json"
            if run_file.exists():
                try:
                    with open(run_file, encoding="utf-8") as f:
                        data = json.load(f)
                    req = ApprovalRequest.from_dict(data)
                    return req if _matches_scope(req, scope) else None
                except (json.JSONDecodeError, OSError) as exc:
                    logger.debug("Error reading run approval file %s: %s", run_file, exc)
                    if scope is not None:
                        raise ApprovalStorageDegradedError(
                            f"Corrupt or unreadable run approval file '{run_file}': {exc}"
                        ) from exc
            return None

    def resolve_request(
        self,
        approval_token: str,
        decision: str,
        decided_by: str | None = None,
        decision_reason: str | None = None,
        scope: ScopeToken | None = None,
    ) -> ApprovalRequest:
        normalized_decision = decision.upper().strip()
        if normalized_decision not in ("APPROVED", "REJECTED"):
            raise ValueError(
                f"Invalid approval decision '{decision}'. Must be 'APPROVED' or 'REJECTED'."
            )

        with self._lock:
            token_file = self.base_dir / f"token_{approval_token}.json"
            if not token_file.exists():
                raise KeyError(f"Approval request for token '{approval_token}' not found.")
            try:
                with open(token_file, encoding="utf-8") as f:
                    req = ApprovalRequest.from_dict(json.load(f))
            except (json.JSONDecodeError, OSError) as exc:
                raise ApprovalStorageDegradedError(
                    f"Corrupt or unreadable token file '{token_file}': {exc}"
                ) from exc

            if scope is not None:
                if req.is_legacy_unscoped and not scope.is_system:
                    raise ScopeMismatchError(
                        f"Approval request for token '{approval_token}' is UNSCOPED_LEGACY "
                        "and cannot be resolved by tenant scope."
                    )
                if not _matches_scope(req, scope):
                    raise ScopeMismatchError(
                        f"Scope mismatch: active scope cannot resolve approval '{approval_token}'."
                    )

            if req.status != "PENDING":
                raise ValueError(
                    f"Approval request for token '{approval_token}' is already resolved."
                )
            req.status = normalized_decision
            req.decision = normalized_decision
            req.decision_reason = decision_reason or (
                "Approved via review gate"
                if normalized_decision == "APPROVED"
                else "Rejected via review gate"
            )
            req.decided_by = decided_by or "system"
            req.decided_at = time.time()

            data = req.to_dict()
            run_file = self.base_dir / f"{req.run_id}.json"
            self._atomic_write(run_file, data)
            token_file = self.base_dir / f"token_{req.approval_token}.json"
            self._atomic_write(token_file, data)

            return req

    def list_pending(
        self, run_id: str | None = None, scope: ScopeToken | None = None
    ) -> list[ApprovalRequest]:
        pending: list[ApprovalRequest] = []
        with self._lock:
            try:
                file_paths = list(self.base_dir.glob("token_*.json"))
            except OSError as scan_exc:
                if scope is not None:
                    raise ApprovalStorageDegradedError(
                        f"Error scanning approval directory '{self.base_dir}': {scan_exc}"
                    ) from scan_exc
                logger.debug("Error listing pending approvals: %s", scan_exc)
                return []

            for file_path in file_paths:
                try:
                    with open(file_path, encoding="utf-8") as f:
                        data = json.load(f)
                    req = ApprovalRequest.from_dict(data)
                except (json.JSONDecodeError, OSError) as exc:
                    if scope is not None:
                        raise ApprovalStorageDegradedError(
                            f"Failed parsing pending approval file '{file_path}': {exc}"
                        ) from exc
                    logger.debug("Error parsing pending file %s: %s", file_path, exc)
                    continue

                if req.status == "PENDING":
                    if run_id is None or req.run_id == run_id:
                        if _matches_scope(req, scope):
                            pending.append(req)

        return pending

    def delete_request(self, approval_token: str, scope: ScopeToken | None = None) -> bool:
        req = self.get_request(approval_token, scope=scope)
        if not req:
            return False
        with self._lock:
            deleted = False
            token_file = self.base_dir / f"token_{approval_token}.json"
            if token_file.exists():
                try:
                    token_file.unlink()
                    deleted = True
                except OSError as exc:
                    logger.debug("Error unlinking token file %s: %s", token_file, exc)

            run_file = self.base_dir / f"{req.run_id}.json"
            if run_file.exists():
                try:
                    run_file.unlink()
                    deleted = True
                except OSError as exc:
                    logger.debug("Error unlinking run file %s: %s", run_file, exc)
            return deleted

    get = get_request

    def stream_pending(self, scope: ScopeToken | None = None) -> Iterator[ApprovalEvent]:
        for req in self.list_pending(scope=scope):
            yield ApprovalEvent(event_type="PENDING", request=req)


class SQLiteApprovalStore(ApprovalStore):
    """
    Durable SQLite-backed approval store for Core Runtime HITL queues.
    Zero-dependency, multi-process safe with table migration and indexing.
    """

    def __init__(self, db_path: Path | str | None = None):
        if db_path is None:
            configured_db = os.getenv("AGENTV_APPROVALS_DB")
            if configured_db:
                self.db_path = Path(configured_db).resolve()
            else:
                self.db_path = (config.PROJECT_ROOT / ".agentv" / "approvals.db").resolve()
        else:
            self.db_path = Path(db_path).resolve()

        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with closing(self._get_connection()) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS approval_requests (
                            approval_token TEXT PRIMARY KEY,
                            run_id TEXT NOT NULL,
                            turn_index INTEGER NOT NULL,
                            outbound_payload_hash TEXT NOT NULL,
                            required_role TEXT,
                            reviewer_credentials TEXT,
                            status TEXT NOT NULL,
                            rule_id TEXT,
                            checkpoint_id TEXT,
                            action_payload TEXT,
                            prompt TEXT,
                            created_at REAL,
                            decision TEXT,
                            decision_reason TEXT,
                            decided_by TEXT,
                            decided_at REAL,
                            metadata TEXT,
                            scope_tags TEXT,
                            scope_digest TEXT,
                            manifest_id TEXT,
                            idempotency_key TEXT
                        )
                    """)
                    for col in ("scope_tags", "scope_digest", "manifest_id", "idempotency_key"):
                        try:
                            cursor.execute(f"ALTER TABLE approval_requests ADD COLUMN {col} TEXT")
                        except sqlite3.OperationalError:
                            pass
                    cursor.execute(
                        "CREATE INDEX IF NOT EXISTS idx_approval_run_id "
                        "ON approval_requests(run_id)"
                    )
                    cursor.execute(
                        "CREATE INDEX IF NOT EXISTS idx_approval_status "
                        "ON approval_requests(status)"
                    )
                    cursor.execute(
                        "CREATE INDEX IF NOT EXISTS idx_approval_scope_digest "
                        "ON approval_requests(scope_digest)"
                    )
                    cursor.execute(
                        "CREATE INDEX IF NOT EXISTS idx_approval_idempotency_key "
                        "ON approval_requests(idempotency_key)"
                    )
                    conn.commit()
        except Exception as e:
            logger.error("Failed to initialize SQLite Approval Database: %s", e)
            raise ApprovalStorageDegradedError(
                f"Failed to initialize SQLite Approval Database at '{self.db_path}': {e}"
            ) from e

    def _row_to_request(self, row: tuple) -> ApprovalRequest:
        scope_tags = {}
        scope_digest = ""
        manifest_id = None
        idempotency_key = None
        if len(row) >= 21:
            scope_tags = json.loads(row[17]) if row[17] else {}
            scope_digest = str(row[18] or "")
            manifest_id = row[19]
            idempotency_key = row[20]

        return ApprovalRequest(
            approval_token=row[0],
            run_id=row[1],
            turn_index=row[2],
            outbound_payload_hash=row[3],
            required_role=row[4],
            reviewer_credentials=json.loads(row[5]) if row[5] else {},
            status=row[6],
            rule_id=row[7],
            checkpoint_id=row[8],
            action_payload=json.loads(row[9]) if row[9] else {},
            prompt=row[10],
            created_at=row[11],
            decision=row[12],
            decision_reason=row[13],
            decided_by=row[14],
            decided_at=row[15],
            metadata=json.loads(row[16]) if row[16] else {},
            scope_tags=scope_tags,
            scope_digest=scope_digest,
            manifest_id=manifest_id,
            idempotency_key=idempotency_key,
        )

    def create_request(self, request: ApprovalRequest) -> ApprovalRequest:
        with self._lock:
            try:
                with closing(self._get_connection()) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        INSERT INTO approval_requests (
                            approval_token, run_id, turn_index, outbound_payload_hash,
                            required_role, reviewer_credentials, status, rule_id,
                            checkpoint_id, action_payload, prompt, created_at,
                            decision, decision_reason, decided_by, decided_at, metadata,
                            scope_tags, scope_digest, manifest_id, idempotency_key
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(approval_token) DO UPDATE SET
                            status=excluded.status,
                            decision=excluded.decision,
                            decision_reason=excluded.decision_reason,
                            decided_by=excluded.decided_by,
                            decided_at=excluded.decided_at,
                            metadata=excluded.metadata,
                            scope_tags=excluded.scope_tags,
                            scope_digest=excluded.scope_digest,
                            manifest_id=excluded.manifest_id,
                            idempotency_key=excluded.idempotency_key
                        """,
                        (
                            request.approval_token,
                            request.run_id,
                            request.turn_index,
                            request.outbound_payload_hash,
                            request.required_role,
                            json.dumps(request.reviewer_credentials),
                            request.status,
                            request.rule_id,
                            request.checkpoint_id,
                            json.dumps(request.action_payload),
                            request.prompt,
                            request.created_at.timestamp(),
                            request.decision,
                            request.decision_reason,
                            request.decided_by,
                            request.decided_at,
                            json.dumps(request.metadata),
                            json.dumps(request.scope_tags),
                            request.scope_digest,
                            request.manifest_id,
                            request.idempotency_key,
                        ),
                    )
                    conn.commit()
            except sqlite3.Error as exc:
                raise ApprovalStorageDegradedError(
                    f"SQLite database error writing approval request: {exc}"
                ) from exc
        return request

    def get_request(
        self, approval_token: str, scope: ScopeToken | None = None
    ) -> ApprovalRequest | None:
        if not approval_token:
            return None
        with self._lock:
            try:
                with closing(self._get_connection()) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT approval_token, run_id, turn_index, outbound_payload_hash, "
                        "required_role, reviewer_credentials, status, rule_id, "
                        "checkpoint_id, action_payload, prompt, created_at, decision, "
                        "decision_reason, decided_by, decided_at, metadata, "
                        "scope_tags, scope_digest, manifest_id, idempotency_key "
                        "FROM approval_requests WHERE approval_token = ?",
                        (approval_token,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        return None
                    req = self._row_to_request(row)
                    return req if _matches_scope(req, scope) else None
            except sqlite3.Error as exc:
                raise ApprovalStorageDegradedError(
                    f"SQLite database error getting approval request: {exc}"
                ) from exc

    def get_request_by_run_id(
        self, run_id: str, scope: ScopeToken | None = None
    ) -> ApprovalRequest | None:
        if not run_id:
            return None
        with self._lock:
            try:
                with closing(self._get_connection()) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT approval_token, run_id, turn_index, outbound_payload_hash, "
                        "required_role, reviewer_credentials, status, rule_id, "
                        "checkpoint_id, action_payload, prompt, created_at, decision, "
                        "decision_reason, decided_by, decided_at, metadata, "
                        "scope_tags, scope_digest, manifest_id, idempotency_key "
                        "FROM approval_requests WHERE run_id = ? "
                        "ORDER BY created_at DESC",
                        (run_id,),
                    )
                    for row in cursor.fetchall():
                        req = self._row_to_request(row)
                        if _matches_scope(req, scope):
                            return req
                    return None
            except sqlite3.Error as exc:
                raise ApprovalStorageDegradedError(
                    f"SQLite database error getting approval by run_id: {exc}"
                ) from exc

    def resolve_request(
        self,
        approval_token: str,
        decision: str,
        decided_by: str | None = None,
        decision_reason: str | None = None,
        scope: ScopeToken | None = None,
    ) -> ApprovalRequest:
        normalized_decision = decision.upper().strip()
        if normalized_decision not in ("APPROVED", "REJECTED"):
            raise ValueError(
                f"Invalid approval decision '{decision}'. Must be 'APPROVED' or 'REJECTED'."
            )

        now = time.time()
        reason = decision_reason or (
            "Approved via review gate"
            if normalized_decision == "APPROVED"
            else "Rejected via review gate"
        )
        reviewer = decided_by or "system"

        with self._lock:
            try:
                with closing(self._get_connection()) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT approval_token, run_id, turn_index, outbound_payload_hash, "
                        "required_role, reviewer_credentials, status, rule_id, "
                        "checkpoint_id, action_payload, prompt, created_at, decision, "
                        "decision_reason, decided_by, decided_at, metadata, "
                        "scope_tags, scope_digest, manifest_id, idempotency_key "
                        "FROM approval_requests WHERE approval_token = ?",
                        (approval_token,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        raise KeyError(f"Approval request for token '{approval_token}' not found.")
                    req = self._row_to_request(row)

                    if scope is not None:
                        if req.is_legacy_unscoped and not scope.is_system:
                            raise ScopeMismatchError(
                                f"Approval request for token '{approval_token}' is UNSCOPED_LEGACY "
                                "and cannot be resolved by tenant scope."
                            )
                        if not _matches_scope(req, scope):
                            raise ScopeMismatchError(
                                "Scope mismatch: active scope cannot resolve approval "
                                f"'{approval_token}'."
                            )

                    if req.status != "PENDING":
                        raise ValueError(
                            f"Approval request for token '{approval_token}' is already resolved."
                        )

                    cursor.execute(
                        "UPDATE approval_requests SET "
                        "status = ?, decision = ?, decision_reason = ?, "
                        "decided_by = ?, decided_at = ? "
                        "WHERE approval_token = ? AND status = 'PENDING'",
                        (
                            normalized_decision,
                            normalized_decision,
                            reason,
                            reviewer,
                            now,
                            approval_token,
                        ),
                    )
                    conn.commit()
            except sqlite3.Error as exc:
                raise ApprovalStorageDegradedError(
                    f"SQLite database error resolving approval request: {exc}"
                ) from exc

        resolved = self.get_request(approval_token)
        if not resolved:
            raise KeyError(f"Approval request for token '{approval_token}' not found after update.")
        return resolved

    def list_pending(
        self, run_id: str | None = None, scope: ScopeToken | None = None
    ) -> list[ApprovalRequest]:
        with self._lock:
            try:
                with closing(self._get_connection()) as conn:
                    cursor = conn.cursor()
                    query = (
                        "SELECT approval_token, run_id, turn_index, outbound_payload_hash, "
                        "required_role, reviewer_credentials, status, rule_id, "
                        "checkpoint_id, action_payload, prompt, created_at, decision, "
                        "decision_reason, decided_by, decided_at, metadata, "
                        "scope_tags, scope_digest, manifest_id, idempotency_key "
                        "FROM approval_requests WHERE status = 'PENDING'"
                    )
                    params: list[Any] = []
                    if run_id:
                        query += " AND run_id = ?"
                        params.append(run_id)
                    query += " ORDER BY created_at ASC"

                    cursor.execute(query, tuple(params))
                    rows = cursor.fetchall()
                    result: list[ApprovalRequest] = []
                    for r in rows:
                        req = self._row_to_request(r)
                        if _matches_scope(req, scope):
                            result.append(req)
                    return result
            except sqlite3.Error as exc:
                raise ApprovalStorageDegradedError(
                    f"SQLite database error listing pending approvals: {exc}"
                ) from exc

    def delete_request(self, approval_token: str, scope: ScopeToken | None = None) -> bool:
        req = self.get_request(approval_token, scope=scope)
        if not req:
            return False
        with self._lock:
            try:
                with closing(self._get_connection()) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "DELETE FROM approval_requests WHERE approval_token = ?",
                        (approval_token,),
                    )
                    conn.commit()
                    return cursor.rowcount > 0
            except sqlite3.Error as exc:
                raise ApprovalStorageDegradedError(
                    f"SQLite database error deleting approval request: {exc}"
                ) from exc

    get = get_request

    def stream_pending(self, scope: ScopeToken | None = None) -> Iterator[ApprovalEvent]:
        for req in self.list_pending(scope=scope):
            yield ApprovalEvent(event_type="PENDING", request=req)


def migrate_unscoped_approval(
    approval_token: str,
    run_id: str | None = None,
    auditor_identity: str = "system",
    store: ApprovalStore | None = None,
    operator: str | None = None,
    reason: str = "Audited scope backfill",
    run_index_root: Path | None = None,
) -> ApprovalRequest:
    """
    Audited migration utility to bind an UNSCOPED_LEGACY approval to a verified scope.

    Strict invariants:
    1. The approval must exist and be currently UNSCOPED_LEGACY.
    2. A verified run manifest or run index with the exact run_id must exist.
    3. The verified run must have an unambiguous, non-empty scope.
    4. Migration records an audit record in the approval metadata.
    5. Fails closed with ValueError if provenance is ambiguous or missing.
    """
    app_store = store or get_default_approval_store()
    system_scope = ScopeToken.from_tags(None, is_system=True)
    req = app_store.get_request(approval_token, scope=system_scope)
    if not req:
        raise KeyError(f"Approval request '{approval_token}' not found.")

    if not req.is_legacy_unscoped:
        return req

    target_run_id = run_id or req.run_id
    if target_run_id != req.run_id:
        raise ValueError(
            f"Run ID mismatch: approval belongs to '{req.run_id}', requested '{target_run_id}'."
        )

    # 1. Look up verified run in run_index
    from eval_runner.run_index import read_run_index

    verified_context: dict[str, Any] | None = None
    verified_scope_digest: str = ""
    verified_manifest_id: str | None = req.manifest_id

    idx_entry = read_run_index(target_run_id, root=run_index_root)
    if (
        idx_entry
        and isinstance(idx_entry.get("context"), Mapping)
        and idx_entry.get("scope_digest")
    ):
        verified_context = dict(idx_entry["context"])
        verified_scope_digest = str(idx_entry["scope_digest"])

    # 2. Look up run manifest if run_index wasn't present or missing scope
    if not verified_context or not verified_scope_digest:
        from eval_runner.reference.local_run_store import LocalFileRunStore

        run_store = LocalFileRunStore()
        manifest_getter = getattr(
            run_store, "get_run_manifest", getattr(run_store, "get_manifest", None)
        )
        manifest_data = manifest_getter(target_run_id) if manifest_getter else None
        if manifest_data and isinstance(manifest_data, dict):
            verified_manifest_id = verified_manifest_id or manifest_data.get("manifest_id")
            m_ctx = manifest_data.get("context") or manifest_data.get("scope")
            if isinstance(m_ctx, Mapping):
                verified_context = dict(m_ctx)
                verified_scope_digest = str(
                    manifest_data.get("scope_digest")
                    or ScopeToken.from_tags(verified_context).digest
                )

    if not verified_context or not verified_scope_digest:
        raise ValueError(
            f"Cannot migrate approval '{approval_token}': no verified run or unambiguous scope "
            f"found for run '{target_run_id}'."
        )

    # Bind verified scope
    token = ScopeToken.from_tags(verified_context)
    if token.digest != verified_scope_digest:
        raise ValueError(
            f"Scope digest mismatch in run provenance: {token.digest} vs {verified_scope_digest}."
        )

    req.scope_tags = token.tags
    req.scope_digest = token.digest
    if verified_manifest_id:
        req.manifest_id = verified_manifest_id

    operator_id = operator or auditor_identity or "system"

    # Record audit trail
    migration_audit = {
        "migrated_at": datetime.now(UTC).isoformat(),
        "migrated_by": operator_id,
        "operator": operator_id,
        "reason": reason,
        "previous_status": "UNSCOPED_LEGACY",
        "verified_run_id": target_run_id,
        "bound_scope_digest": token.digest,
    }
    req.metadata["migration"] = migration_audit

    return app_store.create_request(req)


_default_store: ApprovalStore | None = None
_store_lock = threading.Lock()


def get_default_approval_store(
    store_type: str | None = None,
    base_dir: str | Path | None = None,
) -> ApprovalStore:
    """
    Returns the configured or singleton ApprovalStore reference implementation.
    Defaults to lightweight FileApprovalStore (.agentv/approvals/<run_id>.json).
    """
    from agentv_runtime.discovery import resolve_extension

    kind = store_type or os.getenv("AGENTV_APPROVAL_STORE", "file").lower()
    if base_dir is not None:
        if kind == "sqlite":
            return SQLiteApprovalStore(db_path=base_dir)
        return FileApprovalStore(base_dir=base_dir)

    default_factory = SQLiteApprovalStore if kind == "sqlite" else FileApprovalStore
    if kind in ("sqlite", "file"):
        return default_factory()
    return resolve_extension("approval_stores", default_factory=default_factory)


def reset_default_approval_store() -> None:
    """Resets the singleton store instance for tests."""
    global _default_store
    from agentv_runtime.discovery import reset_extensions

    reset_extensions("approval_stores")
    with _store_lock:
        _default_store = None


__all__ = [
    "ApprovalRequest",
    "ApprovalStore",
    "FileApprovalStore",
    "SQLiteApprovalStore",
    "get_default_approval_store",
    "migrate_unscoped_approval",
    "reset_default_approval_store",
]
