"""Provider-native leaderboard aggregation."""

from typing import Any


class LeaderboardGenerator:
    """Aggregate provider-owned manifests and events into leaderboard rows."""

    @staticmethod
    def _collect_stats(run_store: Any, min_pass_rate: float = 0.0) -> list[dict[str, Any]]:
        stats: list[dict[str, Any]] = []
        for run in run_store.list_runs(limit=10_000):
            run_id = run.get("run_id")
            if not isinstance(run_id, str):
                continue
            manifest = run_store.get_manifest(run_id) or {}
            events = run_store.get_events(run_id, offset=0, limit=10_000_000)
            metadata = (
                manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
            )
            start = next((event for event in events if event.get("event") == "run_start"), {})
            start_metadata = (
                start.get("metadata") if isinstance(start.get("metadata"), dict) else {}
            )
            agent_name = (
                metadata.get("agent_name")
                or manifest.get("agent_name")
                or start_metadata.get("agent_name")
                or run.get("agent_id")
                or "unknown"
            )
            evaluations = [event for event in events if event.get("event") == "evaluation"]
            if not evaluations:
                continue
            grouped: dict[str, list[bool]] = {}
            for event in evaluations:
                task_id = str(event.get("task_id") or len(grouped))
                grouped.setdefault(task_id, []).append(bool(event.get("success", False)))
            total = len(grouped)
            successful = sum(all(results) for results in grouped.values())
            pass_rate = successful / total * 100 if total else 0.0
            if pass_rate < min_pass_rate:
                continue
            scores: dict[str, list[float]] = {}
            for event in evaluations:
                metric, score = event.get("metric"), event.get("value", event.get("score"))
                if metric and isinstance(score, (int, float)):
                    scores.setdefault(str(metric), []).append(float(score))
            certified = bool(manifest.get("certification") or manifest.get("certificate"))
            stats.append(
                {
                    "run_id": run_id,
                    "agent": agent_name,
                    "agent_display": f"🏅 {agent_name}" if certified else agent_name,
                    "pass_rate": round(pass_rate, 1),
                    "successful_tasks": successful,
                    "total_tasks": total,
                    "tasks": f"{successful}/{total}",
                    "certified": certified,
                    "metrics": {
                        metric: round(sum(values) / len(values), 3)
                        for metric, values in scores.items()
                    },
                    "evidence_source": "provider",
                }
            )
        return sorted(stats, key=lambda row: row["pass_rate"], reverse=True)

    @staticmethod
    def generate_data(run_store: Any, min_pass_rate: float = 0.0) -> list[dict[str, Any]]:
        return LeaderboardGenerator._collect_stats(run_store, min_pass_rate=min_pass_rate)

    @staticmethod
    def generate_markdown(run_store: Any, min_pass_rate: float = 50.0) -> str:
        stats = LeaderboardGenerator._collect_stats(run_store, min_pass_rate=min_pass_rate)
        if not stats:
            return (
                "# 🏆 Agent Evaluation Leaderboard\n\n> No qualifying provider-owned runs found.\n"
            )
        lines = [
            "# 🏆 Agent Evaluation Leaderboard",
            "",
            "| Rank | Agent | Pass Rate | Success/Total | Evidence |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for index, row in enumerate(stats, 1):
            lines.append(
                f"| {index}. | **{row['agent_display']}** | {row['pass_rate']:.1f}% | "
                f"{row['tasks']} | provider |"
            )
        return "\n".join(lines) + "\n"


def run_leaderboard(run_store: Any, output_file: str = "LEADERBOARD.md") -> None:
    """Write a presentation artifact derived from provider-owned records."""
    content = LeaderboardGenerator.generate_markdown(run_store)
    with open(output_file, "w", encoding="utf-8") as output:
        output.write(content)
    print(f"[OK] Leaderboard generated: {output_file}")
