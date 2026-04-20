# eval_runner/benchmarks/gaia.py
from typing import Any


class GAIABenchmark:
    """Loader and Adapter for the GAIA (General AI Assistants) dataset."""

    @staticmethod
    def load(uri: str) -> list[dict[str, Any]]:
        # uri format: gaia://2023_all (or similar)
        # For now, we expect the user to have the gaia parquet/json locally or we'd fetch from HF
        # Mocking the fetch logic for v1.0 RC
        print(f"      [Benchmark] Loading mock GAIA dataset from {uri}...")

        # In a real implementation, this would use `datasets` library to pull from HF
        # For the harness, we convert it to our Scenario format
        return [
            {
                "aes_version": 1.4,
                "metadata": {
                    "id": "gaia_validation_001",
                    "name": "GAIA: Complex Information Extraction",
                    "compliance_level": "Standard",
                },
                "id": "gaia_validation_001",
                "description": (
                    "The agent must find the total population of a specific city in 2022 "
                    "and compare it to its neighboring city."
                ),
                "industry": "General Intelligence",
                "workflow": {
                    "nodes": [
                        {
                            "id": "step_1",
                            "task_description": (
                                "Identify the 2022 population for San Francisco and San Jose."
                            ),
                            "expected_outcome": [
                                {
                                    "target": "message",
                                    "expected": (
                                        "Correct population counts retrieved from a "
                                        "reliable source."
                                    ),
                                    "mode": "regex",
                                }
                            ],
                            "success_criteria": [{"metric": "factual_accuracy", "threshold": 1.0}],
                        }
                    ],
                    "edges": [],
                },
            },
            {
                "aes_version": 1.4,
                "metadata": {
                    "id": "gaia_validation_002",
                    "name": "GAIA: Tool-Enabled Cross-Referencing",
                    "compliance_level": "Standard",
                },
                "id": "gaia_validation_002",
                "description": (
                    "Given a list of scientific papers, find the most cited one "
                    "and extract its main conclusion."
                ),
                "industry": "General Intelligence",
                "workflow": {
                    "nodes": [
                        {
                            "id": "step_1",
                            "task_description": "Find citation counts for the provided DOIs.",
                            "expected_outcome": [
                                {
                                    "target": "message",
                                    "expected": "Correct identification of the most cited paper.",
                                    "mode": "regex",
                                }
                            ],
                            "success_criteria": [{"metric": "factual_accuracy", "threshold": 0.9}],
                        }
                    ],
                    "edges": [],
                },
            },
        ]
