from __future__ import annotations
"""
runner.py

Orchestration logic for evaluation tasks.
Supports multi-attempt (pass@k) loops and plugin interception.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
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

    async def run(self, scenario: dict, attempts: int = 1, metadata: Optional[dict] = None) -> List[Any]:
        from .engine import AgentAdapterRegistry  # Avoid circular import
        from .tool_sandbox import ToolSandbox
        from .session import SessionManager
        import copy
        
        ctx = EvaluationContext(
            scenario_id=scenario.get("scenario_id", "unknown"),
            scenario_data=copy.deepcopy(scenario),
            metadata=dict(copy.deepcopy(metadata)) if metadata else {}
        )
        
        run_id = f"run-{ctx.scenario_id}-{int(asyncio.get_event_loop().time())}"
        EventEmitter.emit(CoreEvents.RUN_START, {
            "run_id": run_id, 
            "scenario": ctx.scenario_id, 
            "k_attempts": attempts
        })

        plugins.manager.trigger("before_evaluation", ctx)
        
        all_attempt_results = []
        
        for k in range(1, attempts + 1):
            session = SessionManager(scenario, metadata=ctx.metadata)
            attempt_results = await session.execute_tasks(k)
            all_attempt_results.append(attempt_results)

        # Cross-attempt aggregation (e.g. consistency)
        if attempts > 1:
            plugins.manager.trigger("on_metrics_calculated", ctx, all_attempt_results)

        plugins.manager.trigger("after_evaluation", ctx, all_attempt_results)
        
        # Calculate pass@k
        successful_attempts = 0
        for attempt_res in all_attempt_results:
            if all(all(m.get("success", False) for m in tr.get("metrics", [])) for tr in attempt_res):
                successful_attempts += 1
        
        pass_at_k = successful_attempts / attempts if attempts > 0 else 0.0
        EventEmitter.emit(CoreEvents.RUN_END, {
            "pass_at_k": pass_at_k, 
            "successful_attempts": successful_attempts, 
            "total_attempts": attempts
        })

        return all_attempt_results
