from __future__ import annotations

"""
runner.py

Orchestration logic for evaluation tasks.
Supports multi-attempt (pass@k) loops and plugin interception.
"""

import asyncio  # noqa: E402
import logging  # noqa: E402
from abc import ABC, abstractmethod  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from . import events, plugins  # noqa: E402
from .context import EvaluationContext  # noqa: E402

logger = logging.getLogger(__name__)

# from .events import CoreEvents, EventEmitter # Removed to avoid confusion


class BaseRunner(ABC):
    """Abstract interface for evaluation runners."""

    @abstractmethod
    async def run(
        self,
        scenario: dict,
        attempts: int = 1,
        run_id: str | None = None,
        seed: int | None = None,
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
        seed: int | None = None,
        metadata: dict | None = None,
        max_turns: int | None = None,
        cancellation_event: Any | None = None,
        resumption_checkpoint: dict | None = None,
    ) -> list[Any]:
        import copy

        from .session import SessionManager

        # [Forensic Hardening] Centralized Identifier Resolution
        effective_run_id = run_id or f"run-{scenario['id']}-{int(asyncio.get_event_loop().time())}"

        # Resolve OpenTelemetry parent context/span
        otel_ctx = None
        try:
            from opentelemetry import trace
            from opentelemetry.trace import propagation

            tracer = trace.get_tracer("agentv")
            parent_context = None
            if metadata and "traceparent" in metadata:
                parent_context = propagation.extract({"traceparent": metadata["traceparent"]})
            elif scenario.get("span_context"):
                parent_context = propagation.extract(scenario["span_context"])

            span = tracer.start_span(
                name=f"agentv.run.{scenario['id']}",
                context=parent_context,
            )
            span.set_attribute("agentv.run_id", effective_run_id)
            span.set_attribute("agentv.scenario_id", scenario["id"])
            span.set_attribute("agentv.attempts", attempts)

            otel_ctx = trace.set_span_in_context(span, parent_context)
        except Exception as e:
            import sys

            sys.stderr.write(f"   [Telemetry] Warning: Failed to initialize OTel span: {e}\n")

        ctx = EvaluationContext(
            identifier=scenario.get("id") or scenario.get("metadata", {}).get("name", "unknown"),
            scenario_data=copy.deepcopy(scenario),
            run_id=effective_run_id,
            seed=seed,
            metadata=dict(copy.deepcopy(metadata)) if metadata else {},
            span_context=scenario.get("span_context"),
            otel_context=otel_ctx,
        )

        try:
            events.emit(
                events.CoreEvents.RUN_START,
                {
                    "run_id": effective_run_id,
                    "scenario": ctx.identifier,
                    "k_attempts": attempts,
                    "workflow": ctx.scenario_data.get("workflow"),
                    "scenario_data": dict(ctx.scenario_data) if ctx.scenario_data else {},
                },
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
                if cancellation_event and getattr(cancellation_event, "is_set", lambda: False)():
                    break

                current_seed = None
                # [Industrial Determinism] Final Seed = Base Seed + Run Index
                if ctx.seed is not None:
                    current_seed = ctx.seed + (k - 1)
                    import random

                    random.seed(current_seed)
                    print(f"      [Runner] Seeding attempt {k} with {current_seed}")

                # Inject max_turns into scenario copy for SessionManager consumption
                scenario_copy = copy.deepcopy(scenario)
                if max_turns:
                    scenario_copy["max_turns"] = max_turns

                session = SessionManager(
                    effective_run_id,
                    scenario_copy,
                    metadata=ctx.metadata,
                    seed=current_seed,
                    cancellation_event=cancellation_event,
                    resumption_checkpoint=resumption_checkpoint,
                )
                attempt_results = await session.execute_tasks(k)

                # [Forensic Sync] propagate resolved routing (e.g. Port 8000)
                # Since ctx.metadata is frozen (MappingProxyType), we use the bypass pattern
                # to ensure the ReportingPlugin sees the final resolved state.
                from .context import _freeze_dict

                new_meta = dict(ctx.metadata)
                new_meta.update(session.metadata)
                object.__setattr__(ctx, "metadata", _freeze_dict(new_meta))

                all_attempt_results.append(attempt_results)
            events.emit(
                events.CoreEvents.PHASE_END,
                {"phase": "pass_at_k_execution"},
                span_context=ctx.span_context,
            )

            pass_at_k = 0.0
            try:
                # Cross-attempt aggregation (e.g. consolidation)
                if attempts > 1:
                    plugins.manager.trigger("on_metrics_calculated", ctx, all_attempt_results)

                # Calculate pass@k
                pass_at_k = self.calculate_pass_at_k(all_attempt_results, attempts)
            except Exception as e:
                import traceback

                tb = traceback.format_exc()
                print(f"      [Runner Error] Failed to generate reports or calculate pass@k: {e}")
                print(tb)
                events.emit(
                    events.CoreEvents.ERROR,
                    {"message": f"Runner Post-Process Error: {e}", "traceback": tb},
                )

            events.emit(
                events.CoreEvents.RUN_END,
                {
                    "pass_at_k": pass_at_k,
                    "successful_attempts": sum(
                        1 for res in all_attempt_results if self._is_attempt_successful(res)
                    ),
                    "total_attempts": attempts,
                    "metadata": dict(ctx.metadata),
                },
                span_context=ctx.span_context,
            )

            events.emit(
                events.CoreEvents.STRATEGY_END,
                {"strategy": "pass_at_k", "status": "success" if pass_at_k > 0 else "failure"},
                span_context=ctx.span_context,
            )

            # Trigger after_evaluation lifecycle hook after terminal events are emitted
            plugins.manager.trigger("after_evaluation", ctx, all_attempt_results)

            return all_attempt_results
        finally:
            if ctx.otel_context:
                try:
                    from opentelemetry import trace

                    span = trace.get_current_span(ctx.otel_context)
                    if span:
                        span.end()
                except Exception as e:
                    import sys

                    sys.stderr.write(f"   [Telemetry] Warning: Failed to clean up OTel span: {e}\n")

    def _is_attempt_successful(self, attempt_results: list[dict]) -> bool:
        if not attempt_results:
            return False
        for res in attempt_results:
            if res.get("status") != "success":
                return False
            for m in res.get("metrics", []):
                if not m.get("passed", True):
                    return False
        return True

    def calculate_pass_at_k(self, all_results: list[list[dict[str, Any]]], k: int) -> float:
        """Calculates the pass@k metric (percentage of successful attempts)."""
        if k <= 0:
            return 0.0
        successful = sum(1 for res in all_results if self._is_attempt_successful(res))
        return float(successful) / k


def run_scenario(
    scenario: dict,
    attempts: int = 1,
    run_id: str | None = None,
    seed: int | None = None,
    metadata: dict | None = None,
    max_turns: int | None = None,
    cancellation_event: Any | None = None,
    resumption_checkpoint: dict | None = None,
) -> list[Any]:
    """
    Synchronous entry point that orchestrates evaluation via DefaultRunner.
    Used by InProcessExecutionBackend and CLI triggers.
    """
    runner = DefaultRunner()
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(
                asyncio.run,
                runner.run(
                    scenario=scenario,
                    attempts=attempts,
                    run_id=run_id,
                    seed=seed,
                    metadata=metadata,
                    max_turns=max_turns,
                    cancellation_event=cancellation_event,
                    resumption_checkpoint=resumption_checkpoint,
                ),
            ).result()
    else:
        return loop.run_until_complete(
            runner.run(
                scenario=scenario,
                attempts=attempts,
                run_id=run_id,
                seed=seed,
                metadata=metadata,
                max_turns=max_turns,
                cancellation_event=cancellation_event,
                resumption_checkpoint=resumption_checkpoint,
            )
        )
