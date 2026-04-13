from __future__ import annotations

"""
runner.py

Orchestration logic for evaluation tasks.
Supports multi-attempt (pass@k) loops and plugin interception.
"""

import asyncio  # noqa: E402
from abc import ABC, abstractmethod  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from . import events, plugins  # noqa: E402
from .context import EvaluationContext  # noqa: E402

# from .events import CoreEvents, EventEmitter # Removed to avoid confusion


class BaseRunner(ABC):
    """Abstract interface for evaluation runners."""

    @abstractmethod
    async def run(
        self,
        scenario: dict,
        attempts: int = 1,
        run_id: str | None = None,
        metadata: dict | None = None,
        max_turns: int | None = None,
    ) -> list[Any]:
        pass


class DefaultRunner(BaseRunner):
    """Standard implementation of the evaluation loop."""

    def __init__(self):
        """Sanity check for required directories."""
        Path("scenarios").mkdir(exist_ok=True)
        Path("industries").mkdir(exist_ok=True)
        Path(".aes").mkdir(exist_ok=True)

    async def run(
        self,
        scenario: dict,
        attempts: int = 1,
        run_id: str | None = None,
        metadata: dict | None = None,
        max_turns: int | None = None,
    ) -> list[Any]:
        import copy

        from .session import SessionManager

        # [Forensic Hardening] Centralized Identifier Resolution
        # Identity is resolved and normalized in the core Loader (AES v1.4.0)
        # Authoritative field: scenario["id"]
        ctx = EvaluationContext(
            identifier=scenario["id"],
            scenario_data=copy.deepcopy(scenario),
            metadata=dict(copy.deepcopy(metadata)) if metadata else {},
            span_context=scenario.get("span_context"),
        )

        effective_run_id = run_id or f"run-{ctx.identifier}-{int(asyncio.get_event_loop().time())}"
        events.emit(
            events.CoreEvents.RUN_START,
            {"run_id": effective_run_id, "scenario": ctx.identifier, "k_attempts": attempts},
            span_context=ctx.span_context,
        )

        plugins.manager.trigger("before_evaluation", ctx)

        all_attempt_results = []

        # 🚀 STRATEGY: Mission-Level Telemetry
        events.emit(
            events.CoreEvents.STRATEGY_START,
            {"strategy": "pass_at_k", "k": attempts},
            span_context=ctx.span_context,
        )

        events.emit(
            events.CoreEvents.PHASE_START,
            {"phase": "pass_at_k_execution", "k": attempts},
            span_context=ctx.span_context,
        )
        for k in range(1, attempts + 1):
            # Inject max_turns into scenario copy for SessionManager consumption
            scenario_copy = copy.deepcopy(scenario)
            if max_turns:
                scenario_copy["max_turns"] = max_turns

            session = SessionManager(effective_run_id, scenario_copy, metadata=ctx.metadata)
            attempt_results = await session.execute_tasks(k)
            all_attempt_results.append(attempt_results)
        events.emit(
            events.CoreEvents.PHASE_END,
            {"phase": "pass_at_k_execution"},
            span_context=ctx.span_context,
        )

        # Cross-attempt aggregation (e.g. consistency)
        if attempts > 1:
            plugins.manager.trigger("on_metrics_calculated", ctx, all_attempt_results)

        plugins.manager.trigger("after_evaluation", ctx, all_attempt_results)

        # Calculate pass@k
        pass_at_k = self.calculate_pass_at_k(all_attempt_results, attempts)

        events.emit(
            events.CoreEvents.RUN_END,
            {
                "pass_at_k": pass_at_k,
                "successful_attempts": sum(
                    1 for res in all_attempt_results if self._is_attempt_successful(res)
                ),
                "total_attempts": attempts,
            },
            span_context=ctx.span_context,
        )

        events.emit(
            events.CoreEvents.STRATEGY_END,
            {"strategy": "pass_at_k", "status": "success" if pass_at_k > 0 else "failure"},
            span_context=ctx.span_context,
        )

        return all_attempt_results

    def _is_attempt_successful(self, attempt_res: list[dict[str, Any]]) -> bool:
        """Helper to determine if an attempt (sequence of tasks) was fully successful."""
        if not attempt_res:
            return False
        return all(
            len(tr.get("metrics", [])) > 0
            and all(m.get("success", False) for m in tr.get("metrics", []))
            for tr in attempt_res
        )

    def calculate_pass_at_k(self, all_results: list[list[dict[str, Any]]], k: int) -> float:
        """Calculates the pass@k metric (percentage of successful attempts)."""
        if k <= 0:
            return 0.0
        successful = sum(1 for res in all_results if self._is_attempt_successful(res))
        return float(successful) / k
