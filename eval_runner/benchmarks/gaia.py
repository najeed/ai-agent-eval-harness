# eval_runner/benchmarks/gaia.py
import json
from pathlib import Path
from typing import List, Dict, Any


class GAIABenchmark:
    """Loader and Adapter for the GAIA (General AI Assistants) dataset."""

    @staticmethod
    def load(uri: str) -> List[Dict[str, Any]]:
        # uri format: gaia://2023_all (or similar)
        # For now, we expect the user to have the gaia parquet/json locally or we'd fetch from HF
        # Mocking the fetch logic for v1.0 RC
        print(f"      [Benchmark] Loading GAIA dataset from {uri}...")

        # In a real implementation, this would use `datasets` library to pull from HF
        # For the harness, we convert it to our Scenario format
        return [
            {
                "scenario_id": "gaia_validation_001",
                "title": "GAIA: Complex Information Extraction",
                "description": "The agent must find the total population of a specific city in 2022 and compare it to its neighboring city.",
                "use_case": "Research & Extraction",
                "core_function": "Multi-hop Reasoning",
                "industry": "General Intelligence",
                "tasks": [
                    {
                        "task_id": "step_1",
                        "description": "Identify the 2022 population for San Francisco and San Jose.",
                        "expected_outcome": "Correct population counts retrieved from a reliable source.",
                        "success_criteria": [
                            {"metric": "factual_accuracy", "threshold": 1.0}
                        ],
                    }
                ],
            },
            {
                "scenario_id": "gaia_validation_002",
                "title": "GAIA: Tool-Enabled Cross-Referencing",
                "description": "Given a list of scientific papers, find the most cited one and extract its main conclusion.",
                "use_case": "Academic Research",
                "core_function": "Academic Synthesis",
                "industry": "General Intelligence",
                "tasks": [
                    {
                        "task_id": "step_1",
                        "description": "Find citation counts for the provided DOIs.",
                        "expected_outcome": "Correct identification of the most cited paper.",
                        "success_criteria": [
                            {"metric": "factual_accuracy", "threshold": 0.9}
                        ],
                    }
                ],
            },
        ]
