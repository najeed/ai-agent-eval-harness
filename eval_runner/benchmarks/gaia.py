from typing import Any

from ._dataset import load_benchmark


class GAIABenchmark:
    """Project explicitly selected GAIA data into AES scenarios."""

    @staticmethod
    def load(uri: str) -> list[dict[str, Any]]:
        return load_benchmark(uri, "gaia", ("Question", "question"), ("Final answer", "answer"))
