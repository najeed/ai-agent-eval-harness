from __future__ import annotations

"""
runner.py

Orchestration logic for evaluation tasks.
Supports multi-attempt (pass@k) loops and plugin interception.
Returns first-class EvaluationResult contracts.
"""

import asyncio  # noqa: E402
import logging  # noqa: E402
from abc import ABC, abstractmethod  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from agentv_runtime.results import EvaluationResult  # noqa: E402

from . import events, plugins  # noqa: E402
from .context import EvaluationContext  # noqa: E402
from .reproducibility import build_reproducibility_contract, fingerprint  # noqa: E402
from .statistics import compute_attempt_statistics  # noqa: E402

logger = logging.getLogger(__name__)


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
    ) -> EvaluationResult:
        pass


class DefaultRunner(BaseRunner):
    """Standard implementation of the evaluation loop."""

    def __init__(
        self,
        run_store: Any | None = None,
        config_resolver: Any | None = None,
        artifact_store: Any | None = None,
        checkpoint_store: Any | None = None,
        policy_evaluator: Any | None = None,
        signing_backend: Any | None = None,
        execution_backend: Any | None = None,
    ):
        """Sanity check for required directories and initialize storage / config wiring."""
        Path("scenarios").mkdir(exist_ok=True)
        Path("industries").mkdir(exist_ok=True)
        Path(".aes").mkdir(exist_ok=True)

        from eval_runner.config_resolver import ConfigResolver
        from eval_runner.reference.local_run_store import LocalFileRunStore

        self.run_store = run_store or LocalFileRunStore()
        self.config_resolver = config_resolver or ConfigResolver
        self.resolved_config = self.config_resolver.resolve()
        self.artifact_store = artifact_store
        self.checkpoint_store = checkpoint_store
        self.policy_evaluator = policy_evaluator
        self.signing_backend = signing_backend
        self.execution_backend = execution_backend

        # Wire dependency graph into execution_backend if supported
        if self.execution_backend and hasattr(self.execution_backend, "set_dependency_graph"):
            self.execution_backend.set_dependency_graph(
                runner=self,
                artifact_store=self.artifact_store,
                checkpoint_store=self.checkpoint_store,
                policy_evaluator=self.policy_evaluator,
                signing_backend=self.signing_backend,
                config_resolver=self.config_resolver,
                run_store=self.run_store,
            )

    def set_dependency_graph(
        self,
        artifact_store: Any | None = None,
        checkpoint_store: Any | None = None,
        policy_evaluator: Any | None = None,
        signing_backend: Any | None = None,
        config_resolver: Any | None = None,
        run_store: Any | None = None,
        resolved_config: Any | None = None,
    ) -> None:
        """Dynamically configures or updates the runner's extension dependency graph."""
        if artifact_store is not None:
            self.artifact_store = artifact_store
        if checkpoint_store is not None:
            self.checkpoint_store = checkpoint_store
        if policy_evaluator is not None:
            self.policy_evaluator = policy_evaluator
        if signing_backend is not None:
            self.signing_backend = signing_backend
        if config_resolver is not None:
            self.config_resolver = config_resolver
        if run_store is not None:
            self.run_store = run_store
        if resolved_config is not None:
            from agentv_runtime.config import ResolvedRuntimeConfig

            if isinstance(resolved_config, dict):
                self.resolved_config = ResolvedRuntimeConfig(**resolved_config)
            elif isinstance(resolved_config, ResolvedRuntimeConfig):
                self.resolved_config = resolved_config

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
    ) -> EvaluationResult:
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

        # [AgentV v2.0.0] Explicit execution truth mode
        execution_mode = (
            scenario.get("execution_mode")
            or (metadata or {}).get("execution_mode")
            or scenario.get("metadata", {}).get("execution_mode")
            or "simulated"
        )
        repro_contract = build_reproducibility_contract(
            scenario,
            resolved_config=self.resolved_config,
            seed=seed,
            attempts=attempts,
            execution_mode=str(execution_mode),
            adapter_metadata=dict(ctx.metadata),
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
                    "execution_mode": str(execution_mode),
                    "reproducibility_fingerprint": fingerprint(repro_contract),
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
                    resolved_config=self.resolved_config,
                    artifact_store=self.artifact_store,
                    checkpoint_store=self.checkpoint_store,
                    policy_evaluator=self.policy_evaluator,
                    signing_backend=self.signing_backend,
                )
                attempt_results = await session.execute_tasks(k)

                # [Forensic Sync] propagate resolved routing (e.g. Port 8000)
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
            attempt_statistics: dict[str, Any] = {}
            try:
                # Cross-attempt aggregation
                if attempts > 1:
                    plugins.manager.trigger("on_metrics_calculated", ctx, all_attempt_results)

                # [AgentV v2.0.0] Standardized statistics over ACTUALLY EXECUTED
                # attempts (P0 #8). pass_at_k is the unbiased estimator; the raw
                # proportion, conjunctive/disjunctive semantics and confidence
                # are reported separately.
                stats = compute_attempt_statistics(
                    all_attempt_results, self._is_attempt_successful, requested_k=attempts
                )
                attempt_statistics = stats
                pass_at_k = stats["pass_at_k"]
            except Exception as e:
                import traceback

                tb = traceback.format_exc()
                print(f"      [Runner Error] Failed to generate reports or calculate pass@k: {e}")
                print(tb)
                events.emit(
                    events.CoreEvents.ERROR,
                    {"message": f"Runner Post-Process Error: {e}", "traceback": tb},
                )

            successful_attempts_count = sum(
                1 for res in all_attempt_results if self._is_attempt_successful(res)
            )

            events.emit(
                events.CoreEvents.RUN_END,
                {
                    "pass_at_k": pass_at_k,
                    "attempt_success_rate": attempt_statistics.get("attempt_success_rate", 0.0),
                    "all_pass": attempt_statistics.get("all_pass", False),
                    "any_pass": attempt_statistics.get("any_pass", False),
                    "successful_attempts": successful_attempts_count,
                    "total_attempts": attempts,
                    "executed_attempts": len(all_attempt_results),
                    "metadata": dict(ctx.metadata),
                },
                span_context=ctx.span_context,
            )

            events.emit(
                events.CoreEvents.STRATEGY_END,
                {"strategy": "pass_at_k", "status": "success" if pass_at_k > 0 else "failure"},
                span_context=ctx.span_context,
            )

            cfg_hash = getattr(self.resolved_config, "config_hash", "")

            # Save run manifest to RunStore
            if self.run_store:
                try:
                    manifest_data = {
                        "run_id": effective_run_id,
                        "scenario_id": scenario.get("id"),
                        "attempts": attempts,
                        "pass_at_k": pass_at_k,
                        "attempt_statistics": attempt_statistics,
                        "execution_mode": str(execution_mode),
                        "reproducibility": repro_contract,
                        "results": all_attempt_results,
                        "config_hash": cfg_hash,
                    }
                    self.run_store.save_run_manifest(effective_run_id, manifest_data)
                except Exception as e:
                    logger.debug(f"Failed to save manifest to RunStore: {e}")

            result_metadata = dict(ctx.metadata)
            result_metadata["execution_mode"] = str(execution_mode)
            result_metadata["reproducibility"] = repro_contract
            result_metadata["reproducibility_fingerprint"] = fingerprint(repro_contract)

            return EvaluationResult(
                run_id=effective_run_id,
                scenario_id=str(scenario.get("id", "unknown")),
                pass_at_k=pass_at_k,
                successful_attempts=successful_attempts_count,
                total_attempts=attempts,
                attempts_results=all_attempt_results,
                metadata=result_metadata,
                config_hash=cfg_hash,
                statistics=attempt_statistics,
            )
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
        """
        Standard pass@k estimator over ACTUALLY EXECUTED attempts.
        Prefer `compute_attempt_statistics` for the full semantics contract.
        """
        from .statistics import pass_at_k_estimator

        n = len(all_results)
        successful = sum(1 for res in all_results if self._is_attempt_successful(res))
        return pass_at_k_estimator(n, successful, k)


