from __future__ import annotations

"""
runner.py

Orchestration logic for evaluation tasks.
Supports multi-attempt (pass@k) loops and plugin interception.
Returns first-class EvaluationResult contracts.
"""

import asyncio  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import uuid  # noqa: E402
from abc import ABC, abstractmethod  # noqa: E402
from collections.abc import Mapping  # noqa: E402
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
from .run_lifecycle import RunSuspendedForApproval  # noqa: E402
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

    # 1b. Required policy controls are ordinary required oracles.  A policy
    # declaration is certifiable only when it names the exact assertion that
    # will produce its evidence; descriptive labels are not controls.
    policies = (scenario.get("metadata") or {}).get("policies") or {}
    if isinstance(policies, dict):
        for policy_id, policy_spec in policies.items():
            if not isinstance(policy_spec, dict) or policy_spec.get("required") is not True:
                continue
            oracle_id = policy_spec.get("oracle_id")
            if not isinstance(oracle_id, str) or not oracle_id.strip():
                raise ValueError(
                    f"RequiredPolicyMissingOracleId: policy '{policy_id}' must declare oracle_id"
                )
            if oracle_id not in req_oracles:
                req_oracles.append(oracle_id)

    # 2. Compile from Workflow nodes / CompiledEvaluationPlan (fail closed on invalid plan)
    from eval_runner.execution_ir import compile_evaluation_plan

    plan = compile_evaluation_plan(scenario)
    for oid, compiled in plan.oracles.items():
        if getattr(compiled, "required", True):
            s_oid = str(oid).strip()
            if s_oid and s_oid not in req_oracles:
                req_oracles.append(s_oid)

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

    @staticmethod
    def _resolve_source_commit_attribution(adapter_meta: dict[str, Any]) -> tuple[str, str, bool]:
        commit = adapter_meta.get("source_commit") or os.environ.get("AGENT_SOURCE_COMMIT")
        if commit:
            return str(commit), "declared", False
        github_sha = os.environ.get("GITHUB_SHA")
        if github_sha and adapter_meta.get("source_repository"):
            return str(github_sha), "declared", False
        return "unknown", "unknown", False

    @staticmethod
    def _resolve_source_commit(adapter_meta: dict[str, Any]) -> str:
        val, _, _ = DefaultRunner._resolve_source_commit_attribution(adapter_meta)
        return val

    @staticmethod
    def _resolve_model_provider_attribution(
        m: str, adapter_meta: dict[str, Any]
    ) -> tuple[str, str, bool]:
        if adapter_meta.get("provider"):
            return str(adapter_meta["provider"]), "declared", True
        if adapter_meta.get("model_provider"):
            return str(adapter_meta["model_provider"]), "declared", True
        m_lower = (m or "").lower()
        if any(k in m_lower for k in ("gpt", "openai", "o1", "o3", "davinci")):
            return "openai", "derived", False
        if any(k in m_lower for k in ("claude", "anthropic")):
            return "anthropic", "derived", False
        if any(k in m_lower for k in ("gemini", "google", "palm")):
            return "google", "derived", False
        if any(k in m_lower for k in ("llama", "mistral", "qwen", "deepseek", "local", "ollama")):
            return "local", "derived", False
        if adapter_meta.get("framework"):
            return str(adapter_meta["framework"]), "declared", False
        return "unknown", "unknown", False

    @staticmethod
    def _resolve_model_provider(m: str, adapter_meta: dict[str, Any]) -> str:
        val, _, _ = DefaultRunner._resolve_model_provider_attribution(m, adapter_meta)
        return val

    @staticmethod
    def _resolve_tool_versions_attribution(
        scenario: dict[str, Any], adapter_meta: dict[str, Any]
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        t_vers: dict[str, str] = {}
        t_prov: dict[str, dict[str, Any]] = {}
        scen_tools = scenario.get("tools") or []
        if isinstance(scen_tools, list):
            for i, t in enumerate(scen_tools):
                if isinstance(t, dict):
                    t_name = str(t.get("name") or f"tool_{i}")
                    if t.get("version"):
                        ver_str = str(t["version"])
                        t_vers[t_name] = ver_str
                        t_prov[t_name] = {"value": ver_str, "source": "declared", "verified": False}
                    else:
                        t_vers[t_name] = "unknown"
                        t_prov[t_name] = {
                            "value": "unknown",
                            "source": "unknown",
                            "verified": False,
                        }
                elif isinstance(t, str):
                    t_vers[t] = "unknown"
                    t_prov[t] = {"value": "unknown", "source": "unknown", "verified": False}
        if isinstance(adapter_meta.get("tools"), dict):
            for k, v in adapter_meta["tools"].items():
                v_str = str(v)
                t_vers[k] = v_str
                t_prov[k] = {"value": v_str, "source": "declared", "verified": False}
        return t_vers, t_prov

    @staticmethod
    def _resolve_tool_versions(
        scenario: dict[str, Any], adapter_meta: dict[str, Any]
    ) -> dict[str, str]:
        t_vers, _ = DefaultRunner._resolve_tool_versions_attribution(scenario, adapter_meta)
        return t_vers

    def __init__(
        self,
        run_store: Any | None = None,
        config_resolver: Any | None = None,
        artifact_store: Any | None = None,
        checkpoint_store: Any | None = None,
        policy_evaluator: Any | None = None,
        signing_backend: Any | None = None,
        execution_backend: Any | None = None,
        revision_service: Any | None = None,
    ):
        """Sanity check for required directories and initialize storage / config wiring."""
        Path("scenarios").mkdir(exist_ok=True)
        Path("industries").mkdir(exist_ok=True)
        # Runtime state is project-owned, never process-CWD-owned. Console
        # launches may originate from the UI directory.
        (config.PROJECT_ROOT / ".aes").mkdir(exist_ok=True)

        from agentv_runtime.discovery import resolve_extension
        from eval_runner.config_resolver import ConfigResolver
        from eval_runner.reference.local_artifact import LocalFileArtifactStore
        from eval_runner.reference.local_run_store import LocalFileRunStore

        self.run_store = (
            run_store
            if run_store is not None
            else resolve_extension("run_stores", default_factory=LocalFileRunStore)
        )
        self.config_resolver = config_resolver or ConfigResolver
        self.resolved_config = self.config_resolver.resolve()
        self.artifact_store = resolve_extension(
            "artifact_stores",
            explicit=artifact_store,
            default_factory=LocalFileArtifactStore,
        )
        self.checkpoint_store = checkpoint_store
        self.policy_evaluator = policy_evaluator
        self.signing_backend = signing_backend
        self.execution_backend = execution_backend
        self.revision_service = revision_service

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
        resumption_token: str | None = None,
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
        if isinstance(ctx.metadata, Mapping):
            from .context import _freeze_dict

            new_meta = dict(ctx.metadata) if isinstance(ctx.metadata, Mapping) else {}
            new_meta["execution_mode"] = execution_mode
            new_meta["execution_mode_declared"] = execution_mode_declared
            object.__setattr__(ctx, "metadata", _freeze_dict(new_meta))

        repro_contract = build_reproducibility_contract(
            scenario,
            resolved_config=self.resolved_config,
            seed=seed,
            attempts=attempts,
            execution_mode=str(execution_mode),
            adapter_metadata=dict(ctx.metadata) if isinstance(ctx.metadata, Mapping) else {},
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
        # Freeze the exact document whose identity is bound into the execution
        # manifest *before* emitting RUN_START.  Event subscribers/plugins may
        # enrich mutable scenario objects; persisting afterwards from that
        # object would split the vault snapshot from the signed run identity.
        scenario_snapshot = json.loads(json.dumps(scenario))
        if compute_scenario_hash(scenario_snapshot) != scen_hash:
            raise RuntimeError(
                "ScenarioSnapshotHashMismatch: unable to freeze the exact scenario "
                "document bound to this execution."
            )
        scen_ver = str(
            scenario.get("version") or (scenario.get("metadata") or {}).get("version") or "1.0.0"
        )
        adapter_meta = dict(ctx.metadata) if isinstance(ctx.metadata, Mapping) else {}
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
        raw_agent_ver = adapter_meta.get("agent_version") or (scenario.get("agent") or {}).get(
            "version"
        )
        agent_ver = str(raw_agent_ver) if raw_agent_ver else "unknown"
        agent_ver_src = "declared" if raw_agent_ver else "unknown"

        raw_fw = adapter_meta.get("framework") or scenario.get("framework")
        framework_name = str(raw_fw) if raw_fw else "unknown"
        framework_src = "declared" if raw_fw else "unknown"

        raw_fw_ver = adapter_meta.get("framework_version")
        framework_version = str(raw_fw_ver) if raw_fw_ver else "unknown"
        framework_ver_src = "declared" if raw_fw_ver else "unknown"

        raw_adapt_ver = adapter_meta.get("adapter_version")
        adapter_version = str(raw_adapt_ver) if raw_adapt_ver else "unknown"
        adapter_ver_src = "declared" if raw_adapt_ver else "unknown"

        # Rich Provenance Extraction
        import hashlib

        from agentv_runtime.canonical import canonical_json_encode
        from eval_runner import __version__ as runtime_pkg_version

        source_commit, source_commit_src, source_commit_ver = (
            self._resolve_source_commit_attribution(adapter_meta)
        )
        model_prov, model_prov_src, model_prov_ver = self._resolve_model_provider_attribution(
            str(provider_model), adapter_meta
        )
        tool_versions, tool_prov = self._resolve_tool_versions_attribution(scenario, adapter_meta)

        prompt_data = (
            scenario.get("prompt")
            or scenario.get("instruction")
            or scenario.get("system_prompt")
            or ""
        )
        prompt_rev = f"sha3_256:{hashlib.sha3_256(canonical_json_encode(prompt_data)).hexdigest()}"
        cfg_obj = scenario.get("config") or scenario.get("agent_config") or {}
        config_rev = f"sha3_256:{hashlib.sha3_256(canonical_json_encode(cfg_obj)).hexdigest()}"
        policy_data = (
            (scenario.get("metadata") or {}).get("policies")
            or scenario.get("policy")
            or scenario.get("rules")
            or scenario.get("assertions")
            or []
        )
        policy_h = (
            str(scenario.get("policy_hash"))
            if scenario.get("policy_hash") is not None
            else f"sha3_256:{hashlib.sha3_256(canonical_json_encode(policy_data)).hexdigest()}"
        )
        oracle_h = f"sha3_256:{hashlib.sha3_256(canonical_json_encode(req_oracles)).hexdigest()}"
        env_raw = (
            f"{sys.platform}:{platform.python_version()}:{platform.node()}:{runtime_pkg_version}"
        )
        env_fp = f"sha3_256:{hashlib.sha3_256(env_raw.encode('utf-8')).hexdigest()}"

        is_certification = bool(
            execution_mode in ("live", "hybrid")
            and execution_mode_declared
            and not (metadata or {}).get("provisional")
            and not scenario.get("provisional")
            and not (metadata or {}).get("debug")
            and not scenario.get("debug")
        )

        if is_certification:
            missing_cert_fields = []
            if not scen_hash or scen_hash == "unknown":
                missing_cert_fields.append("scenario_hash")
            if not policy_h or policy_h == "unknown":
                missing_cert_fields.append("policy_hash")
            eval_cfg_hash = getattr(self.resolved_config, "config_hash", "")
            if not eval_cfg_hash or eval_cfg_hash in ("none", "unknown"):
                missing_cert_fields.append("evaluator_config_hash")
            if scenario.get("tools"):
                unresolved_tools = [k for k, v in tool_versions.items() if v == "unknown"]
                if unresolved_tools:
                    missing_cert_fields.append(f"tool_versions:{unresolved_tools}")

            has_adapter = bool(
                scenario.get("adapter")
                or adapter_meta.get("adapter")
                or protocol in ("openai", "gemini", "claude", "bedrock", "ollama")
                or provider_model
                or (metadata or {}).get("require_model_provenance")
                or scenario.get("require_model_provenance")
            )
            if has_adapter:
                if not provider_model or provider_model == "unknown":
                    missing_cert_fields.append("configured_model_id")
                if not model_prov or model_prov == "unknown":
                    missing_cert_fields.append("model_provider")
                if adapter_version == "unknown":
                    missing_cert_fields.append("adapter_version")

            if missing_cert_fields:
                missing_str = ", ".join(missing_cert_fields)
                fail_err = (
                    "Certification run failed closed: missing authoritative provenance for "
                    f"required identity fields: {missing_str}. "
                    "Unknown fields must not be defaulted."
                )
                logger.error(fail_err)
                events.emit(
                    events.CoreEvents.CERTIFICATION_FAILED,
                    {
                        "run_id": effective_run_id,
                        "status": "certification_failed",
                        "error": fail_err,
                        "missing_provenance": missing_cert_fields,
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
                        "error": fail_err,
                        "finalization": None,
                        "metadata": {**dict(ctx.metadata), "uncertifiable": True},
                    },
                    span_context=ctx.span_context,
                )
                return EvaluationResult(
                    run_id=effective_run_id,
                    scenario_id=str(scenario.get("id", "unknown")),
                    pass_at_k=0.0,
                    successful_attempts=0,
                    total_attempts=attempts,
                    attempts_results=[],
                    metadata={
                        "error": fail_err,
                        "uncertifiable": True,
                        "missing_provenance": missing_cert_fields,
                    },
                )

        provenance_dict = {
            "agent_id": {"value": str(agent_id), "source": "declared", "verified": False},
            "agent_version": {"value": agent_ver, "source": agent_ver_src, "verified": False},
            "source_commit": {
                "value": source_commit,
                "source": source_commit_src,
                "verified": source_commit_ver,
            },
            "model_provider": {
                "value": model_prov,
                "source": model_prov_src,
                "verified": model_prov_ver,
            },
            "model": {
                "value": str(provider_model),
                "source": "declared" if provider_model else "unknown",
                "verified": False,
            },
            "configured_model_id": {
                "value": str(provider_model),
                "source": "declared" if provider_model else "unknown",
                "verified": False,
            },
            "endpoint": {
                "value": str(endpoint),
                "source": "declared" if endpoint else "unknown",
                "verified": False,
            },
            "protocol": {
                "value": str(protocol),
                "source": "declared" if protocol else "unknown",
                "verified": False,
            },
            "framework": {"value": framework_name, "source": framework_src, "verified": False},
            "framework_version": {
                "value": framework_version,
                "source": framework_ver_src,
                "verified": False,
            },
            "adapter_version": {
                "value": adapter_version,
                "source": adapter_ver_src,
                "verified": False,
            },
            "tool_versions": tool_prov,
            "prompt_revision": {"value": prompt_rev, "source": "observed", "verified": True},
            "config_revision": {"value": config_rev, "source": "observed", "verified": True},
            "scenario_hash": {"value": scen_hash, "source": "observed", "verified": True},
            "policy_hash": {"value": policy_h, "source": "observed", "verified": True},
            "oracle_hash": {"value": oracle_h, "source": "observed", "verified": True},
        }

        resolved_agent_config = {
            "agent_id": str(agent_id),
            "version": str(agent_ver),
            "source_commit": source_commit,
            "model_provider": model_prov,
            "model": str(provider_model),
            "configured_model_id": str(provider_model),
            "endpoint": str(endpoint),
            "protocol": str(protocol),
            "framework": framework_name,
            "framework_version": framework_version,
            "adapter_version": adapter_version,
            "tool_versions": tool_versions,
            "prompt_revision": prompt_rev,
            "config_revision": config_rev,
            "provenance": provenance_dict,
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
            "runtime_version": str(runtime_pkg_version),
            "environment_fingerprint": env_fp,
        }

        resolved_runtime_config = {
            "execution_mode": str(execution_mode),
            "attempts": attempts,
            "seed": seed,
            "max_turns": max_turns,
            "runtime_version": str(runtime_pkg_version),
            "evaluator_config_hash": getattr(self.resolved_config, "config_hash", "") or "none",
            "scenario_hash": scen_hash,
            "policy_hash": policy_h,
            "oracle_hash": oracle_h,
            "reproducibility_fingerprint": fingerprint(repro_contract),
            **dict(adapter_meta.get("runtime_config") or {}),
        }

        manifest_metadata = {
            **(dict(ctx.metadata) if isinstance(ctx.metadata, Mapping) else {}),
            "preflight_fingerprint": canonical_preflight_fp,
            "plugin_provenance": dict(getattr(plugins.manager, "provenance_map", {}) or {}),
            "evaluator_fingerprint": metric_registry_fingerprint(),
            "required_oracle_ids": req_oracles,
            "scenario_hash": scen_hash,
            "policy_hash": policy_h,
            "oracle_hash": oracle_h,
            "environment_fingerprint": env_fp,
        }

        # Resolve server-side scope and adopt scoped runtime configuration revision
        observed_revision_record = None
        runtime_context = (
            ctx.metadata.get("runtime_context") if isinstance(ctx.metadata, Mapping) else None
        )
        if not runtime_context:
            from eval_runner.run_index import read_run_index

            idx_rec = read_run_index(effective_run_id)
            if idx_rec and isinstance(idx_rec.get("context"), Mapping):
                runtime_context = idx_rec["context"]

        if isinstance(runtime_context, Mapping) and all(
            bool(runtime_context.get(k))
            for k in ("org_id", "tenant_id", "workspace_id", "active_environment")
        ):
            try:
                from agentv_runtime.config import (
                    ConfigResolver as AgentVConfigResolver,
                    RuntimeWorkerConfigConsumer,
                )
                from eval_runner.services.config_revision import (
                    ConfigurationRevisionService,
                    bind_revision_to_evidence,
                    derive_verified_scope,
                )

                scope = derive_verified_scope(runtime_context)
                revision_service = (
                    getattr(self, "revision_service", None) or ConfigurationRevisionService()
                )
                adapter = revision_service.get_deployment_adapter()

                worker_instance_id = (
                    os.getenv("AGENTV_WORKER_INSTANCE_ID")
                    or getattr(self, "worker_instance_id", None)
                    or f"worker_{platform.node() or 'node'}_{os.getpid()}"
                )

                target_rev = adapter.get_pending_or_active_revision(
                    scope, instance_id=worker_instance_id
                )
                if target_rev is not None:
                    resolver_inst = (
                        self.config_resolver
                        if hasattr(self.config_resolver, "resolve_detailed")
                        else AgentVConfigResolver()
                    )
                    consumer = RuntimeWorkerConfigConsumer(
                        instance_id=worker_instance_id,
                        resolver=resolver_inst,
                    )
                    observation = consumer.consume_and_reload(
                        target_rev,
                        config_dict=cfg_obj if isinstance(cfg_obj, dict) else None,
                    )
                    observed_revision_record = adapter.report_worker_observation(
                        scope,
                        target_rev.revision_id,
                        observation,
                    )
                    bind_revision_to_evidence(manifest_metadata, observed_revision_record)
            except Exception as rev_err:
                # A scoped runtime context declares that configuration is part
                # of the execution contract.  Continuing after a failed
                # adoption would produce evidence for a configuration the
                # worker did not prove it used.
                raise RuntimeError(
                    "ScopedConfigurationAdoptionFailed: unable to adopt and "
                    "bind the active scoped configuration revision"
                ) from rev_err

        # Defense-in-depth: Ensure metadata values (including nested CLI args dicts)
        # do not retain dispatch callbacks or opaque runtime callables
        cleaned_manifest_metadata: dict[str, Any] = {}
        for mk, mv in manifest_metadata.items():
            if isinstance(mv, dict):
                cleaned_manifest_metadata[mk] = {k: v for k, v in mv.items() if not callable(v)}
            elif not callable(mv):
                cleaned_manifest_metadata[mk] = mv

        exec_manifest_scope: dict[str, str] = {}
        exec_manifest_scope_digest: str = ""
        if isinstance(runtime_context, Mapping):
            from agentv_runtime.scope import ScopeToken

            scope_tok = ScopeToken.from_tags(runtime_context)
            exec_manifest_scope = dict(scope_tok.tags)
            exec_manifest_scope_digest = scope_tok.digest

        exec_manifest = ExecutionManifest(
            manifest_id=f"man_{effective_run_id}",
            scenario_id=str(scenario_identifier),
            scenario_version=scen_ver,
            scenario_hash=scen_hash,
            agent_config=resolved_agent_config,
            runtime_config=resolved_runtime_config,
            environment=env_dict,
            metadata=cleaned_manifest_metadata,
            scope=exec_manifest_scope,
            scope_digest=exec_manifest_scope_digest,
        )
        exec_manifest_hash = exec_manifest.compute_manifest_hash()

        run_vault_dir = Path(config.RUN_LOG_DIR).resolve() / effective_run_id
        is_resume = (resumption_checkpoint is not None) or bool(resumption_token)
        manifest_file = run_vault_dir / "execution_manifest.json"
        scenario_snapshot_file = run_vault_dir / "scenario_resolved.json"

        if run_vault_dir.exists():
            if not is_resume:
                raise RuntimeError(
                    f"RunIdCollision: evidence vault already exists for run '{effective_run_id}'"
                )
            from eval_runner.run_lifecycle import (
                RunLifecycleState,
                get_run_lifecycle_state,
                transition_run_lifecycle,
            )

            lf_state = get_run_lifecycle_state(effective_run_id)
            if lf_state in (RunLifecycleState.FINALIZING, RunLifecycleState.SEALED):
                raise RuntimeError(
                    f"ResumptionError: cannot resume run '{effective_run_id}' in terminal "
                    f"lifecycle state '{lf_state.value}'"
                )
            transition_run_lifecycle(effective_run_id, RunLifecycleState.OPEN)

        # On resumption, the authoritative manifest and scenario snapshot are
        # an inseparable immutable contract.  Reject before emitting new trace
        # events or executing work when either artifact is absent, malformed,
        # or inconsistent with the other.
        if is_resume:
            if not manifest_file.is_file() or not scenario_snapshot_file.is_file():
                raise RuntimeError(
                    "ResumptionArtifactMissing: immutable execution_manifest.json and "
                    "scenario_resolved.json are required to resume a run."
                )
            try:
                with open(manifest_file, encoding="utf-8") as mf:
                    loaded_m_data = json.load(mf)
                exec_manifest = ExecutionManifest.from_dict(loaded_m_data)
                exec_manifest_hash = exec_manifest.compute_manifest_hash()
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as em_err:
                raise RuntimeError(
                    "ResumptionManifestInvalid: immutable execution_manifest.json "
                    "cannot be verified for resume."
                ) from em_err

            try:
                with open(scenario_snapshot_file, encoding="utf-8") as sf:
                    loaded_snapshot = json.load(sf)
                if not isinstance(loaded_snapshot, dict):
                    raise ValueError("scenario_resolved.json is not a JSON object")
                scenario_snapshot = loaded_snapshot
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as sf_err:
                raise RuntimeError(
                    "ResumptionSnapshotInvalid: immutable scenario_resolved.json "
                    "cannot be verified for resume."
                ) from sf_err

            snapshot_hash = compute_scenario_hash(scenario_snapshot)
            if snapshot_hash != exec_manifest.scenario_hash:
                raise RuntimeError(
                    "ResumptionScenarioHashMismatch: scenario_resolved.json does not match "
                    "the authoritative execution manifest."
                )

            snapshot_id = (
                scenario_snapshot.get("id")
                or (scenario_snapshot.get("metadata") or {}).get("id")
                or (scenario_snapshot.get("metadata") or {}).get("name")
                or "unknown"
            )
            snapshot_version = str(
                scenario_snapshot.get("version")
                or (scenario_snapshot.get("metadata") or {}).get("version")
                or "1.0.0"
            )
            if (
                str(snapshot_id) != exec_manifest.scenario_id
                or snapshot_version != exec_manifest.scenario_version
            ):
                raise RuntimeError(
                    "ResumptionScenarioIdentityMismatch: scenario_resolved.json does not "
                    "match the authoritative execution manifest."
                )

            resumed_req_oracles = compile_required_oracle_ids(
                scenario_snapshot, resolved_policy=self.policy_evaluator
            )
            manifest_req_oracles = sorted(
                set(
                    exec_manifest.metadata.get("required_oracle_ids")
                    or exec_manifest.runtime_config.get("required_oracle_ids")
                    or []
                )
            )
            if resumed_req_oracles != manifest_req_oracles:
                raise RuntimeError(
                    "ResumptionOracleInventoryMismatch: scenario snapshot and execution "
                    "manifest required-oracle inventories differ."
                )

            scenario = scenario_snapshot
            scenario_identifier = exec_manifest.scenario_id
            scen_ver = exec_manifest.scenario_version
            scen_hash = exec_manifest.scenario_hash
            req_oracles = resumed_req_oracles
            manifest_mode = exec_manifest.runtime_config.get(
                "execution_mode"
            ) or exec_manifest.metadata.get("execution_mode")
            if manifest_mode:
                execution_mode = manifest_mode
                execution_mode_declared = True
            from .context import _freeze_dict

            new_meta = dict(ctx.metadata) if isinstance(ctx.metadata, Mapping) else {}
            new_meta["execution_mode"] = execution_mode
            new_meta["execution_mode_declared"] = execution_mode_declared
            object.__setattr__(ctx, "identifier", str(scenario_identifier))
            object.__setattr__(ctx, "scenario_data", _freeze_dict(scenario_snapshot))
            object.__setattr__(ctx, "metadata", _freeze_dict(new_meta))

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
                        execution_mode_declared
                        or scenario.get("execution_mode")
                        or (metadata or {}).get("execution_mode")
                        or scenario.get("metadata", {}).get("execution_mode")
                    ),
                    "reproducibility_fingerprint": fingerprint(repro_contract),
                    "is_resume": is_resume,
                    "resumption_token": resumption_token,
                },
                span_context=ctx.span_context,
            )

            # The evaluator owns the authoritative execution manifest.  A
            # launcher/preflight may have written a provisional manifest into
            # the vault, but it can describe a different resolved scenario or
            # runtime configuration.  On a fresh run it must never survive as
            # the certification artifact: finalization is signed against this
            # evaluator-built manifest.  A resume is different—the initial
            # authoritative manifest is immutable and was reloaded above.
            if not is_resume:
                run_vault_dir.mkdir(parents=True, exist_ok=True)
                manifest_tmp = manifest_file.with_suffix(".json.tmp")
                scenario_tmp = scenario_snapshot_file.with_suffix(".json.tmp")
                with open(manifest_tmp, "w", encoding="utf-8") as mf:
                    json.dump(exec_manifest.to_dict(), mf, indent=2)
                with open(scenario_tmp, "w", encoding="utf-8") as sf:
                    json.dump(scenario_snapshot, sf, indent=2)
                manifest_tmp.replace(manifest_file)
                scenario_tmp.replace(scenario_snapshot_file)

            if self.run_store is not None:
                self.run_store.create_run(
                    run_id=effective_run_id,
                    scenario_id=str(scenario_identifier),
                    agent_id=(metadata or {}).get("agent_id"),
                    metadata=dict(ctx.metadata) if ctx.metadata else {},
                    context=(metadata or {}).get("runtime_context"),
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

                # A resumed run must execute the exact frozen scenario
                # contract, not a caller-supplied scenario that may have
                # changed while the run was awaiting approval.
                session_contract = scenario_snapshot if is_resume else scenario
                scenario_copy = copy.deepcopy(session_contract)
                if max_turns:
                    scenario_copy["max_turns"] = max_turns

                session = SessionManager(
                    effective_run_id,
                    scenario_copy,
                    # Bind the persisted scenario snapshot to the exact
                    # pre-execution contract hashed above. ``scenario_copy``
                    # carries runtime-only controls such as max_turns.
                    scenario_contract=session_contract,
                    metadata=ctx.metadata,
                    seed=current_seed,
                    cancellation_event=cancellation_event,
                    resumption_checkpoint=resumption_checkpoint,
                    resumption_token=resumption_token,
                    resolved_config=self.resolved_config,
                    artifact_store=self.artifact_store,
                    checkpoint_store=self.checkpoint_store,
                    policy_evaluator=self.policy_evaluator,
                    signing_backend=self.signing_backend,
                )
                try:
                    attempt_results = await session.execute_tasks(k)
                except RunSuspendedForApproval as susp:
                    from eval_runner.run_lifecycle import (
                        RunLifecycleState,
                        transition_run_lifecycle,
                    )

                    logger.info(
                        "Evaluation run %s suspended for approval (token: %s)",
                        effective_run_id,
                        susp.approval_token,
                    )
                    transition_run_lifecycle(
                        effective_run_id,
                        RunLifecycleState.PAUSED_FOR_APPROVAL,
                        log_dir=session.log_root,
                    )
                    raise

                # [Forensic Sync] propagate resolved routing (e.g. Port 8000)
                from .context import _freeze_dict

                new_meta = dict(ctx.metadata) if isinstance(ctx.metadata, Mapping) else {}
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
            post_process_error = None
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
                post_process_error = f"Evaluator post-processing / statistics failure: {e}"
                logger.error("Runner Post-Process Error: %s\n%s", e, tb)
                events.emit(
                    events.CoreEvents.ERROR,
                    {
                        "run_id": effective_run_id,
                        "message": post_process_error,
                        "traceback": tb,
                    },
                )

            if post_process_error is not None:
                # [Item 3: P0 Fail-Closed Post-Processing]
                # Any failure in statistics or aggregator processing must transition to
                # EVALUATION_INVALID, certifiable=False, and forbid standard finalization.
                events.emit(
                    events.CoreEvents.EVALUATION_INVALID,
                    {
                        "run_id": effective_run_id,
                        "status": "evaluation_invalid",
                        "error": post_process_error,
                        "outcome": "EVALUATION_INVALID",
                    },
                    span_context=ctx.span_context,
                )
                events.emit(
                    events.CoreEvents.RUN_END,
                    {
                        "run_id": effective_run_id,
                        "status": "evaluation_invalid",
                        "passed": False,
                        "score": 0.0,
                        "pass_at_k": 0.0,
                        "evaluation_valid": False,
                        "outcome": "EVALUATION_INVALID",
                        "certifiable": False,
                        "error": post_process_error,
                        "finalization": None,
                        "metadata": {
                            **(dict(ctx.metadata) if isinstance(ctx.metadata, Mapping) else {}),
                            "evaluation_valid": False,
                            "outcome": "EVALUATION_INVALID",
                            "uncertifiable": True,
                            "certifiable": False,
                            "error": post_process_error,
                        },
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
                        "error": post_process_error,
                        "evaluation_valid": False,
                        "outcome": "EVALUATION_INVALID",
                        "uncertifiable": True,
                        "certifiable": False,
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

            # This event is part of the pre-finalization trace and therefore
            # must be persisted before computing the root bound by finalization.
            events.emit(
                events.CoreEvents.STRATEGY_END,
                {
                    "run_id": effective_run_id,
                    "strategy": "pass_at_k",
                    "status": "success" if pass_at_k > 0 else "failure",
                },
                span_context=ctx.span_context,
            )

            trace_events: list[tuple[dict[str, Any], str]] = []
            trace_read_error: str | None = None
            try:
                stored_events = self.run_store.get_events(
                    effective_run_id, offset=0, limit=10_000_000
                )
                trace_events = [
                    (
                        event,
                        json.dumps(event, default=str, separators=(",", ":")),
                    )
                    for event in stored_events
                    if isinstance(event, dict)
                ]
                if not trace_events:
                    trace_read_error = "RunStorageProvider returned no trace events."
            except Exception as read_err:
                trace_read_error = f"RunStorageProvider event retrieval failed: {read_err}"
                logger.debug("Failed reading provider trace for evidence graph root: %s", read_err)

            # [Item 2: P0 Physical Trace Exclusivity]
            if is_certification and (trace_read_error is not None or not trace_events):
                fail_msg = (
                    f"Authoritative physical trace unreadable or missing for certification: "
                    f"{trace_read_error or 'trace stream was empty'}. "
                    "Synthetic evidence reconstruction is prohibited in certification mode."
                )
                logger.error(fail_msg)
                events.emit(
                    events.CoreEvents.CERTIFICATION_FAILED,
                    {
                        "run_id": effective_run_id,
                        "status": "certification_failed",
                        "error": fail_msg,
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
                        "error": fail_msg,
                        "finalization": None,
                        "metadata": {
                            **(dict(ctx.metadata) if isinstance(ctx.metadata, Mapping) else {}),
                            "uncertifiable": True,
                        },
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
                        "error": fail_msg,
                        "uncertifiable": True,
                    },
                )

            if not trace_events:
                # DEBUG / TEST: synthetic reconstruction permitted, certificate prohibited
                from .context import _freeze_dict

                meta_dict = dict(ctx.metadata) if isinstance(ctx.metadata, Mapping) else {}
                meta_dict["uncertifiable"] = True
                meta_dict["provisional"] = True
                object.__setattr__(ctx, "metadata", _freeze_dict(meta_dict))
                for a in collected_assertions:
                    synthetic_event = {"event": "assertion_evaluated", **a}
                    from agentv_runtime.canonical import canonical_json_dumps

                    trace_events.append((synthetic_event, canonical_json_dumps(synthetic_event)))

            ev_graph = build_evidence_graph_from_events(
                trace_events, required_oracle_ids=req_oracles
            )
            evidence_root = ev_graph["evidence_root_hash"]
            trace_sequence_numbers = [
                event[0].get("_seq")
                for event in trace_events
                if isinstance(event[0].get("_seq"), int)
            ]
            terminal_trace_seq = max(trace_sequence_numbers, default=len(trace_events))

            # Authenticated EvaluatorFinalizationRecord bound to upfront manifest hash
            evaluator_id = getattr(self, "evaluator_identity", None) or "system_id"
            sign_err_msg = None
            eval_priv = None
            try:
                backend_can_sign = bool(
                    self.signing_backend
                    and getattr(self.signing_backend, "can_sign", lambda: True)()
                )
                if backend_can_sign:
                    eval_priv = self.signing_backend
                else:
                    from eval_runner.identity import IdentityService

                    # Local reference fallback only. External signing backends
                    # must not be forced to export a PEM private key.
                    eval_priv = IdentityService.get_private_key(
                        evaluator_id, auto_provision=not is_certification
                    )
                    if not eval_priv and evaluator_id != "eval_runner.runner.EvaluationKernel":
                        eval_priv = IdentityService.get_private_key(
                            "eval_runner.runner.EvaluationKernel",
                            auto_provision=not is_certification,
                        )
                        if eval_priv:
                            evaluator_id = "eval_runner.runner.EvaluationKernel"
                if not eval_priv:
                    sign_err_msg = (
                        f"Evaluator private key for '{evaluator_id}' not found in TRUST_ROOT or "
                        f"environment (auto-provisioning prohibited for certification: "
                        f"is_certification={is_certification})"
                    )
                    logger.error(sign_err_msg)
            except Exception as key_err:
                sign_err_msg = str(key_err)
                logger.error("Evaluator private key retrieval error: %s", key_err)

            # Campaign acceptance policy:
            # 1. Reject incomplete campaigns (truncated by cancellation or early termination).
            # 2. Enforce explicit acceptance across required attempts:
            # all required attempts must pass.
            is_truncated = bool(
                attempt_statistics.get("truncated_by_cancellation")
                or len(all_attempt_results) < attempts
            )
            is_campaign_complete = not is_truncated and len(all_attempt_results) == attempts
            all_attempts_passed = bool(
                is_campaign_complete and attempt_statistics.get("all_pass", False)
            )

            # Separate statistical reliability from certification eligibility.
            finalization_outcome = "pass" if all_attempts_passed else "fail"
            finalization_score = (
                1.0
                if all_attempts_passed
                else (
                    float(successful_attempts_count) / float(len(all_attempt_results))
                    if all_attempt_results
                    else 0.0
                )
            )

            finalization_record = EvaluatorFinalizationRecord(
                finalization_id=f"fin_{effective_run_id}",
                run_id=effective_run_id,
                execution_manifest_hash=exec_manifest_hash,
                # Finalization binds the same immutable identity carried by
                # the execution manifest, never a mutable working scenario.
                scenario_id=exec_manifest.scenario_id,
                scenario_version=exec_manifest.scenario_version,
                scenario_hash=exec_manifest.scenario_hash,
                evaluator_identity=evaluator_id,
                evaluator_config_hash=getattr(self.resolved_config, "config_hash", "") or "none",
                required_oracle_ids=req_oracles,
                evidence_root_hash=evidence_root,
                outcome=finalization_outcome,
                score=finalization_score,
                # This is a trace boundary, not an attempt count.  It binds
                # finalization to the last event committed before finalization.
                terminal_seq=terminal_trace_seq,
            )
            try:
                if eval_priv:
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
                if self.run_store:
                    try:
                        failed_manifest = {
                            "run_id": effective_run_id,
                            "scenario_id": str(scenario.get("id", "unknown")),
                            "status": "FAILED",
                            "error": (
                                "Authoritative evaluator finalization signing failed: "
                                f"{sign_err_msg}"
                            ),
                            "attempts": attempts,
                            "pass_at_k": 0.0,
                            "results": all_attempt_results,
                        }
                        runtime_context = (
                            ctx.metadata.get("runtime_context")
                            if isinstance(ctx.metadata, Mapping)
                            else None
                        )
                        if not runtime_context:
                            from eval_runner.run_index import read_run_index

                            idx_rec = read_run_index(effective_run_id)
                            if idx_rec and isinstance(idx_rec.get("context"), Mapping):
                                runtime_context = idx_rec["context"]
                        if isinstance(runtime_context, Mapping):
                            from agentv_runtime.scope import ScopeToken

                            token = ScopeToken.from_tags(runtime_context)
                            failed_manifest["context"] = token.tags
                            failed_manifest["scope_digest"] = token.digest
                        if observed_revision_record is not None:
                            from eval_runner.services.config_revision import (
                                bind_revision_to_evidence,
                            )

                            bind_revision_to_evidence(failed_manifest, observed_revision_record)
                        self.run_store.save_run_manifest(effective_run_id, failed_manifest)
                    except Exception as err:
                        logger.debug("Failed saving failed run manifest on signing error: %s", err)
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
                events.CoreEvents.RUN_END,
                {
                    "run_id": effective_run_id,
                    "status": "success" if finalization_outcome == "pass" else "failure",
                    "passed": bool(finalization_outcome == "pass"),
                    "score": finalization_score,
                    "pass_at_k": pass_at_k,
                    "attempt_success_rate": attempt_statistics.get("attempt_success_rate", 0.0),
                    "all_pass": attempt_statistics.get("all_pass", False),
                    "any_pass": attempt_statistics.get("any_pass", False),
                    "successful_attempts": successful_attempts_count,
                    "total_attempts": attempts,
                    "executed_attempts": len(all_attempt_results),
                    "campaign_complete": is_campaign_complete,
                    "acceptance_policy": "all_required_attempts_pass",
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
                        "execution_manifest": exec_manifest.to_dict(),
                        "scenario_data": scenario,
                    }
                    runtime_context = (
                        ctx.metadata.get("runtime_context")
                        if isinstance(ctx.metadata, Mapping)
                        else None
                    )
                    if not runtime_context:
                        from eval_runner.run_index import read_run_index

                        idx_rec = read_run_index(effective_run_id)
                        if idx_rec and isinstance(idx_rec.get("context"), Mapping):
                            runtime_context = idx_rec["context"]

                    if isinstance(runtime_context, Mapping):
                        from agentv_runtime.scope import ScopeToken

                        token = ScopeToken.from_tags(runtime_context)
                        manifest_data["context"] = token.tags
                        manifest_data["scope_digest"] = token.digest
                    if observed_revision_record is not None:
                        from eval_runner.services.config_revision import bind_revision_to_evidence

                        bind_revision_to_evidence(manifest_data, observed_revision_record)
                    self.run_store.save_run_manifest(effective_run_id, manifest_data)
                except Exception as e:
                    logger.debug(f"Failed to save manifest to RunStore: {e}")

            result_metadata = dict(ctx.metadata) if isinstance(ctx.metadata, Mapping) else {}
            result_metadata["execution_mode"] = str(execution_mode)
            result_metadata["reproducibility"] = repro_contract
            result_metadata["reproducibility_fingerprint"] = fingerprint(repro_contract)
            result_metadata["campaign_complete"] = is_campaign_complete
            result_metadata["acceptance_policy"] = "all_required_attempts_pass"
            result_metadata["outcome"] = finalization_outcome

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

            # First-class NodeVerdict gating across all typed evidence dimensions
            if "node_verdict" in res and isinstance(res["node_verdict"], dict):
                nv = res["node_verdict"]
                if nv.get("verification") in ("fail", "invalid"):
                    return False
                if nv.get("policy") == "denied":
                    return False
                if nv.get("parity") == "fail":
                    return False
                if nv.get("reconciliation") in ("fail", "invalid"):
                    return False
                if nv.get("overall") not in ("success", "not_applicable"):
                    return False

            # Mandatory State Reconciliation Gating: Missing observations
            # or mismatched state fail closed
            if "reconciliation" in res and isinstance(res["reconciliation"], dict):
                recon = res["reconciliation"]
                if recon.get("expected_change_checks") and not recon.get("reconciled"):
                    return False

            # Typed OracleResult requiredness lattice evaluation
            if "oracle_results" in res and isinstance(res["oracle_results"], list):
                for or_res in res["oracle_results"]:
                    req_level = str(or_res.get("requiredness", "REQUIRED")).upper()
                    outcome = str(or_res.get("outcome", "NOT_EVALUATED")).upper()
                    if req_level == "REQUIRED" and outcome != "PASS":
                        return False
                    # OPTIONAL and INFORMATIONAL oracles never gate attempt success

            # 3. Oracle rows: invalid or non-PASS assertions veto the attempt.
            for m in res.get("metrics") or []:
                if not isinstance(m, dict):
                    continue
                is_opt_or_info = m.get("severity") == "informational" or str(
                    m.get("requiredness", "")
                ).upper() in ("OPTIONAL", "INFORMATIONAL")
                if is_opt_or_info:
                    continue
                if m.get("invalid") or m.get("status") == "EVALUATION_INVALID":
                    return False
                outcome = str(m.get("outcome", "")).upper()
                if outcome:
                    if outcome != "PASS":
                        return False
                elif m.get("success") is not True:
                    return False
                if m.get("success") is False:
                    return False

            for h in res.get("state_hygiene") or []:
                if not isinstance(h, dict):
                    continue
                if h.get("invalid") or h.get("status") == "EVALUATION_INVALID":
                    return False
                if str(h.get("requiredness", "")).upper() in ("OPTIONAL", "INFORMATIONAL"):
                    continue
                outcome = str(h.get("outcome", "")).upper()
                if outcome:
                    if outcome != "PASS":
                        return False
                elif h.get("success") is not True:
                    return False
                if h.get("success") is False:
                    return False

            for p in res.get("state_parity") or []:
                if not isinstance(p, dict):
                    continue
                if p.get("invalid") or p.get("status") == "EVALUATION_INVALID":
                    return False
                if str(p.get("requiredness", "")).upper() in ("OPTIONAL", "INFORMATIONAL"):
                    continue
                outcome = str(p.get("outcome", "")).upper()
                if outcome:
                    if outcome != "PASS":
                        return False
                elif p.get("success") is not True:
                    return False
                if p.get("success") is False:
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
    resumption_token: str | None = None,
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

    async def _run_with_adapter_cleanup() -> EvaluationResult:
        """Run one evaluation and release this process's shared HTTP sessions."""
        try:
            return await runner.run(
                scenario=scenario,
                attempts=attempts,
                run_id=run_id,
                seed=seed,
                metadata=metadata,
                max_turns=max_turns,
                cancellation_event=cancellation_event,
                resumption_checkpoint=resumption_checkpoint,
                resumption_token=resumption_token,
            )
        finally:
            from .adapters import close_adapter_sessions

            await close_adapter_sessions()

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
                _run_with_adapter_cleanup(),
            ).result()
    else:
        return loop.run_until_complete(_run_with_adapter_cleanup())
