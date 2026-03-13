# eval_runner/benchmarks/assistantbench.py
from typing import List, Dict, Any

class AssistantBenchmark:
    """Loader and Adapter for the AssistantBench dataset."""
    
    @staticmethod
    def load(uri: str) -> List[Dict[str, Any]]:
        print(f"      [Benchmark] Loading AssistantBench dataset from {uri}...")
        return [
            {
                "scenario_id": f"ab_{i}",
                "title": f"AssistantBench Task {i}",
                "description": "AssistantBench web-search/tool task.",
                "use_case": "Web Assistant",
                "core_function": "Search",
                "industry": "General",
                "tasks": [
                    {
                        "task_id": "solve_task",
                        "description": "Solve the AssistantBench web-search/tool task.",
                        "expected_outcome": "Goal reached via tools",
                        "success_criteria": [
                            {"metric": "state_verification", "threshold": 1.0}
                        ]
                    }
                ]
            } for i in range(2)
        ]
