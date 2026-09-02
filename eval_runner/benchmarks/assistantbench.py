# eval_runner/benchmarks/assistantbench.py
from typing import Any


class AssistantBenchmark:
    """Loader and Adapter for the AssistantBench dataset."""

    @staticmethod
    def load(uri: str) -> list[dict[str, Any]]:
        """
        Load AssistantBench scenarios from the given URI.

        Raises NotImplementedError because fabricated dataset substitution is prohibited
        on an audit-defensible certification platform.  Runs sourced from an
        assistantbench:// URI must test against real dataset entries to produce valid
        evaluation evidence.

        To integrate the real dataset:
          1. Obtain the AssistantBench dataset (https://arxiv.org/abs/2407.15711).
          2. Replace this body with logic that reads the dataset file at ``uri``
             and converts each row to the AES 1.4 scenario schema.
        """
        raise NotImplementedError(
            f"AssistantBenchmark.load('{uri}') is not implemented. "
            "Fabricated data substitution is prohibited on this platform. "
            "Provide a real AssistantBench dataset path before using the "
            "assistantbench:// URI scheme in certification-grade evaluations."
        )
