import asyncio
import logging
import sqlite3
import threading
import time
import uuid
from contextlib import closing

from eval_runner import config

logger = logging.getLogger(__name__)

# Lock for SQLite writes to avoid concurrent access issues
db_lock = threading.Lock()


class PendingApproval:
    def __init__(
        self,
        task_id,
        run_id,
        prompt,
        timeout_seconds=1800,
        approval_id=None,
        created_at=None,
        action=None,
        response=None,
        resolved_by=None,
        resumption_token=None,
        resumed_from_db=False,
    ):
        self.id = approval_id or str(uuid.uuid4())
        self.task_id = task_id
        self.run_id = run_id
        self.prompt = prompt
        self.created_at = created_at or time.time()
        self.timeout_seconds = timeout_seconds
        self.response = response
        self.resolved_by = resolved_by
        self.action = action  # "approve" | "reject" | "timeout"
        self.resumption_token = resumption_token or f"tok_{uuid.uuid4().hex[:16]}"
        self.resumed_from_db = resumed_from_db
        self._event = threading.Event()
        if action is not None:
            self._event.set()

    def resolve(self, action, response, resolved_by):
        self.action = action
        self.response = response
        self.resolved_by = resolved_by
        self._event.set()

    async def wait(self):
        # Compute remaining timeout accurately across process lifecycles
        elapsed = time.time() - self.created_at
        remaining = max(0.0, float(self.timeout_seconds) - elapsed)

        if remaining <= 0 and not self._event.is_set():
            self.action = "timeout"
            self.response = "[Auto-aborted: approval window expired]"
            self._event.set()
            return self

        loop = asyncio.get_event_loop()
        signaled = await loop.run_in_executor(None, self._event.wait, remaining)
        if not signaled:
            self.action = "timeout"
            self.response = "[Auto-aborted: approval window expired]"
            self._event.set()
        return self

    def to_dict(self):
        return {
            "id": self.id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "prompt": self.prompt,
            "created_at": self.created_at,
            "timeout_seconds": self.timeout_seconds,
            "action": self.action,
            "response": self.response,
            "resolved_by": self.resolved_by,
            "resumption_token": self.resumption_token,
            "resumed_from_db": self.resumed_from_db,
            "remaining_seconds": max(
                0, int(self.timeout_seconds - (time.time() - self.created_at))
            ),
        }


class PendingApprovalRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._items: dict[str, PendingApproval] = {}

        # Configure SQLite DB Path
        self.db_path = config.RUN_LOG_DIR / "hitl.db"
        self._init_db()
        self._load_from_db()

    def _init_db(self):
        try:
            config.RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
            with db_lock:
                with closing(sqlite3.connect(self.db_path)) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS pending_approvals (
                            id TEXT PRIMARY KEY,
                            task_id TEXT,
                            run_id TEXT,
                            prompt TEXT,
                            action TEXT,
                            response TEXT,
                            resolved_by TEXT,
                            timeout_seconds INTEGER,
                            created_at REAL,
                            resumption_token TEXT
                        )
                    """)
                    # Handle migration if table existed without resumption_token column
                    cursor.execute("PRAGMA table_info(pending_approvals)")
                    cols = [row[1] for row in cursor.fetchall()]
                    if "resumption_token" not in cols:
                        cursor.execute(
                            "ALTER TABLE pending_approvals ADD COLUMN resumption_token TEXT"
                        )
                    conn.commit()
        except Exception as e:
            logger.error(f"Failed to initialize SQLite HITL Database: {e}")

    def _load_from_db(self):
        try:
            if not self.db_path.exists():
                return
            with db_lock:
                with closing(sqlite3.connect(self.db_path)) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT id, task_id, run_id, prompt, action, response, "
                        "resolved_by, timeout_seconds, created_at, resumption_token "
                        "FROM pending_approvals"
                    )
                    rows = cursor.fetchall()

            with self._lock:
                for row in rows:
                    approval = PendingApproval(
                        approval_id=row[0],
                        task_id=row[1],
                        run_id=row[2],
                        prompt=row[3],
                        action=row[4],
                        response=row[5],
                        resolved_by=row[6],
                        timeout_seconds=row[7],
                        created_at=row[8],
                        resumption_token=row[9] if len(row) > 9 else None,
                        resumed_from_db=True,
                    )
                    self._items[approval.id] = approval
        except Exception as e:
            logger.error(f"Failed to load HITL approvals from DB: {e}")

    def create(self, task_id, run_id, prompt, timeout_seconds=1800) -> PendingApproval:
        approval = PendingApproval(task_id, run_id, prompt, timeout_seconds)

        # Write to SQLite
        try:
            with db_lock:
                with closing(sqlite3.connect(self.db_path)) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO pending_approvals (id, task_id, run_id, prompt, "
                        "action, response, resolved_by, timeout_seconds, created_at, "
                        "resumption_token) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            approval.id,
                            approval.task_id,
                            approval.run_id,
                            approval.prompt,
                            approval.action,
                            approval.response,
                            approval.resolved_by,
                            approval.timeout_seconds,
                            approval.created_at,
                            approval.resumption_token,
                        ),
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"Failed to save approval to DB: {e}")

        with self._lock:
            self._items[approval.id] = approval

        # Broadcast creation event if subscriber registered
        self._notify_sse("create", approval.to_dict())
        return approval

    def resolve(self, approval_id, action, response, resolved_by) -> bool:
        with self._lock:
            approval = self._items.get(approval_id)
        if not approval:
            return False

        approval.resolve(action, response, resolved_by)

        # Update SQLite
        try:
            with db_lock:
                with closing(sqlite3.connect(self.db_path)) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "UPDATE pending_approvals SET action = ?, response = ?, "
                        "resolved_by = ? WHERE id = ?",
                        (action, response, resolved_by, approval_id),
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"Failed to resolve approval in DB: {e}")

        self._notify_sse("resolve", approval.to_dict())
        return True

    def pending(self) -> list[PendingApproval]:
        with self._lock:
            return [i for i in self._items.values() if not i._event.is_set()]

    def pending_resumed(self) -> list[PendingApproval]:
        with self._lock:
            return [i for i in self._items.values() if not i._event.is_set() and i.resumed_from_db]

    def get_by_resumption_token(self, token: str) -> PendingApproval | None:
        with self._lock:
            for item in self._items.values():
                if item.resumption_token == token:
                    return item
        return None

    # SSE Broadcasting registration hooks
    def _notify_sse(self, event_type: str, data: dict):
        # We hook into this via console blueprint event listeners
        for listener in _sse_listeners:
            try:
                listener(event_type, data)
            except Exception as e:
                logger.debug(f"Error notifying SSE listener: {e}")


_sse_listeners = []


def subscribe_sse(listener):
    _sse_listeners.append(listener)


def unsubscribe_sse(listener):
    if listener in _sse_listeners:
        _sse_listeners.remove(listener)


global_registry = PendingApprovalRegistry()
