import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RunPoint:
    run_id: str
    timestamp: str
    pass_rate: float


@dataclass
class RunTrendReport:
    agent_name: str
    window: int
    run_points: list[RunPoint]
    slope: float
    direction: str
    any_regression: bool


class RunTrendAnalyzer:
    """Compute trends from the authoritative run provider, not a run directory."""

    def __init__(
        self,
        *,
        run_store: Any,
        agent_name: str | None = None,
        window: int = 10,
        threshold: float = 0.0,
        context: dict[str, Any] | None = None,
    ):
        self.run_store = run_store
        self.agent_name = agent_name
        self.window = window
        self.threshold = threshold
        self.context = context

    def _ols_slope(self, y_values: list[float]) -> float:
        if len(y_values) < 2:
            return 0.0
        x_values = list(range(len(y_values)))
        try:
            from statistics import linear_regression

            slope, _ = linear_regression(x_values, y_values)
            return float(slope)
        except Exception as exc:
            logger.debug("Linear regression fallback activated: %s", exc, exc_info=True)
            mean_x = sum(x_values) / len(x_values)
            mean_y = sum(y_values) / len(y_values)
            numerator = sum(
                (x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values, strict=True)
            )
            denominator = sum((x - mean_x) ** 2 for x in x_values)
            return float(numerator / denominator) if denominator else 0.0

    def analyze(self) -> list[RunTrendReport]:
        agent_runs: dict[str, list[RunPoint]] = {}
        for run in self.run_store.list_runs(limit=10_000, context=self.context):
            run_id = run.get("run_id")
            if not isinstance(run_id, str):
                continue
            try:
                events = self.run_store.get_events(
                    run_id, offset=0, limit=10_000_000, context=self.context
                )
                manifest = self.run_store.get_manifest(run_id, context=self.context) or {}
            except Exception as exc:
                logger.warning("Skipping provider run %s: %s", run_id, exc)
                continue
            run_start = next((event for event in events if event.get("event") == "run_start"), {})
            metadata = (
                run_start.get("metadata") if isinstance(run_start.get("metadata"), dict) else {}
            )
            manifest_meta = (
                manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
            )
            resolved_agent = (
                manifest_meta.get("agent_name")
                or manifest.get("agent_name")
                or metadata.get("agent_name")
                or metadata.get("agent")
                or run_start.get("agent")
                or run.get("agent_id")
                or "unknown"
            )
            if self.agent_name and resolved_agent != self.agent_name:
                continue
            evaluations = [event for event in events if event.get("event") == "evaluation"]
            grouped: dict[str, list[bool]] = {}
            for event in evaluations:
                task_id = str(event.get("task_id") or len(grouped))
                grouped.setdefault(task_id, []).append(bool(event.get("success", False)))
            pass_rate = (
                sum(all(results) for results in grouped.values()) / len(grouped) if grouped else 0.0
            )
            timestamp = (
                run_start.get("timestamp")
                or run_start.get("_ts_iso")
                or run.get("created_at")
                or run.get("timestamp")
                or ""
            )
            agent_runs.setdefault(str(resolved_agent), []).append(
                RunPoint(run_id=run_id, timestamp=str(timestamp), pass_rate=pass_rate)
            )

        reports: list[RunTrendReport] = []
        for name, points in agent_runs.items():
            points.sort(key=lambda point: point.timestamp)
            window_points = points[-self.window :]
            slope = self._ols_slope([point.pass_rate for point in window_points])
            direction = (
                "degrading"
                if slope < -self.threshold
                else "improving"
                if slope > self.threshold
                else "stable"
            )
            reports.append(
                RunTrendReport(
                    agent_name=name,
                    window=len(window_points),
                    run_points=window_points,
                    slope=slope,
                    direction=direction,
                    any_regression=direction == "degrading",
                )
            )
        return reports
