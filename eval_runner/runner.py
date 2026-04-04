from __future__ import annotations

"""
runner.py

Orchestration logic for evaluation tasks.
Supports multi-attempt (pass@k) loops and plugin interception.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from pathlib import Path
from .context import EvaluationContext, TurnContext
from .events import EventEmitter, CoreEvents
from . import plugins
from . import metrics


class BaseRunner(ABC):
    """Abstract interface for evaluation runners."""

    @abstractmethod
    async def run(self, scenario: dict, attempts: int = 1, metadata: Optional[dict] = None) -> List[Any]:
        pass


class DefaultRunner(BaseRunner):
    """Standard implementation of the evaluation loop."""

    def __init__(self):
        """Sanity check for required directories."""
        Path("scenarios").mkdir(exist_ok=True)
        Path("industries").mkdir(exist_ok=True)
        Path(".aes").mkdir(exist_ok=True)

    async def run(self, scenario: dict, attempts: int = 1, metadata: Optional[dict] = None) -> List[Any]:
        from .engine import AgentAdapterRegistry  # Avoid circular import
        from .tool_sandbox import ToolSandbox
        from .session import SessionManager
        import copy

        ctx = EvaluationContext(
            scenario_id=scenario.get("scenario_id", "unknown"),
            scenario_data=copy.deepcopy(scenario),
            metadata=dict(copy.deepcopy(metadata)) if metadata else {},
            span_context=scenario.get("span_context"),
        )

        run_id = f"run-{ctx.scenario_id}-{int(asyncio.get_event_loop().time())}"
        EventEmitter.emit(
            CoreEvents.RUN_START,
            {"run_id": run_id, "scenario": ctx.scenario_id, "k_attempts": attempts},
            span_context=ctx.span_context
        )

        plugins.manager.trigger("before_evaluation", ctx)

        all_attempt_results = []

        EventEmitter.emit(CoreEvents.PHASE_START, {"phase": "pass_at_k_execution", "k": attempts}, span_context=ctx.span_context)
        for k in range(1, attempts + 1):
            session = SessionManager(scenario, metadata=ctx.metadata)
            attempt_results = await session.execute_tasks(k)
            all_attempt_results.append(attempt_results)
        EventEmitter.emit(CoreEvents.PHASE_END, {"phase": "pass_at_k_execution"}, span_context=ctx.scenario_id)

        # Cross-attempt aggregation (e.g. consistency)
        if attempts > 1:
            plugins.manager.trigger("on_metrics_calculated", ctx, all_attempt_results)

        plugins.manager.trigger("after_evaluation", ctx, all_attempt_results)
        
        # Calculate pass@k
        pass_at_k = self.calculate_pass_at_k(all_attempt_results, attempts)
        
        EventEmitter.emit(
            CoreEvents.RUN_END,
            {
                "pass_at_k": pass_at_k,
                "successful_attempts": sum(1 for res in all_attempt_results if self._is_attempt_successful(res)),
                "total_attempts": attempts,
            },
            span_context=ctx.span_context
        )

        return all_attempt_results

    def _is_attempt_successful(self, attempt_res: List[Dict[str, Any]]) -> bool:
        """Helper to determine if an attempt (sequence of tasks) was fully successful."""
        if not attempt_res:
            return False
        return all(
            len(tr.get("metrics", [])) > 0 and all(m.get("success", False) for m in tr.get("metrics", []))
            for tr in attempt_res
        )

    def calculate_pass_at_k(self, all_results: List[List[Dict[str, Any]]], k: int) -> float:
        """Calculates the pass@k metric (percentage of successful attempts)."""
        if k <= 0:
            return 0.0
        successful = sum(1 for res in all_results if self._is_attempt_successful(res))
        return float(successful) / k
