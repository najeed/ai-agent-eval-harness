# eval_runner/benchmarks/assistantbench.py
from typing import List, Dict, Any

class AssistantBenchmark:
    """Loader and Adapter for the AssistantBench dataset."""
    
    @staticmethod
    def load(uri: str) -> List[Dict[str, Any]]:
        print(f"      [Benchmark] Loading AssistantBench dataset from {uri}...")
        return [
            {
                "id": f"ab_{i}",
                "task_description": "Solve the AssistantBench web-search/tool task.",
                "initial_state": {},
                "success_criteria": [
                    {"type": "state_verification", "path": "goal_reached", "value": True}
                ]
            } for i in range(2)
        ]
