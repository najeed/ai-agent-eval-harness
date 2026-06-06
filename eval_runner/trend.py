import datetime
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .trace_utils import load_events

logger = logging.getLogger(__name__)


@dataclass
class RunPoint:
    run_id: str
    timestamp: str
    pass_rate: float  # successful_tasks / total_tasks


@dataclass
class RunTrendReport:
    agent_name: str
    window: int
    run_points: list[RunPoint]
    slope: float  # OLS slope (negative = regression)
    direction: str  # "improving" | "stable" | "degrading"
    any_regression: bool  # True if slope < -threshold


class RunTrendAnalyzer:
    def __init__(
        self,
        run_log_dir: str,
        agent_name: str | None = None,
        window: int = 10,
        threshold: float = 0.0,
    ):
        self.run_log_dir = Path(run_log_dir)
        self.agent_name = agent_name
        self.window = window
        self.threshold = threshold

    def _ols_slope(self, y_values: list[float]) -> float:
        if len(y_values) < 2:
            return 0.0
        x_values = list(range(len(y_values)))
        try:
            from statistics import linear_regression

            slope, _ = linear_regression(x_values, y_values)
            return float(slope)
        except Exception:
            # Fallback manual OLS slope calculation (e.g. if statistics.linear_regression fails)
            n = len(x_values)
            mean_x = sum(x_values) / n
            mean_y = sum(y_values) / n
            num = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values, strict=True))
            den = sum((x - mean_x) ** 2 for x in x_values)
            if den == 0:
                return 0.0
            return float(num / den)

    def analyze(self) -> list[RunTrendReport]:
        if not self.run_log_dir.exists():
            raise FileNotFoundError(f"Run log directory does not exist: {self.run_log_dir}")

        # Scan for run traces: supports both vault-style (runs/*/run.jsonl) and flat-style
        vault_traces = list(self.run_log_dir.glob("*/run.jsonl"))
        flat_traces = list(self.run_log_dir.glob("*.jsonl"))

        # De-duplicate paths
        seen = set()
        all_traces = []
        for tp in vault_traces + flat_traces:
            resolved = tp.resolve()
            if resolved not in seen:
                seen.add(resolved)
                all_traces.append(tp)

        # Parse and gather points
        agent_runs = {}

        for tp in all_traces:
            try:
                events = load_events(tp)
                if not events:
                    continue

                run_start = next((e for e in events if e.get("event") == "run_start"), {})
                meta = run_start.get("metadata", {})

                # Attributing agent name: Manifest > Event Metadata > Directory/Filename
                manifest_path = tp.parent / "run_manifest.json"
                manifest_data = {}
                if manifest_path.exists():
                    try:
                        with open(manifest_path, encoding="utf-8") as f:
                            manifest_data = json.load(f)
                    except Exception:
                        pass

                resolved_agent = (
                    manifest_data.get("metadata", {}).get("agent_name")
                    or meta.get("agent_name")
                    or meta.get("agent")
                    or run_start.get("agent")
                )

                if not resolved_agent:
                    resolved_agent = tp.parent.name if tp.name == "run.jsonl" else tp.stem

                # Filter by agent name if specified
                if self.agent_name and resolved_agent != self.agent_name:
                    continue

                # Run ID
                run_id = (
                    manifest_data.get("run_id") or run_start.get("run_id") or tp.parent.name
                    if tp.name == "run.jsonl"
                    else tp.stem
                )

                # Timestamp
                ts = run_start.get("timestamp") or run_start.get("_ts_iso")
                if not ts:
                    ts = datetime.datetime.fromtimestamp(tp.stat().st_mtime).isoformat()

                # Pass rate
                evals = [e for e in events if e.get("event") == "evaluation"]
                if not evals:
                    pass_rate = 0.0
                else:
                    total_tasks = len(set(e.get("task_id") for e in evals))
                    task_metrics = {}
                    for e in evals:
                        tid = e.get("task_id")
                        if tid not in task_metrics:
                            task_metrics[tid] = []
                        task_metrics[tid].append(e.get("success", False))

                    successful_tasks = 0
                    for _tid, results in task_metrics.items():
                        if all(results):
                            successful_tasks += 1

                    pass_rate = (successful_tasks / total_tasks) if total_tasks > 0 else 0.0

                point = RunPoint(run_id=run_id, timestamp=ts, pass_rate=pass_rate)
                if resolved_agent not in agent_runs:
                    agent_runs[resolved_agent] = []
                agent_runs[resolved_agent].append(point)

            except Exception as e:
                logger.error(f"[TrendAnalyzer] Skip trace {tp} due to parse error: {e}")
                continue

        reports = []
        for name, points in agent_runs.items():
            # Sort chronologically by timestamp
            points.sort(key=lambda p: p.timestamp)

            # Get the recent window of points
            window_points = points[-self.window :]

            # Compute slope
            slope = self._ols_slope([p.pass_rate for p in window_points])

            # Determine direction and regression status
            # slope threshold check
            if slope < -self.threshold:
                direction = "degrading"
                any_regression = True
            elif slope > self.threshold:
                direction = "improving"
                any_regression = False
            else:
                direction = "stable"
                any_regression = False

            reports.append(
                RunTrendReport(
                    agent_name=name,
                    window=len(window_points),
                    run_points=window_points,
                    slope=slope,
                    direction=direction,
                    any_regression=any_regression,
                )
            )

        return reports
