"""
eval_runner.interfaces.checkpoint
Public Extension Family: CheckpointStore Contract
"""

from abc import ABC, abstractmethod
from typing import Any


class CheckpointStore(ABC):
    """
    Abstraction for persisting and loading evaluation session checkpoints.
    OSS Reference: SQLiteCheckpointStore / LocalFileCheckpointStore
    Control Plane / Enterprise: PostgresCheckpointStore
    """

    @abstractmethod
    def save(
        self,
        run_id: str,
        checkpoint_id: str,
        state: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persists a session state checkpoint. Returns the checkpoint ID or URI."""
        raise NotImplementedError

    @abstractmethod
    def load(self, run_id: str, checkpoint_id: str | None = None) -> dict[str, Any] | None:
        """Loads the latest or specific session checkpoint state for a run."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, run_id: str, checkpoint_id: str | None = None) -> bool:
        """Deletes checkpoints for a given run."""
        raise NotImplementedError

    @abstractmethod
    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        """Lists metadata for all checkpoints recorded for a run."""
        raise NotImplementedError
