from __future__ import annotations

"""
runner.py

Orchestration logic for evaluation tasks.
Supports multi-attempt (pass@k) loops and plugin interception.
Returns first-class EvaluationResult contracts.
"""

import asyncio  # noqa: E402
import logging  # noqa: E402
import uuid  # noqa: E402
from abc import ABC, abstractmethod  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from agentv_runtime.results import EvaluationResult  # noqa: E402

from . import config, events, plugins  # noqa: E402
from .context import EvaluationContext  # noqa: E402
from .execution_ir import WorkflowStatus  # noqa: E402
from .reproducibility import (  # noqa: E402
    build_reproducibility_contract,
    fingerprint,
    metric_registry_fingerprint,
)
from .statistics import compute_attempt_statistics  # noqa: E402

logger = logging.getLogger(__name__)


def new_run_id(scenario_id: str) -> str:
    """
    [P0-12] Globally-unique, time-ordered run ID: UUIDv7 suffix (UUID4
    fallback on pre-3.14 interpreters). The legacy integer-second truncation
    allowed concurrent same-scenario collisions that contaminated evidence
    vaults.
    """
    _u7 = getattr(uuid, "uuid7", None)
    unique_suffix = _u7().hex if callable(_u7) else uuid.uuid4().hex
    return f"run-{scenario_id}-{unique_suffix}"


