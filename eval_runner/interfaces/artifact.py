"""
eval_runner.interfaces.artifact
Public Extension Family: ArtifactStore Contract
"""

from abc import ABC, abstractmethod
from typing import Any


class ArtifactStore(ABC):
    """
    Abstraction for persisting and retrieving evaluation artifacts, trajectories, and blobs.
    OSS Reference: LocalFileArtifactStore
    Control Plane / Enterprise: S3ArtifactStore / GCSArtifactStore / AzureBlobArtifactStore
    """

    @abstractmethod
    def store_artifact(
        self,
        run_id: str,
        artifact_name: str,
        content: bytes | str,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Stores an artifact and returns its persistent URI / path."""
        raise NotImplementedError

    @abstractmethod
    def get_artifact(self, run_id: str, artifact_name: str) -> bytes | None:
        """Retrieves raw artifact content by run ID and name."""
        raise NotImplementedError

    @abstractmethod
    def exists(self, run_id: str, artifact_name: str) -> bool:
        """Checks if a given artifact exists for a run."""
        raise NotImplementedError

    @abstractmethod
    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        """Lists all artifacts associated with a run."""
        raise NotImplementedError
