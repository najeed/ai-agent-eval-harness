# eval_runner/benchmarks/assistantbench.py
from typing import Any


class AssistantBenchmark:
    """Loader and Adapter for the AssistantBench dataset."""

    @staticmethod
    def load(uri: str) -> list[dict[str, Any]]:
        print(f"      [Benchmark] Loading mock AssistantBench dataset from {uri}...")
        return [
            {
                "aes_version": 1.4,
                "metadata": {
                    "id": f"ab_{i}",
                    "name": f"AssistantBench Task {i}",
                    "compliance_level": "Standard",
                },
                "id": f"ab_{i}",
                "description": "AssistantBench web-search/tool task.",
                "industry": "General",
                "workflow": {
                    "nodes": [
                        {
                            "id": "solve_task",
                            "task_description": "Solve the AssistantBench web-search/tool task.",
                            "expected_outcome": [
                                {
                                    "target": "message",
                                    "expected": "Goal reached via tools",
                                    "mode": "regex",
                                }
                            ],
                            "success_criteria": [
                                {"metric": "state_verification", "threshold": 1.0}
                            ],
                        }
                    ],
                    "edges": [],
                },
            }
            for i in range(2)
        ]
