"""
eval_runner.reference.local_leaderboard
OSS Reference Implementation: LocalLeaderboardStore
"""

from typing import Any

from eval_runner.interfaces.leaderboard import LeaderboardStore
from eval_runner.leaderboard_generator import LeaderboardGenerator


class LocalLeaderboardStore(LeaderboardStore):
    """
    Local filesystem-backed reference LeaderboardStore.
    Delegates statistical aggregation to LeaderboardGenerator over the local runs directory.
    """

    def __init__(self, run_store: Any):
        self.run_store = run_store

    def get_leaderboard(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        rows = LeaderboardGenerator.generate_data(self.run_store)
        if filters:
            if "min_pass_rate" in filters:
                min_pr = float(filters["min_pass_rate"])
                rows = [r for r in rows if r.get("pass_rate", 0) >= min_pr]
            if "agent" in filters:
                agent_name = str(filters["agent"]).lower()
                rows = [r for r in rows if agent_name in r.get("agent", "").lower()]
        return rows

    def record_run_summary(self, run_id: str, summary: dict[str, Any]) -> None:
        manifest = self.run_store.get_manifest(run_id) or {}
        manifest["leaderboard_summary"] = dict(summary)
        self.run_store.save_run_manifest(run_id, manifest)


# Alias for naming consistency with LocalFileCatalogStore and LocalFileRunStore
LocalFileLeaderboardStore = LocalLeaderboardStore
