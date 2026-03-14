"""
aggregator.py

Statistical aggregator for the Advanced Publication Suite.
Processes run.jsonl files from a batch and computes publication metrics.
"""

import json
import math
import yaml
from pathlib import Path
from typing import List, Dict, Any
from taxonomy import FailureTaxonomy

class Aggregator:
    def __init__(self, manifest_path: str):
        self.manifest_path = Path(manifest_path)
        with open(self.manifest_path, "r") as f:
            self.manifest = json.load(f)
        self.config = self._load_config()

    def _load_config(self):
        config_path = Path("config.yaml")
        if config_path.exists():
            with open(config_path, "r") as f:
                return yaml.safe_load(f)
        return {"pricing": {}, "confidence_level": 0.95}

    def _calculate_cost(self, events: List[Dict[str, Any]]):
        # Scan events for token usage or tool calls
        total_tokens = 0
        for e in events:
            if e.get("event") == "agent_response":
                # Mock token count if not present in trace
                total_tokens += len(str(e.get("content", ""))) // 4
        
        pricing = self.config.get("pricing", {})
        rate = 0.0
        agent_name = self.manifest.get("agent_name", "").lower()
        for k, v in pricing.items():
            if k in agent_name:
                rate = v / 1000000.0
                break
        return total_tokens * rate

    def _wilson_score_interval(self, p, n):
        if n == 0: return 0.0
        z = 1.96
        denominator = 1 + z**2/n
        centre_adj_probability = p + z**2 / (2*n)
        adjusted_standard_deviation = math.sqrt((p*(1-p) + z**2 / (4*n)) / n)
        return (z * adjusted_standard_deviation) / denominator

    def process(self):
        print(f"📊 [Aggregator] Processing batch: {self.manifest['fingerprint']}")
        
        scenario_results = {}
        
        for run in self.manifest["runs"]:
            if not run["success"]: continue
            
            log_path = Path(run["log_path"])
            if not log_path.exists(): continue
            
            events = []
            with open(log_path, "r") as f:
                for line in f:
                    if line.strip(): events.append(json.loads(line))
            
            s_id = run["scenario"]
            if s_id not in scenario_results:
                scenario_results[s_id] = {"passes": [], "latencies": [], "costs": [], "failures": []}
            
            res = scenario_results[s_id]
            
            # Determine success from events
            eval_events = [e for e in events if e.get("event") == "evaluation"]
            is_success = all(e.get("success", False) for e in eval_events) if eval_events else False
            res["passes"].append(is_success)
            
            # Latency (simplified: time between run_start and run_end)
            start_event = next((e for e in events if e.get("event") == "run_start"), None)
            end_event = next((e for e in events if e.get("event") == "run_end"), None)
            if start_event and end_event:
                # Assuming timestamps are present
                pass # logic for time diff
                res["latencies"].append(2.5) # Mock for now
            
            res["costs"].append(self._calculate_cost(events))
            
            if not is_success:
                res["failures"].append(FailureTaxonomy.classify_from_events(events))

        # Final aggregation
        report = {
            "fingerprint": self.manifest["fingerprint"],
            "agent": self.manifest["agent_name"],
            "scenarios": {}
        }
        
        for s_id, data in scenario_results.items():
            n = len(data["passes"])
            pass_rate = sum(data["passes"]) / n if n > 0 else 0
            
            report["scenarios"][s_id] = {
                "pass_rate": pass_rate,
                "confidence_interval_95": self._wilson_score_interval(pass_rate, n),
                "avg_latency": sum(data["latencies"]) / len(data["latencies"]) if data["latencies"] else 0,
                "avg_cost": sum(data["costs"]) / len(data["costs"]) if data["costs"] else 0,
                "failure_distribution": {cat: data["failures"].count(cat)/len(data["failures"]) for cat in set(data["failures"])} if data["failures"] else {}
            }

        output_path = Path(self.manifest["base_dir"]) / "aggregated_results.json"
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)
            
        print(f"✅ [Aggregator] Aggregation complete: {output_path}")
        return output_path

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python aggregator.py <manifest_path>")
    else:
        agg = Aggregator(sys.argv[1])
        agg.process()
