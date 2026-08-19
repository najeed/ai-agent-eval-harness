"""
eval_runner.reference.local_leaderboard
OSS Reference Implementation: LocalLeaderboardStore
"""

from pathlib import Path
from typing import Any

from eval_runner import config
from eval_runner.interfaces.leaderboard import LeaderboardStore
from eval_runner.leaderboard_generator import LeaderboardGenerator


class LocalLeaderboardStore(LeaderboardStore):
    """
    Local filesystem-backed reference LeaderboardStore.
    Delegates statistical aggregation to LeaderboardGenerator over the local runs directory.
    """

    def __init__(self, runs_dir: str | Path | None = None):
        self.runs_dir = str(runs_dir or config.RUN_LOG_DIR)

    def get_leaderboard(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        rows = LeaderboardGenerator.generate_data(self.runs_dir)
        if filters:
            if "min_pass_rate" in filters:
                min_pr = float(filters["min_pass_rate"])
                rows = [r for r in rows if r.get("pass_rate", 0) >= min_pr]
            if "agent" in filters:
                agent_name = str(filters["agent"]).lower()
                rows = [r for r in rows if agent_name in r.get("agent", "").lower()]
        return rows

    def record_run_summary(self, run_id: str, summary: dict[str, Any]) -> None:
        import json

        from eval_runner.utils.safe_path import SafeRunPathResolver

        try:
            target_dir = SafeRunPathResolver.resolve_run_dir(self.runs_dir, run_id, create=True)
            summary_file = SafeRunPathResolver.resolve_artifact_path(
                target_dir, "run_summary.json", allow_subdirs=False
            )
            with open(summary_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
        except (ValueError, PermissionError):
            pass


# Alias for naming consistency with LocalFileCatalogStore and LocalFileRunStore
LocalFileLeaderboardStore = LocalLeaderboardStore
