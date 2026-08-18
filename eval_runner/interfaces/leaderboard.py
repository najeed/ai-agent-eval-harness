"""
eval_runner.interfaces.leaderboard
Public Extension Family: LeaderboardStore Contract
"""

from abc import ABC, abstractmethod
from typing import Any


class LeaderboardStore(ABC):
    """
    Abstraction for leaderboard statistical aggregation, model rankings, and benchmark comparisons.
    OSS Reference: LocalLeaderboardStore
    Control Plane / Enterprise: DistributedLeaderboardStore
    """

    @abstractmethod
    def get_leaderboard(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Computes and returns aggregated leaderboard rows."""
        raise NotImplementedError

    @abstractmethod
    def record_run_summary(self, run_id: str, summary: dict[str, Any]) -> None:
        """Records or updates a run summary in the leaderboard index."""
        raise NotImplementedError
