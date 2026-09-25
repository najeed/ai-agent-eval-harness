"""
eval_runner.reference.approval_store
Reference storage implementations for the ApprovalStore contract (HITL Queue).
Neutral, lightweight, zero-dependency implementations (File and SQLite).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from agentv_runtime.interfaces import ApprovalRequest, ApprovalStore
from eval_runner import config

logger = logging.getLogger(__name__)


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
        with open(temp_path, "wb") as f:
            f.write(payload_bytes)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, target_path)

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

    def get_request(self, approval_token: str) -> ApprovalRequest | None:
        if not approval_token:
            return None
        with self._lock:
            # 1. Fast O(1) path via token file
            token_file = self.base_dir / f"token_{approval_token}.json"
            if token_file.exists():
                try:
                    with open(token_file, encoding="utf-8") as f:
                        data = json.load(f)
                    return ApprovalRequest.from_dict(data)
                except (json.JSONDecodeError, OSError) as exc:
                    logger.debug("Error reading token file %s: %s", token_file, exc)

            # 2. Fallback scan of run files
            try:
                for file_path in self.base_dir.glob("*.json"):
                    if file_path.name.startswith("token_") or file_path.name.endswith(".tmp"):
                        continue
                    try:
                        with open(file_path, encoding="utf-8") as f:
                            data = json.load(f)
                        if data.get("approval_token") == approval_token:
                            return ApprovalRequest.from_dict(data)
                    except (json.JSONDecodeError, OSError):
                        continue
            except OSError as scan_exc:
                logger.debug("Error scanning approval directory: %s", scan_exc)

            return None

    def get_request_by_run_id(self, run_id: str) -> ApprovalRequest | None:
        if not run_id:
            return None
        with self._lock:
            run_file = self.base_dir / f"{run_id}.json"
            if run_file.exists():
                try:
                    with open(run_file, encoding="utf-8") as f:
                        data = json.load(f)
                    return ApprovalRequest.from_dict(data)
                except (json.JSONDecodeError, OSError) as exc:
                    logger.debug("Error reading run approval file %s: %s", run_file, exc)
            return None

    def resolve_request(
        self,
        approval_token: str,
        decision: str,
        decided_by: str | None = None,
        decision_reason: str | None = None,
    ) -> ApprovalRequest:
        req = self.get_request(approval_token)
        if not req:
            raise KeyError(f"Approval request for token '{approval_token}' not found.")

        normalized_decision = decision.upper().strip()
        if normalized_decision not in ("APPROVED", "REJECTED"):
            raise ValueError(
                f"Invalid approval decision '{decision}'. Must be 'APPROVED' or 'REJECTED'."
            )

        with self._lock:
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

    def list_pending(self, run_id: str | None = None) -> list[ApprovalRequest]:
        pending: list[ApprovalRequest] = []
        with self._lock:
            try:
                for file_path in self.base_dir.glob("token_*.json"):
                    try:
                        with open(file_path, encoding="utf-8") as f:
                            data = json.load(f)
                        if data.get("status") == "PENDING":
                            if run_id is None or data.get("run_id") == run_id:
                                pending.append(ApprovalRequest.from_dict(data))
                    except (json.JSONDecodeError, OSError) as exc:
                        logger.debug("Error parsing pending file %s: %s", file_path, exc)
            except OSError as scan_exc:
                logger.debug("Error listing pending approvals: %s", scan_exc)
        return pending

    def delete_request(self, approval_token: str) -> bool:
        req = self.get_request(approval_token)
        with self._lock:
            deleted = False
            token_file = self.base_dir / f"token_{approval_token}.json"
            if token_file.exists():
                try:
                    token_file.unlink()
                    deleted = True
                except OSError as exc:
                    logger.debug("Error unlinking token file %s: %s", token_file, exc)

            if req:
                run_file = self.base_dir / f"{req.run_id}.json"
                if run_file.exists():
                    try:
                        run_file.unlink()
                        deleted = True
                    except OSError as exc:
                        logger.debug("Error unlinking run file %s: %s", run_file, exc)
            return deleted


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

    def _init_db(self) -> None:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with closing(sqlite3.connect(self.db_path)) as conn:
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
                            metadata TEXT
                        )
                    """)
                    cursor.execute(
                        "CREATE INDEX IF NOT EXISTS idx_approval_run_id "
                        "ON approval_requests(run_id)"
                    )
                    cursor.execute(
                        "CREATE INDEX IF NOT EXISTS idx_approval_status "
                        "ON approval_requests(status)"
                    )
                    conn.commit()
        except Exception as e:
            logger.error("Failed to initialize SQLite Approval Database: %s", e)
            raise

    def _row_to_request(self, row: tuple) -> ApprovalRequest:
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
        )

    def create_request(self, request: ApprovalRequest) -> ApprovalRequest:
        with self._lock:
            with closing(sqlite3.connect(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO approval_requests (
                        approval_token, run_id, turn_index, outbound_payload_hash,
                        required_role, reviewer_credentials, status, rule_id,
                        checkpoint_id, action_payload, prompt, created_at,
                        decision, decision_reason, decided_by, decided_at, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(approval_token) DO UPDATE SET
                        status=excluded.status,
                        decision=excluded.decision,
                        decision_reason=excluded.decision_reason,
                        decided_by=excluded.decided_by,
                        decided_at=excluded.decided_at
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
                        request.created_at,
                        request.decision,
                        request.decision_reason,
                        request.decided_by,
                        request.decided_at,
                        json.dumps(request.metadata),
                    ),
                )
                conn.commit()
        return request

    def get_request(self, approval_token: str) -> ApprovalRequest | None:
        if not approval_token:
            return None
        with self._lock:
            with closing(sqlite3.connect(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT approval_token, run_id, turn_index, outbound_payload_hash, "
                    "required_role, reviewer_credentials, status, rule_id, "
                    "checkpoint_id, action_payload, prompt, created_at, decision, "
                    "decision_reason, decided_by, decided_at, metadata "
                    "FROM approval_requests WHERE approval_token = ?",
                    (approval_token,),
                )
                row = cursor.fetchone()
                return self._row_to_request(row) if row else None

    def get_request_by_run_id(self, run_id: str) -> ApprovalRequest | None:
        if not run_id:
            return None
        with self._lock:
            with closing(sqlite3.connect(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT approval_token, run_id, turn_index, outbound_payload_hash, "
                    "required_role, reviewer_credentials, status, rule_id, "
                    "checkpoint_id, action_payload, prompt, created_at, decision, "
                    "decision_reason, decided_by, decided_at, metadata "
                    "FROM approval_requests WHERE run_id = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (run_id,),
                )
                row = cursor.fetchone()
                return self._row_to_request(row) if row else None

    def resolve_request(
        self,
        approval_token: str,
        decision: str,
        decided_by: str | None = None,
        decision_reason: str | None = None,
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
            with closing(sqlite3.connect(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE approval_requests SET "
                    "status = ?, decision = ?, decision_reason = ?, "
                    "decided_by = ?, decided_at = ? "
                    "WHERE approval_token = ?",
                    (
                        normalized_decision,
                        normalized_decision,
                        reason,
                        reviewer,
                        now,
                        approval_token,
                    ),
                )
                if cursor.rowcount == 0:
                    raise KeyError(f"Approval request for token '{approval_token}' not found.")
                conn.commit()

        req = self.get_request(approval_token)
        if not req:
            raise KeyError(f"Approval request for token '{approval_token}' not found after update.")
        return req

    def list_pending(self, run_id: str | None = None) -> list[ApprovalRequest]:
        with self._lock:
            with closing(sqlite3.connect(self.db_path)) as conn:
                cursor = conn.cursor()
                if run_id:
                    cursor.execute(
                        "SELECT approval_token, run_id, turn_index, outbound_payload_hash, "
                        "required_role, reviewer_credentials, status, rule_id, "
                        "checkpoint_id, action_payload, prompt, created_at, decision, "
                        "decision_reason, decided_by, decided_at, metadata "
                        "FROM approval_requests WHERE status = 'PENDING' AND run_id = ? "
                        "ORDER BY created_at ASC",
                        (run_id,),
                    )
                else:
                    cursor.execute(
                        "SELECT approval_token, run_id, turn_index, outbound_payload_hash, "
                        "required_role, reviewer_credentials, status, rule_id, "
                        "checkpoint_id, action_payload, prompt, created_at, decision, "
                        "decision_reason, decided_by, decided_at, metadata "
                        "FROM approval_requests WHERE status = 'PENDING' "
                        "ORDER BY created_at ASC"
                    )
                rows = cursor.fetchall()
                return [self._row_to_request(r) for r in rows]

    def delete_request(self, approval_token: str) -> bool:
        with self._lock:
            with closing(sqlite3.connect(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM approval_requests WHERE approval_token = ?",
                    (approval_token,),
                )
                conn.commit()
                return cursor.rowcount > 0


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
    global _default_store
    kind = store_type or os.getenv("AGENTV_APPROVAL_STORE", "file").lower()
    if base_dir is not None:
        if kind == "sqlite":
            return SQLiteApprovalStore(db_path=base_dir)
        return FileApprovalStore(base_dir=base_dir)

    with _store_lock:
        if _default_store is None:
            if kind == "sqlite":
                _default_store = SQLiteApprovalStore()
            else:
                _default_store = FileApprovalStore()
        return _default_store


def reset_default_approval_store() -> None:
    """Resets the singleton store instance for tests."""
    global _default_store
    with _store_lock:
        _default_store = None


__all__ = [
    "ApprovalRequest",
    "ApprovalStore",
    "FileApprovalStore",
    "SQLiteApprovalStore",
    "get_default_approval_store",
    "reset_default_approval_store",
]