def compile_required_oracle_ids(scenario: dict[str, Any], resolved_policy: Any = None) -> list[str]:
    """
    Compile required_oracle_ids BEFORE execution from the immutable
    scenario/evaluation contract and resolved evaluator policy.
    Guarantees that requirements are never derived from observed outputs.
    """
    req_oracles: list[str] = []

    # 1. Explicit declaration in scenario or metadata
    explicit = (
        scenario.get("required_oracles")
        or scenario.get("required_oracle_ids")
        or (scenario.get("metadata") or {}).get("required_oracles")
        or (scenario.get("metadata") or {}).get("required_oracle_ids")
    )
    if isinstance(explicit, (list, set, tuple)):
        for item in explicit:
            s_item = str(item).strip()
            if s_item and s_item not in req_oracles:
                req_oracles.append(s_item)

    # 2. Compile from Workflow nodes / CompiledEvaluationPlan
    try:
        from eval_runner.execution_ir import compile_evaluation_plan

        plan = compile_evaluation_plan(scenario)
        for oid, compiled in plan.oracles.items():
            if getattr(compiled, "required", True):
                s_oid = str(oid).strip()
                if s_oid and s_oid not in req_oracles:
                    req_oracles.append(s_oid)
    except Exception as e:
        logger.debug("Plan compilation in required oracle discovery skipped: %s", e)

    # 3. Top-level scenario success_criteria or expected_outcome
    for key in ("success_criteria", "expected_outcome", "oracles"):
        val_list = scenario.get(key)
        if isinstance(val_list, list):
            for item in val_list:
                if isinstance(item, dict):
                    oid = item.get("oracle_id") or item.get("id") or item.get("name")
                    is_req = item.get("required", True)
                    if oid and is_req and str(oid) not in req_oracles:
                        req_oracles.append(str(oid))
                elif isinstance(item, str) and item not in req_oracles:
                    req_oracles.append(item)

    return sorted(req_oracles)


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

        scenario_identifier = (
            scenario.get("id")
            or (scenario.get("metadata") or {}).get("id")
            or (scenario.get("metadata") or {}).get("name")
            or "unknown"
        )
        # Centralized Identifier Resolution
        effective_run_id = run_id or new_run_id(str(scenario_identifier))

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
                name=f"agentv.run.{scenario_identifier}",
                context=parent_context,
            )
            span.set_attribute("agentv.run_id", effective_run_id)
            span.set_attribute("agentv.scenario_id", str(scenario_identifier))
            span.set_attribute("agentv.attempts", attempts)

            otel_ctx = trace.set_span_in_context(span, parent_context)
        except Exception as e:
            import sys

            sys.stderr.write(f"   [Telemetry] Warning: Failed to initialize OTel span: {e}\n")

        ctx = EvaluationContext(
            identifier=str(scenario_identifier),
            scenario_data=copy.deepcopy(scenario),
            run_id=effective_run_id,
            seed=seed,
            metadata=dict(copy.deepcopy(metadata)) if metadata else {},
            span_context=scenario.get("span_context"),
            otel_context=otel_ctx,
        )

        # [AgentV v2.0.0] Explicit execution truth mode
        declared_mode = (
            scenario.get("execution_mode")
            or (metadata or {}).get("execution_mode")
            or scenario.get("metadata", {}).get("execution_mode")
        )
        execution_mode = str(declared_mode) if declared_mode else "simulated"
        execution_mode_declared = bool(declared_mode)
        if isinstance(ctx.metadata, dict):
            ctx.metadata["execution_mode"] = execution_mode
            ctx.metadata["execution_mode_declared"] = execution_mode_declared

        repro_contract = build_reproducibility_contract(
            scenario,
            resolved_config=self.resolved_config,
            seed=seed,
            attempts=attempts,
            execution_mode=str(execution_mode),
            adapter_metadata=dict(ctx.metadata),
            evaluator_fingerprint=metric_registry_fingerprint(),
            plugin_provenance=dict(getattr(plugins.manager, "provenance_map", {}) or {}),
        )

        # Compile required oracles BEFORE execution from immutable scenario contract (P0-1 Fix)
        req_oracles = compile_required_oracle_ids(scenario, resolved_policy=self.policy_evaluator)

        # Build authoritative physical ExecutionManifest upfront from resolved execution plan
        import json
        import os
        import platform
        import sys

        from agentv_runtime.manifest import (
            ExecutionManifest,
            compute_preflight_fingerprint,
            compute_scenario_hash,
        )

        scen_hash = compute_scenario_hash(scenario)
        scen_ver = str(
            scenario.get("version") or (scenario.get("metadata") or {}).get("version") or "1.0.0"
        )
        adapter_meta = dict(ctx.metadata)
        scenario_meta = scenario.get("metadata", {}) if isinstance(scenario, dict) else {}
        endpoint = (
            adapter_meta.get("agent")
            or adapter_meta.get("endpoint")
            or (scenario.get("adapter") or {}).get("endpoint")
            or scenario.get("endpoint")
            or ""
        )
        protocol = (
            adapter_meta.get("protocol")
            or (scenario.get("adapter") or {}).get("protocol")
            or scenario.get("protocol")
            or ""
        )
        provider_model = (
            adapter_meta.get("model")
            or scenario_meta.get("model")
            or (scenario.get("agent") or {}).get("model")
            or ""
        )
        agent_id = (
            adapter_meta.get("agent_id")
            or (scenario.get("agent") or {}).get("id")
            or scenario.get("agent_id")
            or "default_agent"
        )
        agent_ver = (
            adapter_meta.get("agent_version")
            or (scenario.get("agent") or {}).get("version")
            or "1.0.0"
        )

        resolved_agent_config = {
            "agent_id": str(agent_id),
            "version": str(agent_ver),
            "endpoint": str(endpoint),
            "protocol": str(protocol),
            "model": str(provider_model),
            "adapter_version": str(adapter_meta.get("adapter_version") or "standard"),
            **dict(scenario.get("agent_config") or {}),
            **dict(adapter_meta.get("agent_config") or {}),
        }

        canonical_preflight_fp = adapter_meta.get(
            "preflight_fingerprint"
        ) or compute_preflight_fingerprint(
            scenario_id=str(scenario_identifier),
            scen_hash=scen_hash,
            endpoint=str(endpoint),
            protocol=str(protocol),
            max_turns=max_turns or 10,
        )

        env_dict = {
            "platform": sys.platform,
            "python_version": platform.python_version(),
            "hostname": platform.node() or "localhost",
            "pid": os.getpid(),
        }

        resolved_runtime_config = {
            "execution_mode": str(execution_mode),
            "attempts": attempts,
            "seed": seed,
            "max_turns": max_turns,
            "evaluator_config_hash": getattr(self.resolved_config, "config_hash", "") or "none",
            "reproducibility_fingerprint": fingerprint(repro_contract),
            **dict(adapter_meta.get("runtime_config") or {}),
        }

        manifest_metadata = {
            **dict(ctx.metadata),
            "preflight_fingerprint": canonical_preflight_fp,
            "plugin_provenance": dict(getattr(plugins.manager, "provenance_map", {}) or {}),
            "evaluator_fingerprint": metric_registry_fingerprint(),
            "required_oracle_ids": req_oracles,
        }

        # Defense-in-depth: Ensure metadata values (including nested CLI args dicts)
        # do not retain dispatch callbacks or opaque runtime callables
        cleaned_manifest_metadata: dict[str, Any] = {}
        for mk, mv in manifest_metadata.items():
            if isinstance(mv, dict):
                cleaned_manifest_metadata[mk] = {k: v for k, v in mv.items() if not callable(v)}
            elif not callable(mv):
                cleaned_manifest_metadata[mk] = mv

        exec_manifest = ExecutionManifest(
            manifest_id=f"man_{effective_run_id}",
            scenario_id=str(scenario_identifier),
            scenario_version=scen_ver,
            scenario_hash=scen_hash,
            agent_config=resolved_agent_config,
            runtime_config=resolved_runtime_config,
            environment=env_dict,
            metadata=cleaned_manifest_metadata,
        )
        exec_manifest_hash = exec_manifest.compute_manifest_hash()

        run_vault_dir = config.RUN_LOG_DIR / effective_run_id
        run_vault_dir.mkdir(parents=True, exist_ok=True)
        manifest_file = run_vault_dir / "execution_manifest.json"
        try:
            with open(manifest_file, "w", encoding="utf-8") as mf:
                json.dump(exec_manifest.to_dict(), mf, indent=2)
        except Exception as e:
            logger.debug("Failed saving execution_manifest.json to run vault: %s", e)

        # For fresh evaluation runs (non-resumed), ensure vault lifecycle and trace begin clean
        if resumption_checkpoint is None:
            final_trace_path = run_vault_dir / "run.jsonl"
            if final_trace_path.exists():
                try:
                    final_trace_path.unlink()
                except OSError:
                    try:
                        with open(final_trace_path, "w", encoding="utf-8") as tf:
                            tf.truncate(0)
                    except OSError as trunc_err:
                        logger.debug("Failed truncating stale trace file in runner: %s", trunc_err)
            lf_file = run_vault_dir / ".run_lifecycle"
            if lf_file.exists():
                try:
                    lf_file.unlink()
                except OSError as unl_err:
                    logger.debug("Failed unlinking stale lifecycle marker in runner: %s", unl_err)
            sealed_file = run_vault_dir / ".sealed"
            if sealed_file.exists():
                try:
                    sealed_file.unlink()
                except OSError as unl_err:
                    logger.debug("Failed unlinking stale sealed marker in runner: %s", unl_err)

        try:
            events.emit(
                events.CoreEvents.RUN_START,
                {
                    "run_id": effective_run_id,
                    "scenario": ctx.identifier,
                    "scenario_id": str(scenario_identifier),
                    "k_attempts": attempts,
                    "workflow": ctx.scenario_data.get("workflow"),
                    "scenario_data": dict(ctx.scenario_data) if ctx.scenario_data else {},
                    "execution_mode": str(execution_mode),
                    # Whether the operator explicitly declared the mode;
                    # absent declaration → provisional certificates.
                    "execution_mode_declared": bool(
                        scenario.get("execution_mode")
                        or (metadata or {}).get("execution_mode")
                        or scenario.get("metadata", {}).get("execution_mode")
                    ),
                    "reproducibility_fingerprint": fingerprint(repro_contract),
                },
                span_context=ctx.span_context,
            )

            plugins.manager.trigger("before_evaluation", ctx)

            all_attempt_results = []

            # 🚀 STRATEGY: Mission-Level Telemetry
            events.emit(
                events.CoreEvents.STRATEGY_START,
                {"run_id": effective_run_id, "strategy": "pass_at_k", "k": attempts},
                span_context=ctx.span_context,
            )

            events.emit(
                events.CoreEvents.PHASE_START,
                {"run_id": effective_run_id, "phase": "pass_at_k_execution", "k": attempts},
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
                {"run_id": effective_run_id, "phase": "pass_at_k_execution"},
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
                    {
                        "run_id": effective_run_id,
                        "message": f"Runner Post-Process Error: {e}",
                        "traceback": tb,
                    },
                )

            successful_attempts_count = sum(
                1 for res in all_attempt_results if self._is_attempt_successful(res)
            )

            # Collect observed assertions for evidence trace without mutating required_oracle_ids
            collected_assertions: list[dict[str, Any]] = []
            for attempt in all_attempt_results:
                task_rows = (
                    attempt
                    if isinstance(attempt, list)
                    else [attempt]
                    if isinstance(attempt, dict)
                    else []
                )
                for row in task_rows:
                    if not isinstance(row, dict):
                        continue
                    for or_res in row.get("oracle_results") or []:
                        if isinstance(or_res, dict):
                            collected_assertions.append(or_res)
                        elif isinstance(or_res, str):
                            collected_assertions.append({"oracle_id": or_res, "passed": True})
                    for m in row.get("metrics") or []:
                        if isinstance(m, dict):
                            if (
                                m.get("metric") == "consistency_score"
                                or m.get("oracle_id") == "consistency_score"
                            ):
                                continue
                            collected_assertions.append(m)
                        elif isinstance(m, str):
                            if m == "consistency_score":
                                continue
                            collected_assertions.append({"metric_id": m, "passed": True})

            # Authoritative canonical evidence graph root (Defect 2)
            from agentv_runtime.evidence_graph import build_evidence_graph_from_events
            from agentv_runtime.finalization import EvaluatorFinalizationRecord

            final_trace_path = run_vault_dir / "run.jsonl"
            trace_events: list[dict[str, Any]] = []
            if final_trace_path.exists():
                try:
                    with open(final_trace_path, encoding="utf-8") as tf:
                        for line in tf:
                            s = line.strip()
                            if s:
                                trace_events.append(json.loads(s))
                except Exception as read_err:
                    logger.debug("Failed reading trace for evidence graph root: %s", read_err)

            if not trace_events:
                for a in collected_assertions:
                    trace_events.append({"event": "assertion_evaluated", **a})

            ev_graph = build_evidence_graph_from_events(
                trace_events, required_oracle_ids=req_oracles
            )
            evidence_root = ev_graph["evidence_root_hash"]

            # Authenticated EvaluatorFinalizationRecord bound to upfront manifest hash
            evaluator_id = "eval_runner.runner.EvaluationKernel"
            finalization_record = EvaluatorFinalizationRecord(
                finalization_id=f"fin_{effective_run_id}",
                run_id=effective_run_id,
                execution_manifest_hash=exec_manifest_hash,
                scenario_id=str(scenario_identifier),
                scenario_version=scen_ver,
                scenario_hash=scen_hash,
                evaluator_identity=evaluator_id,
                evaluator_config_hash=getattr(self.resolved_config, "config_hash", "") or "none",
                required_oracle_ids=req_oracles,
                evidence_root_hash=evidence_root,
                outcome="pass" if pass_at_k > 0 else "fail",
                score=float(pass_at_k),
                terminal_seq=len(all_attempt_results),
            )
            sign_err_msg = None
            try:
                from eval_runner.identity import IdentityService

                eval_priv = IdentityService.get_private_key(evaluator_id, auto_provision=True)
                if not eval_priv:
                    sign_err_msg = (
                        f"Evaluator private key for '{evaluator_id}' not found "
                        "(auto-provisioning disabled in production)"
                    )
                    logger.error(sign_err_msg)
                else:
                    finalization_record = finalization_record.sign(eval_priv)
                    sig = getattr(finalization_record, "evaluator_signature", None) or getattr(
                        finalization_record, "signature", None
                    )
                    if not sig:
                        sign_err_msg = "Signature missing after signing attempt"
            except Exception as sign_err:
                sign_err_msg = str(sign_err)
                logger.error("Evaluator signing error in runner: %s", sign_err)

            if sign_err_msg:
                # Terminate authoritative evaluation finalization path immediately (P1 Fix)
                events.emit(
                    events.CoreEvents.CERTIFICATION_FAILED,
                    {
                        "run_id": effective_run_id,
                        "status": "certification_failed",
                        "error": (
                            f"Authoritative evaluator finalization signing failed: {sign_err_msg}"
                        ),
                    },
                    span_context=ctx.span_context,
                )
                events.emit(
                    events.CoreEvents.RUN_END,
                    {
                        "run_id": effective_run_id,
                        "status": "certification_failed",
                        "passed": False,
                        "score": 0.0,
                        "pass_at_k": 0.0,
                        "error": (
                            f"Authoritative evaluator finalization signing failed: {sign_err_msg}"
                        ),
                        "finalization": None,
                        "metadata": dict(ctx.metadata),
                    },
                    span_context=ctx.span_context,
                )
                return EvaluationResult(
                    run_id=effective_run_id,
                    scenario_id=str(scenario.get("id", "unknown")),
                    pass_at_k=0.0,
                    successful_attempts=0,
                    total_attempts=attempts,
                    attempts_results=all_attempt_results,
                    metadata={
                        "error": f"Evaluator signing failed: {sign_err_msg}",
                        "uncertifiable": True,
                    },
                )

            fin_dict = finalization_record.to_dict()

            events.emit(
                events.CoreEvents.STRATEGY_END,
                {
                    "run_id": effective_run_id,
                    "strategy": "pass_at_k",
                    "status": "success" if pass_at_k > 0 else "failure",
                },
                span_context=ctx.span_context,
            )

            events.emit(
                events.CoreEvents.RUN_END,
                {
                    "run_id": effective_run_id,
                    "status": "success" if pass_at_k > 0 else "failure",
                    "passed": bool(pass_at_k > 0),
                    "score": float(pass_at_k),
                    "pass_at_k": pass_at_k,
                    "attempt_success_rate": attempt_statistics.get("attempt_success_rate", 0.0),
                    "all_pass": attempt_statistics.get("all_pass", False),
                    "any_pass": attempt_statistics.get("any_pass", False),
                    "successful_attempts": successful_attempts_count,
                    "total_attempts": attempts,
                    "executed_attempts": len(all_attempt_results),
                    "metadata": dict(ctx.metadata),
                    "finalization": fin_dict,
                    "assertions": collected_assertions,
                },
                span_context=ctx.span_context,
            )

            cfg_hash = getattr(self.resolved_config, "config_hash", "")

            # Save run manifest to RunStore
            if self.run_store:
                try:
                    manifest_data = {
                        "run_id": effective_run_id,
                        "scenario_id": str(scenario_identifier),
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
        """
        [A5] Verdict-authoritative attempt success for pass@k.

        An attempt succeeds if and only if ALL of the following hold:
          1. The authoritative kernel verdict is workflow COMPLETED.
          2. Every evaluation is valid: no evaluation_valid=False row and no
             EVALUATION_INVALID triage tag anywhere in the attempt.
          3. No metric row carries an EVALUATION_INVALID status, and no
             non-informational oracle assertion failed.
          4. No sandbox policy decision was denied (A4 gating).
        """
        if not attempt_results:
            return False

        # 1. Authoritative workflow verdict must exist and be COMPLETED.
        verdict_rows = [
            r
            for r in attempt_results
            if isinstance(r, dict) and isinstance(r.get("workflow_verdict"), dict)
        ]
        if not verdict_rows:
            return False
        for vr in verdict_rows:
            status = str(vr["workflow_verdict"].get("status", "")).lower()
            if status != WorkflowStatus.COMPLETED.value.lower():
                return False

        for res in attempt_results:
            if not isinstance(res, dict):
                continue
            # 2. Evaluation validity is non-negotiable.
            if res.get("triage_tag") == "EVALUATION_INVALID":
                return False
            if res.get("evaluation_valid") is False:
                return False

            # [P2.7] First-class NodeVerdict gating across all typed evidence dimensions
            if "node_verdict" in res and isinstance(res["node_verdict"], dict):
                nv = res["node_verdict"]
                if nv.get("verification") in ("fail", "invalid"):
                    return False
                if nv.get("policy") == "denied":
                    return False
                if nv.get("parity") == "fail":
                    return False
                if nv.get("overall") not in ("success", "not_applicable"):
                    return False

            # Typed OracleResult requiredness lattice evaluation
            if "oracle_results" in res and isinstance(res["oracle_results"], list):
                for or_res in res["oracle_results"]:
                    req_level = str(or_res.get("requiredness", "REQUIRED")).upper()
                    outcome = str(or_res.get("outcome", "NOT_EVALUATED")).upper()
                    if req_level == "REQUIRED":
                        if outcome in ("FAIL", "INVALID", "NOT_EVALUATED"):
                            return False
                    # OPTIONAL and INFORMATIONAL oracles never gate attempt success

            # 3. Oracle rows: invalid or failed assertions veto the attempt.
            for m in res.get("metrics") or []:
                if not isinstance(m, dict):
                    continue
                is_opt_or_info = m.get("severity") == "informational" or str(
                    m.get("requiredness", "")
                ).upper() in ("OPTIONAL", "INFORMATIONAL")
                if is_opt_or_info:
                    continue
                if m.get("success") is False or m.get("outcome") == "FAIL":
                    return False

            for h in res.get("state_hygiene") or []:
                if h.get("invalid") or h.get("status") == "EVALUATION_INVALID":
                    return False
                if str(h.get("requiredness", "")).upper() in ("OPTIONAL", "INFORMATIONAL"):
                    continue
                if h.get("success") is False or h.get("outcome") == "FAIL":
                    return False

            for p in res.get("state_parity") or []:
                if p.get("invalid") or p.get("status") == "EVALUATION_INVALID":
                    return False
                if str(p.get("requiredness", "")).upper() in ("OPTIONAL", "INFORMATIONAL"):
                    continue
                if p.get("success") is False or p.get("outcome") == "FAIL":
                    return False

            # 4. Policy denials are gating (first-class policy assertions).
            for pc in res.get("policy_checks") or []:
                if pc.get("decision") == "denied":
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