def run_scenario(
    scenario: dict,
    attempts: int = 1,
    run_id: str | None = None,
    seed: int | None = None,
    metadata: dict | None = None,
    max_turns: int | None = None,
    cancellation_event: Any | None = None,
    resumption_checkpoint: dict | None = None,
    runner: BaseRunner | None = None,
    run_store: Any | None = None,
    config_resolver: Any | None = None,
    artifact_store: Any | None = None,
    checkpoint_store: Any | None = None,
    policy_evaluator: Any | None = None,
    signing_backend: Any | None = None,
    execution_backend: Any | None = None,
) -> EvaluationResult:
    """
    Synchronous entry point that orchestrates evaluation via DefaultRunner.
    Used by InProcessExecutionBackend and CLI triggers. Accepts injected dependency graph.
    """
    if runner is None:
        runner = DefaultRunner(
            run_store=run_store,
            config_resolver=config_resolver,
            artifact_store=artifact_store,
            checkpoint_store=checkpoint_store,
            policy_evaluator=policy_evaluator,
            signing_backend=signing_backend,
            execution_backend=execution_backend,
        )
    elif hasattr(runner, "set_dependency_graph"):
        runner.set_dependency_graph(
            run_store=run_store,
            config_resolver=config_resolver,
            artifact_store=artifact_store,
            checkpoint_store=checkpoint_store,
            policy_evaluator=policy_evaluator,
            signing_backend=signing_backend,
        )

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
