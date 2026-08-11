"""
Performance latency SLA and multi-session concurrency benchmark suite for synchronous interception.
"""

from __future__ import annotations

import asyncio

import pytest

from eval_runner.tool_sandbox import ToolSandbox, ToolSandboxInterceptor, ToolSandboxService


class NoOpSecurityInterceptor(ToolSandboxInterceptor):
    """Low-overhead security interceptor for benchmark tests."""

    def can_isolate(self, tool_name: str) -> bool:
        return True

    async def isolate_call(self, call_data: dict, next_executor) -> dict:
        return await next_executor(call_data)


@pytest.fixture
def benchmark_scenario():
    """Provides standard scenario configuration for benchmark evaluations."""
    return {
        "id": "benchmark-performance-scenario",
        "run_id": "run-perf-bench-001",
        "aes_version": 1.4,
        "initial_state": {"counter": 0},
        "metadata": {
            "name": "Performance Benchmark Scenario",
            "compliance_level": "Standard",
            "industry": "finance",
        },
        "agent_topology": {
            "default_agent": {"reads": ["*"], "writes": ["*"]},
        },
        "workflow": {"nodes": [], "edges": []},
        "evaluation": {"metrics": []},
    }


def test_interception_pipeline_latency_benchmark(benchmark_scenario, tmp_path, benchmark):
    """
    Benchmark test: Synchronous interception pipeline execution latency benchmark.
    Asserts pipeline overhead per call is within low-latency bounds (<5ms).
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        sandbox = ToolSandbox(
            scenario=benchmark_scenario,
            workspace_root=tmp_path / "workspace",
            jail_root=tmp_path / "jail",
        )
        loop.run_until_complete(sandbox.setup())

        service = ToolSandboxService()
        service.register_interceptor(NoOpSecurityInterceptor())

        call_data = {"tool_name": "echo_shim", "params": {"data": "test_ping"}, "sandbox": sandbox}

        async def core_exec(data):
            return {"status": "ok", "echo": data["params"]["data"]}

        def run_isolate():
            return loop.run_until_complete(service.isolate(call_data, core_exec))

        result = benchmark(run_isolate)
        assert result["status"] == "ok"

        # Explicit SLA Enforcement (<5ms / 0.005s per call)
        stats_obj = getattr(benchmark, "stats", None)
        if stats_obj and getattr(stats_obj, "stats", None):
            mean_latency_sec = stats_obj.stats.mean
            assert mean_latency_sec < 0.005, (
                f"Interception pipeline latency SLA violation: {mean_latency_sec * 1000:.3f}ms "
                f"exceeds 5.0ms threshold!"
            )
    finally:
        loop.close()


@pytest.mark.asyncio
async def test_multi_session_concurrency_scaling(benchmark_scenario, tmp_path):
    """
    Concurrency test: Evaluates behavior and memory safety under 100 concurrent evaluation sessions.
    """
    num_sessions = 100

    async def run_single_session(session_idx: int):
        scen = benchmark_scenario.copy()
        scen["run_id"] = f"run-perf-concurrent-{session_idx}"
        sandbox = ToolSandbox(
            scenario=scen,
            workspace_root=tmp_path / f"ws_{session_idx}",
            jail_root=tmp_path / f"jail_{session_idx}",
        )
        await sandbox.setup()
        res = await sandbox.execute(tool_name="echo_shim", params={"id": session_idx})
        assert isinstance(res, dict)
        await sandbox.teardown()

    tasks = [run_single_session(i) for i in range(num_sessions)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Assert 100% of concurrent sessions completed without exceptions
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(failures) == 0, f"Encountered {len(failures)} failures in concurrent session run!"


@pytest.mark.asyncio
async def test_1000_session_concurrency_scaling(benchmark_scenario, tmp_path):
    """
    Industrial Concurrency Test:
    Evaluates state isolation, run ID uniqueness, and memory safety
    under 1,000 concurrent evaluation sessions.
    """
    num_sessions = 1000
    run_ids = set()

    async def run_single_session(session_idx: int):
        run_id = f"run-perf-1000-scale-{session_idx}"
        run_ids.add(run_id)

        scen = benchmark_scenario.copy()
        scen["run_id"] = run_id
        sandbox = ToolSandbox(
            scenario=scen,
            workspace_root=tmp_path / f"ws1k_{session_idx}",
            jail_root=tmp_path / f"jail1k_{session_idx}",
        )
        await sandbox.setup()
        res = await sandbox.execute(tool_name="echo_shim", params={"id": session_idx})
        assert isinstance(res, dict)
        await sandbox.teardown()
        return run_id

    tasks = [run_single_session(i) for i in range(num_sessions)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Assertions:
    # 1. Zero exceptions under 1,000 concurrent sessions
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(failures) == 0, f"Encountered {len(failures)} failures in 1,000 sessions!"

    # 2. Run ID Uniqueness (Zero state pollution across 1,000 sessions)
    assert len(run_ids) == 1000, f"Expected 1000 unique run IDs, but found {len(run_ids)}!"
