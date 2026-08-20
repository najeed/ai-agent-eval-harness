"""
eval_runner.reference.sqlite_checkpoint
OSS Reference Implementation: SQLiteCheckpointStore
"""

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import eval_runner.config as config
from eval_runner.interfaces.checkpoint import CheckpointStore


class SQLiteCheckpointStore(CheckpointStore):
    """
    SQLite-backed reference checkpoint store.
    Stores durable execution checkpoints across process lifecycles with monotonic sequencing.
    """

    def __init__(self, db_path: str | None = None):
        if not db_path:
            db_path = str(Path(config.RUN_LOG_DIR) / "checkpoints.db")
        self.db_path = db_path
        self._initialized = False

    def _get_connection(self) -> sqlite3.Connection:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_initialized(self):
        if not self._initialized:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            with closing(self._get_connection()) as conn:
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS session_checkpoints (
                            run_id TEXT NOT NULL,
                            checkpoint_id TEXT NOT NULL,
                            turn_number INTEGER NOT NULL DEFAULT 0,
                            state_json TEXT NOT NULL,
                            metadata_json TEXT,
                            created_at TEXT NOT NULL,
                            PRIMARY KEY (run_id, checkpoint_id)
                        )
                        """
                    )
                    # Auto-migration for existing tables without turn_number
                    try:
                        conn.execute(
                            "ALTER TABLE session_checkpoints "
                            "ADD COLUMN turn_number INTEGER NOT NULL DEFAULT 0"
                        )
                    except sqlite3.OperationalError:
                        pass
            self._initialized = True

    def save(
        self,
        run_id: str,
        checkpoint_id: str,
        state: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self._ensure_initialized()
        turn_number = int(state.get("turn", state.get("turn_number", 0)))
        state_json = json.dumps(state)
        metadata_json = json.dumps(metadata or {})
        now_iso = datetime.now().astimezone().isoformat()

        with closing(self._get_connection()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO session_checkpoints
                    (run_id, checkpoint_id, turn_number, state_json, metadata_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (run_id, checkpoint_id, turn_number, state_json, metadata_json, now_iso),
                )
        return f"sqlite://{self.db_path}#{run_id}/{checkpoint_id}"

    def load(self, run_id: str, checkpoint_id: str | None = None) -> dict[str, Any] | None:
        self._ensure_initialized()
        with closing(self._get_connection()) as conn:
            if checkpoint_id:
                row = conn.execute(
                    "SELECT state_json FROM session_checkpoints "
                    "WHERE run_id = ? AND checkpoint_id = ?",
                    (run_id, checkpoint_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT state_json FROM session_checkpoints "
                    "WHERE run_id = ? "
                    "ORDER BY turn_number DESC, checkpoint_id DESC, created_at DESC "
                    "LIMIT 1",
                    (run_id,),
                ).fetchone()

            if row:
                return json.loads(row["state_json"])
        return None

    def delete(self, run_id: str, checkpoint_id: str | None = None) -> bool:
        self._ensure_initialized()
        with closing(self._get_connection()) as conn:
            with conn:
                if checkpoint_id:
                    cur = conn.execute(
                        "DELETE FROM session_checkpoints WHERE run_id = ? AND checkpoint_id = ?",
                        (run_id, checkpoint_id),
                    )
                else:
                    cur = conn.execute(
                        "DELETE FROM session_checkpoints WHERE run_id = ?", (run_id,)
                    )
                return cur.rowcount > 0

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        self._ensure_initialized()
        with closing(self._get_connection()) as conn:
            rows = conn.execute(
                "SELECT checkpoint_id, turn_number, metadata_json, created_at "
                "FROM session_checkpoints "
                "WHERE run_id = ? ORDER BY turn_number ASC, checkpoint_id ASC, created_at ASC",
                (run_id,),
            ).fetchall()
            return [
                {
                    "checkpoint_id": r["checkpoint_id"],
                    "turn_number": r["turn_number"],
                    "metadata": json.loads(r["metadata_json"] or "{}"),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
