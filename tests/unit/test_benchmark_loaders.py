"""
tests/unit/test_benchmark_loaders.py

Verifies that the benchmark loader adapters fail closed with NotImplementedError
rather than silently substituting fabricated scenarios. Any gaia:// or
assistantbench:// URI-sourced run must be evaluated against real data.
"""

import pytest

from eval_runner.benchmarks import BENCHMARK_REGISTRY
from eval_runner.benchmarks.assistantbench import AssistantBenchmark
from eval_runner.benchmarks.gaia import GAIABenchmark


class TestGAIABenchmark:
    def test_load_raises_not_implemented(self):
        """GAIABenchmark.load() must raise NotImplementedError — no fabricated data."""
        with pytest.raises(NotImplementedError) as exc_info:
            GAIABenchmark.load("2023_all")
        msg = str(exc_info.value)
        assert "GAIABenchmark" in msg
        assert "2023_all" in msg
        assert "prohibited" in msg.lower()

    def test_load_any_uri_raises(self):
        """The error must be raised for any URI, not just known ones."""
        with pytest.raises(NotImplementedError):
            GAIABenchmark.load("")
        with pytest.raises(NotImplementedError):
            GAIABenchmark.load("validation")
        with pytest.raises(NotImplementedError):
            GAIABenchmark.load("some/local/path.json")

    def test_registry_entry_is_gaia_class(self):
        """BENCHMARK_REGISTRY['gaia'] must be the GAIABenchmark class."""
        assert BENCHMARK_REGISTRY["gaia"] is GAIABenchmark


class TestAssistantBenchmark:
    def test_load_raises_not_implemented(self):
        """AssistantBenchmark.load() must raise NotImplementedError — no fabricated data."""
        with pytest.raises(NotImplementedError) as exc_info:
            AssistantBenchmark.load("v1")
        msg = str(exc_info.value)
        assert "AssistantBenchmark" in msg
        assert "prohibited" in msg.lower()

    def test_load_any_uri_raises(self):
        """The error must be raised for any URI argument."""
        with pytest.raises(NotImplementedError):
            AssistantBenchmark.load("")
        with pytest.raises(NotImplementedError):
            AssistantBenchmark.load("train")

    def test_registry_entry_is_assistantbench_class(self):
        """BENCHMARK_REGISTRY['assistantbench'] must be the AssistantBenchmark class."""
        assert BENCHMARK_REGISTRY["assistantbench"] is AssistantBenchmark


class TestBenchmarkLoaderIntegration:
    """Integration tests via the loader's URI dispatch path."""

    def test_gaia_uri_raises_via_loader(self):
        """loader.load_scenario('gaia://...') must propagate NotImplementedError."""
        from eval_runner.loader import load_scenario

        with pytest.raises(NotImplementedError):
            load_scenario("gaia://2023_all")

    def test_assistantbench_uri_raises_via_loader(self):
        """loader.load_scenario('assistantbench://...') must propagate NotImplementedError."""
        from eval_runner.loader import load_scenario

        with pytest.raises(NotImplementedError):
            load_scenario("assistantbench://v1")
