from typing import Any

from ._dataset import load_benchmark


class AssistantBenchmark:
    """Project explicitly selected AssistantBench data into AES scenarios."""

    @staticmethod
    def load(uri: str) -> list[dict[str, Any]]:
        return load_benchmark(
            uri,
            "assistantbench",
            ("task", "question", "Question"),
            ("answer", "answers", "Final answer"),
        )
