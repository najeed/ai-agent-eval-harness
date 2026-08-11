import json
from pathlib import Path

from .trace_utils import load_events


class LeaderboardGenerator:
    """Aggregates results from multiple evaluation runs into a comparison leaderboard."""

    @staticmethod
    def _collect_stats(runs_dir: str) -> list[dict]:
        """Core aggregation logic — returns structured rows, shared by both output methods."""
        path = Path(runs_dir)
        traces = list(path.glob("*/run.jsonl"))

        stats = []
        for tp in traces:
            try:
                events = load_events(tp)
                run_start = next((e for e in events if e.get("event") == "run_start"), {})
                meta = run_start.get("metadata", {})

                manifest_path = tp.parent / "run_manifest.json"
                manifest_data = {}
                is_certified = False

                if manifest_path.exists():
                    try:
                        with open(manifest_path, encoding="utf-8") as f:
                            manifest_data = json.load(f)
                            is_certified = True
                    except Exception as e:
                        import logging

                        logging.error(f"   [Leaderboard] Manifest Read Failure for {tp}: {e}")

                agent_name = (
                    manifest_data.get("metadata", {}).get("agent_name")
                    or meta.get("agent_name")
                    or meta.get("agent")
                )

                if not agent_name:
                    agent_name = tp.parent.name

                evals = [e for e in events if e.get("event") == "evaluation"]
                if not evals:
                    continue

                total_tasks = len(set(e.get("task_id") for e in evals))
                task_metrics: dict = {}
                for e in evals:
                    tid = e.get("task_id")
                    if tid not in task_metrics:
                        task_metrics[tid] = []
                    task_metrics[tid].append(e.get("success", False))

                successful_tasks = sum(1 for results in task_metrics.values() if all(results))
                pass_rate = (successful_tasks / total_tasks * 100) if total_tasks > 0 else 0

                if pass_rate < 50:
                    continue

                # Aggregate metric scores by category for drill-down
                metric_scores: dict[str, list[float]] = {}
                for e in evals:
                    cat = e.get("metric", "unknown")
                    score = e.get("value")
                    if score is not None:
                        metric_scores.setdefault(cat, []).append(float(score))

                avg_by_metric = {
                    cat: round(sum(vals) / len(vals), 3) for cat, vals in metric_scores.items()
                }

                stats.append(
                    {
                        "run_id": tp.parent.name,
                        "agent": agent_name,
                        "agent_display": f"\U0001f3c5 {agent_name}" if is_certified else agent_name,
                        "pass_rate": round(pass_rate, 1),
                        "successful_tasks": successful_tasks,
                        "total_tasks": total_tasks,
                        "tasks": f"{successful_tasks}/{total_tasks}",
                        "certified": is_certified,
                        "metrics": avg_by_metric,
                        "trace_file": str(tp.relative_to(path)),
                    }
                )
            except Exception as e:
                import logging

                logging.error(f"   [Leaderboard] Trace Aggregation Failure for {tp}: {e}")
                continue

        stats.sort(key=lambda x: x["pass_rate"], reverse=True)
        return stats

    @staticmethod
    def generate_data(runs_dir: str) -> list[dict]:
        """
        Returns structured leaderboard rows as a list of dicts.
        Suitable for JSON API responses and programmatic consumption.
        """
        return LeaderboardGenerator._collect_stats(runs_dir)

    @staticmethod
    def generate_markdown(runs_dir: str) -> str:
        """Generates a Markdown leaderboard table from traces in a directory."""
        stats = LeaderboardGenerator._collect_stats(runs_dir)

        if not stats:
            return "# \U0001f3c6 Agent Evaluation Leaderboard\n\n> [!WARNING]\n> No agents have achieved the minimum quality threshold (50% pass rate) yet. Keep iterating!\n"  # noqa: E501

        md = "# \U0001f3c6 Agent Evaluation Leaderboard\n\n"
        md += "| Rank | Agent | Pass Rate | Success/Total | Trace File |\n"
        md += "| :--- | :--- | :--- | :--- | :--- |\n"

        for i, s in enumerate(stats):
            icon = (
                "\U0001f947"
                if i == 0
                else "\U0001f948"
                if i == 1
                else "\U0001f949"
                if i == 2
                else f"{i + 1}."
            )
            md += f"| {icon} | **{s['agent_display']}** | {s['pass_rate']:.1f}% | {s['tasks']} | `{s['trace_file']}` |\n"  # noqa: E501

        md += "\n*Generated by [AgentV](https://github.com/najeed/ai-agent-eval-harness)*\n"
        return md


def run_leaderboard(runs_dir: str, output_file: str = "LEADERBOARD.md"):
    """CLI helper for generating the leaderboard."""
    print(f"\n[Leaderboard] Aggregating results from: {runs_dir}...")
    content = LeaderboardGenerator.generate_markdown(runs_dir)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[OK] Leaderboard generated: {output_file}")
