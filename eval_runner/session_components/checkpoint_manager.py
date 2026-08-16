"""
eval_runner.session_components.checkpoint_manager
Decomposed Session Component: SessionCheckpointManager
"""

from typing import Any

from eval_runner.interfaces.checkpoint import CheckpointStore
from eval_runner.reference.sqlite_checkpoint import SQLiteCheckpointStore


class SessionCheckpointManager:
    """Manages session persistence and checkpointing via CheckpointStore interface."""

    def __init__(self, run_id: str, store: CheckpointStore | None = None):
        self.run_id = run_id
        self._store = store
        self._checkpoint_count = 0

    @property
    def store(self) -> CheckpointStore:
        if self._store is None:
            self._store = SQLiteCheckpointStore()
        return self._store

    def create_checkpoint(
        self,
        state: dict[str, Any],
        checkpoint_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Saves a checkpoint for the current run."""
        self._checkpoint_count += 1
        cid = checkpoint_id or f"chk_{self._checkpoint_count:04d}"
        return self.store.save(self.run_id, cid, state, metadata=metadata)

    def load_latest_checkpoint(self) -> dict[str, Any] | None:
        """Loads the most recent checkpoint state."""
        return self.store.load(self.run_id)

    def list_checkpoints(self) -> list[dict[str, Any]]:
        """Lists all checkpoints for the run."""
        return self.store.list_checkpoints(self.run_id)
