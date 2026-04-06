# eval_runner/benchmarks/__init__.py
from .assistantbench import AssistantBenchmark
from .gaia import GAIABenchmark

BENCHMARK_REGISTRY = {"gaia": GAIABenchmark, "assistantbench": AssistantBenchmark}
