"""
eval_runner.interfaces.run_store
Public Extension Family: RunStore Contract
"""

from abc import ABC, abstractmethod
from typing import Any


class RunStore(ABC):
    """
    Abstraction for evaluation run metadata, manifest retrieval, and run lifecycle query.
    OSS Reference: LocalFileRunStore
    Control Plane / Enterprise: PostgresRunStore / ClickHouseRunStore
    """

    @abstractmethod
    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Retrieves run summary, manifest, and status by run ID."""
        raise NotImplementedError

    @abstractmethod
    def list_runs(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Lists runs with pagination."""
        raise NotImplementedError

    @abstractmethod
    def save_run_manifest(self, run_id: str, manifest: dict[str, Any]) -> str:
        """Saves a run manifest and returns the record ID or URI."""
        raise NotImplementedError

    @abstractmethod
    def delete_run(self, run_id: str) -> bool:
        """Deletes a run and its metadata."""
        raise NotImplementedError
