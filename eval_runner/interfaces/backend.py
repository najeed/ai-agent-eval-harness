"""
eval_runner.interfaces.backend
Public Extension Family: ExecutionBackend Contract
"""

from abc import ABC, abstractmethod
from typing import Any


class ExecutionBackend(ABC):
    """
    Neutral abstraction for evaluation run execution.
    OSS Reference: InProcessExecutionBackend
    Control Plane / Enterprise: TemporalExecutionBackend
    """

    @abstractmethod
    def submit(self, run_id: str, scenario_data: dict[str, Any], **kwargs: Any) -> Any:
        """Submits an evaluation run for execution."""
        raise NotImplementedError

    @abstractmethod
    def status(self, run_id: str) -> dict[str, Any]:
        """Returns the current execution status and metadata for a run."""
        raise NotImplementedError

    @abstractmethod
    def cancel(self, run_id: str, reason: str | None = None) -> bool:
        """Cancels an in-progress evaluation run."""
        raise NotImplementedError

    @abstractmethod
    def resume(self, run_id: str, resumption_token: str | None = None, **kwargs: Any) -> Any:
        """Resumes a paused or checkpointed evaluation run."""
        raise NotImplementedError
