# eval_runner/benchmarks/__init__.py
from .gaia import GAIABenchmark
from .assistantbench import AssistantBenchmark

BENCHMARK_REGISTRY = {
    "gaia": GAIABenchmark,
    "assistantbench": AssistantBenchmark
}
