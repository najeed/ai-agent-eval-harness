import json
import logging
from pathlib import Path

from .trace_utils import load_events

logger = logging.getLogger(__name__)


class LeaderboardGenerator:
    """Aggregates results from multiple evaluation runs into a comparison leaderboard."""

    @staticmethod
    def _collect_stats(runs_dir: str, min_pass_rate: float = 0.0) -> list[dict]:
        """Core aggregation logic — returns structured rows, shared by both output methods."""
        path = Path(runs_dir)
        if not path.exists():
            return []

        # Find all run directories (having run.jsonl or summary.json or run_manifest.json)
        run_dirs = [d for d in path.iterdir() if d.is_dir()]

        stats = []
        for rd in run_dirs:
            tp = rd / "run.jsonl"
            summary_path = rd / "summary.json"
            manifest_path = rd / "run_manifest.json"

            if not tp.exists() and not summary_path.exists() and not manifest_path.exists():
                continue

            try:
                manifest_data = {}
                is_certified = False
                if manifest_path.exists():
                    try:
                        with open(manifest_path, encoding="utf-8") as f:
                            manifest_data = json.load(f)
                            is_certified = True
                    except Exception as e:
                        logging.error(f"   [Leaderboard] Manifest Read Failure for {tp}: {e}")

                agent_name = manifest_data.get("metadata", {}).get(
                    "agent_name"
                ) or manifest_data.get("agent_name")

                pass_rate = None
                successful_tasks = 0
                total_tasks = 0
                avg_by_metric: dict[str, float] = {}

                # Fast path: check summary.json
                if summary_path.exists():
                    try:
                        with open(summary_path, encoding="utf-8") as f:
                            sdata = json.load(f)
                            if not agent_name:
                                agent_name = sdata.get("agent_name") or sdata.get("agent")
                            if "pass_rate" in sdata:
                                pass_rate = float(sdata["pass_rate"])
                                if pass_rate <= 1.0:
                                    pass_rate = pass_rate * 100
                            elif "score" in sdata:
                                score_val = float(sdata["score"])
                                pass_rate = score_val * 100 if score_val <= 1.0 else score_val
                            elif "passed" in sdata:
                                pass_rate = 100.0 if sdata["passed"] else 0.0

                            total_tasks = sdata.get("total_tasks", sdata.get("total_nodes", 1))
                            successful_tasks = sdata.get(
                                "successful_tasks",
                                int(total_tasks * (pass_rate or 0) / 100),
                            )
                            if isinstance(sdata.get("metrics"), dict):
                                avg_by_metric = {
                                    k: round(float(v), 3)
                                    for k, v in sdata["metrics"].items()
                                    if isinstance(v, (int, float))
                                }
                    except Exception as e:
                        logging.debug(f"Summary read error in {rd}: {e}")

                # Scan events from run.jsonl if summary was not present or incomplete
                if pass_rate is None and tp.exists():
                    events = load_events(tp)
                    run_start = next((e for e in events if e.get("event") == "run_start"), {})
                    meta = run_start.get("metadata", {})
                    if not agent_name:
                        agent_name = meta.get("agent_name") or meta.get("agent")

                    evals = [e for e in events if e.get("event") == "evaluation"]
                    if not evals:
                        evals = [
                            e
                            for e in events
                            if e.get("event") in ("turn_result", "step_success", "step_failure")
                        ]
                    if not evals:
                        continue

                    task_ids = set(e.get("task_id") for e in evals if e.get("task_id"))
                    total_tasks = len(task_ids) or len(evals)
                    task_metrics: dict = {}
                    for e in evals:
                        tid = e.get("task_id") or str(e.get("step_index", len(task_metrics)))
                        if tid not in task_metrics:
                            task_metrics[tid] = []
                        task_metrics[tid].append(
                            bool(e.get("success", e.get("event") != "step_failure"))
                        )

                    successful_tasks = sum(1 for results in task_metrics.values() if all(results))
                    pass_rate = (successful_tasks / total_tasks * 100) if total_tasks > 0 else 0.0

                    metric_scores: dict[str, list[float]] = {}
                    for e in evals:
                        cat = e.get("metric", "unknown")
                        score = e.get("value", e.get("score"))
                        if score is not None:
                            try:
                                metric_scores.setdefault(cat, []).append(float(score))
                            except (ValueError, TypeError):
                                pass

                    avg_by_metric = {
                        cat: round(sum(vals) / len(vals), 3)
                        for cat, vals in metric_scores.items()
                        if vals
                    }

                if pass_rate is None:
                    continue

                if not agent_name:
                    agent_name = rd.name

                if pass_rate < min_pass_rate:
                    continue

                stats.append(
                    {
                        "run_id": rd.name,
                        "agent": agent_name,
                        "agent_display": f"\U0001f3c5 {agent_name}" if is_certified else agent_name,
                        "pass_rate": round(pass_rate, 1),
                        "successful_tasks": successful_tasks,
                        "total_tasks": total_tasks,
                        "tasks": f"{successful_tasks}/{total_tasks}",
                        "certified": is_certified,
                        "metrics": avg_by_metric,
                        "trace_file": str(tp.relative_to(path))
                        if tp.exists()
                        else f"{rd.name}/summary.json",
                    }
                )
            except Exception as e:
                logging.error(f"   [Leaderboard] Aggregation Failure for {rd}: {e}")
                continue

        stats.sort(key=lambda x: x["pass_rate"], reverse=True)
        return stats

    @staticmethod
    def generate_data(runs_dir: str, min_pass_rate: float = 0.0) -> list[dict]:
        """
        Returns structured leaderboard rows as a list of dicts.
        Suitable for JSON API responses and programmatic consumption.
        """
        return LeaderboardGenerator._collect_stats(runs_dir, min_pass_rate=min_pass_rate)

    @staticmethod
    def generate_markdown(runs_dir: str, min_pass_rate: float = 50.0) -> str:
        """Generates a Markdown leaderboard table from traces in a directory."""
        stats = LeaderboardGenerator._collect_stats(runs_dir, min_pass_rate=min_pass_rate)

        if not stats:
            return (
                "# \U0001f3c6 Agent Evaluation Leaderboard\n\n"
                "> [!WARNING]\n"
                "> No agents have achieved the minimum quality threshold (50% pass rate) yet. "
                "Keep iterating!\n"
            )

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
            md += (
                f"| {icon} | **{s['agent_display']}** | {s['pass_rate']:.1f}% | "
                f"{s['tasks']} | `{s['trace_file']}` |\n"
            )

        md += "\n*Generated by [AgentV](https://github.com/najeed/ai-agent-eval-harness)*\n"
        return md


def run_leaderboard(runs_dir: str, output_file: str = "LEADERBOARD.md"):
    """CLI helper for generating the leaderboard."""
    print(f"\n[Leaderboard] Aggregating results from: {runs_dir}...")
    content = LeaderboardGenerator.generate_markdown(runs_dir)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[OK] Leaderboard generated: {output_file}")
