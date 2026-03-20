"""
publication_plugin.py (v3)

Advanced publication plugin capturing statistical rigor, cost, and failure taxonomy.
Supports A/B testing and regression detection.
"""

import json
import math
import hashlib
import yaml
from pathlib import Path
from datetime import datetime
from .plugins import BaseEvalPlugin
from .context import EvaluationContext
from .taxonomy import FailureTaxonomy
from . import config


class PublicationPlugin(BaseEvalPlugin):
    """Aggregates results into publication-ready slices with advanced stats and rigor."""

    def __init__(self):
        super().__init__()
        self.config = self._load_config()

    def _load_config(self):
        # Check both root and publication_suite folder for self-containment
        paths = [Path("config.yaml"), Path("scripts/publication_suite/config.yaml")]
        for p in paths:
            if p.exists():
                with open(p, "r") as f:
                    return yaml.safe_load(f)
        return {"pricing": {}, "confidence_level": 0.95}

    def after_evaluation(self, context: EvaluationContext, results: list):
        """Aggregate and export advanced metrics after evaluation."""
        attempts = results if isinstance(results[0], list) else [results]

        scenario = context.scenario_data
        agent_name = context.metadata.get("agent_name", "unknown")

        # Calculate Cross-Run Stats
        pass_flags = []
        latencies = []
        costs = []
        failure_counts = {}

        for attempt in attempts:
            is_success = all(
                all(m.get("success", False) for m in tr.get("metrics", []))
                for tr in attempt
            )
            pass_flags.append(is_success)

            # Aggregate per-attempt metrics
            for task_res in attempt:
                latencies.append(task_res.get("metrics_extra", {}).get("latency", 0.0))
                costs.append(self._calculate_cost(task_res, agent_name))

                if not is_success:
                    tag = FailureTaxonomy.classify(task_res)
                    failure_counts[tag] = failure_counts.get(tag, 0) + 1

        pass_rate = sum(pass_flags) / len(pass_flags)

        summary = {
            "run_fingerprint": self._generate_fingerprint(context),
            "scenario_id": context.scenario_id,
            "agent": agent_name,
            "timestamp": datetime.now().isoformat(),
            "runs": len(pass_flags),
            "metrics": {
                "pass_rate": pass_rate,
                "pass_at_k": self._calculate_pass_at_k(pass_flags),
                "avg_latency": sum(latencies) / len(latencies) if latencies else 0,
                "p95_latency": self._percentile(latencies, 95) if latencies else 0,
                "avg_cost": sum(costs) / len(costs) if costs else 0,
                "confidence_interval": self._wilson_score_interval(
                    pass_rate, len(pass_flags)
                ),
                "failure_distribution": {
                    k: v / len(latencies) for k, v in failure_counts.items()
                },
            },
            "metadata": {
                "industry": scenario.get("industry"),
                "use_case": scenario.get("use_case"),
                "difficulty": scenario.get("difficulty"),
            },
        }

        self._export_results(summary)
        self._check_regression(summary)

    def _calculate_cost(self, task_res, agent_name):
        tokens = task_res.get("metrics_extra", {}).get("total_tokens", 0)
        pricing = self.config.get("pricing", {})
        # Find matching pricing key
        rate = 0.0
        # Ensure agent_name is a string to avoid NoneType.lower() error
        safe_name = (agent_name or "unknown").lower()
        for k, v in pricing.items():
            if k in safe_name:
                rate = v / 1000000.0  # Convert from 1M to per-token
                break
        return tokens * rate

    def _generate_fingerprint(self, context):
        args = context.metadata.get("args", {})
        seed = args.get("seed", 0) or 0
        scenario_id = context.scenario_id
        raw = f"{scenario_id}-{seed}-{datetime.now().strftime('%Y%m%d')}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    def _wilson_score_interval(self, p, n):
        if n == 0:
            return 0.0
        z = 1.96  # 95% confidence
        denominator = 1 + z**2 / n
        centre_adj_probability = p + z**2 / (2 * n)
        adjusted_standard_deviation = math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)

        upper = (centre_adj_probability + z * adjusted_standard_deviation) / denominator
        lower = (centre_adj_probability - z * adjusted_standard_deviation) / denominator
        return (upper - lower) / 2  # Return as +/- margin

    def _calculate_pass_at_k(self, pass_flags):
        n = len(pass_flags)
        c = sum(pass_flags)
        res = {}
        for k in [1, 3, 5, 10]:
            if n < k:
                continue
            # Simplified pass@k estimation
            res[f"pass@{k}"] = (
                1 - math.comb(n - c, k) / math.comb(n, k) if n - c >= k else 1.0
            )
        return res

    def _percentile(self, data, p):
        if not data:
            return 0
        s = sorted(data)
        return s[int(len(s) * p / 100)]

    def _export_results(self, summary):
        path = Path("results/publication_results.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(summary) + "\n")

    def _check_regression(self, summary):
        baseline_path = Path("results/baselines.json")
        if not baseline_path.exists():
            return

        try:
            with open(baseline_path, "r") as f:
                baselines = json.load(f)

            s_id = summary["scenario_id"]
            if s_id in baselines:
                old_rate = baselines[s_id].get("pass_rate", 0)
                new_rate = summary["metrics"]["pass_rate"]
                threshold = self.config.get("regression_threshold", 0.03)

                if old_rate - new_rate > threshold:
                    print(
                        f"   [PublicationPlugin] 🚩 REGRESSION DETECTED on {s_id}: {old_rate:.2f} -> {new_rate:.2f}"
                    )
        except:
            pass

    def on_register_commands(self, registry):
        pass
