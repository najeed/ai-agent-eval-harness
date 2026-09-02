# eval_runner/benchmarks/gaia.py
from typing import Any


class GAIABenchmark:
    """Loader and Adapter for the GAIA (General AI Assistants) dataset."""

    @staticmethod
    def load(uri: str) -> list[dict[str, Any]]:
        """
        Load GAIA benchmark scenarios from the given URI.

        Raises NotImplementedError because fabricated dataset substitution is prohibited
        on an audit-defensible certification platform.  Runs sourced from a gaia:// URI
        must test against the real GAIA dataset to produce valid evaluation evidence.

        To integrate the real dataset:
          1. Install the HuggingFace `datasets` library (``pip install datasets``).
          2. Replace this body with:
                from datasets import load_dataset
                ds = load_dataset("gaia-benchmark/GAIA", split=uri or "validation")
                return [_convert(row) for row in ds]
          3. Implement ``_convert`` to project each GAIA row to the AES 1.4 scenario schema.
        """
        raise NotImplementedError(
            f"GAIABenchmark.load('{uri}') is not implemented. "
            "Fabricated data substitution is prohibited on this platform. "
            "Provide a real GAIA dataset path or implement HuggingFace integration before "
            "using the gaia:// URI scheme in certification-grade evaluations."
        )
