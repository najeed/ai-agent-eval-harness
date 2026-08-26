"""
session.py

Manages the state and trajectory of an evaluation session.
Handles conversation history, tool results, and plugin interception.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

try:
    import psutil  # Forensic telemetry fallback
except ImportError:
    psutil = None

logger = logging.getLogger(__name__)

from agentv_runtime.evidence_graph import decision_evidence_root_hash  # noqa: E402

from . import config, events, metrics  # noqa: E402
from .context import TurnContext  # noqa: E402
from .engine import AgentAdapterRegistry  # noqa: E402
from .events import CoreEvents, Event, EventEmitter  # noqa: E402
from .execution_ir import (  # noqa: E402
    CompiledEvaluationPlan,
    ExecutionIdentity,
    ExecutionMode,
    NodeVerdict,
    OracleResult,
    PlanValidationError,
    WorkflowStatus,
    compile_workflow,
)
from .forensics import ForensicCollector  # noqa: E402
from .session_components import (  # noqa: E402
    SessionApprovalManager,
    SessionCheckpointManager,
    SessionMetricsCalculator,
    SessionStateParityVerifier,
    ToolExecutionCoordinator,
    TurnStateManager,
)
from .tool_sandbox import ToolSandbox  # noqa: E402
from .utils import crypto  # noqa: E402
from .workflow_interpreter import WorkflowInterpreter  # noqa: E402

# Security Guardrails: Fork Bomb Prevention
MAX_FORK_DEPTH = config.MAX_FORK_DEPTH
MAX_FORK_BREADTH = config.MAX_FORK_BREADTH


@dataclass
class ExecutionInstanceContext:
    """
    Isolated per-execution-instance context.
    Owns conversation history, actions ledger, turns taken, isolated sandbox fork,
    and state snapshots so parallel branches never bleed state.
    """

    scenario_node_id: str
    execution_instance_id: str
    parent_execution_id: str | None
    attempt_number: int
    identity: ExecutionIdentity
    sandbox: Any
    history: list[dict[str, Any]] = field(default_factory=list)
    actions: dict[str, Any] = field(default_factory=lambda: {"used_tools": []})
    turns_taken: int = 0
    state_before: dict[str, Any] | None = None
    state_after: dict[str, Any] | None = None
    metrics: list[dict[str, Any]] = field(default_factory=list)
    policy_decisions: list[dict[str, Any]] = field(default_factory=list)


class SessionManager:
    """
    Manages a single evaluation attempt's lifecycle.
    Updated for Session-Scoped Lifecycle (Inversion of Control).
    """

    def __init__(
        self,
        run_id: str,
        scenario: dict,
        metadata: dict | None = None,
        seed: int | None = None,
        log_root: Path | None = None,
        cancellation_event: Any | None = None,
        resumption_checkpoint: dict | None = None,
        resolved_config: Any | None = None,
        artifact_store: Any | None = None,
        checkpoint_store: Any | None = None,
        policy_evaluator: Any | None = None,
        signing_backend: Any | None = None,
    ):
        from .plugins import PluginManager

        self.run_id = run_id
        self.cancellation_event = cancellation_event
        self.resolved_config = resolved_config
        self.artifact_store = artifact_store
        self.checkpoint_store = checkpoint_store
        self.policy_evaluator = policy_evaluator
        self.signing_backend = signing_backend
        # [Forensic Isolation] Ensure parallel runs don't mutate shared scenario state
        self.scenario = copy.deepcopy(scenario)
        # Authoritatively inject run_id for downstream forensic affinity (e.g., ToolSandbox)
        self.scenario["run_id"] = run_id

        # [AgentV v1.6.0] Authoritative Metadata Propagation (Ensured mutable)
        self.metadata = dict(metadata or {})
        # Centralized identifier (resolved and normalized in Loader)
        self.identifier = scenario.get("id") or scenario.get("metadata", {}).get("name", "unknown")

        # [AgentV v1.6.0] Authoritative Metadata Discovery
        self.session_metadata = {
            "protocol": "http",
            "agent": None,
            "identifier": self.identifier,
            "seed": seed,
            "span_context": self.metadata.get("span_context"),
        }
        if metadata:
            self.session_metadata.update(metadata)

        self.max_turns = int(scenario.get("max_turns", config.EVAL_MAX_TURNS)) or 10
        self.fork_depth = scenario.get("_fork_depth", 0)

        # [AgentV v2.0.0] Explicit execution truth mode:
        # simulated | record_replay | live | hybrid. Simulation must never
        # masquerade as live verification.
        mode_raw = (
            scenario.get("execution_mode")
            or self.metadata.get("execution_mode")
            or scenario.get("metadata", {}).get("execution_mode")
        )
        execution_mode_declared = bool(mode_raw)
        if not mode_raw:
            mode_raw = ExecutionMode.SIMULATED.value
            # Silent SIMULATED default is LOUD: operators get an
            # unmistakable warning and the certificate will be stamped
            # provisional=true (non-authoritative for audits).
            print(
                "      [WARNING] EXECUTION MODE NOT DECLARED - defaulting to "
                "'simulated'. This run can NEVER be cited as live/replay "
                "verification. Declare execution_mode explicitly."
            )
            logger.warning(
                "Run %s: execution_mode not declared; defaulting to simulated (provisional).",
                self.run_id,
            )
        try:
            self.execution_mode = ExecutionMode(str(mode_raw))
        except ValueError as err:
            # [A3] Fail-closed: an invalid execution_mode is a run-level
            # failure. The kernel never silently downgrades to SIMULATED.
            valid = [m.value for m in ExecutionMode]
            raise ValueError(
                f"Invalid execution_mode '{mode_raw}'. Valid modes: {valid}. "
                "Refusing to fall back to SIMULATED (fail-closed)."
            ) from err

        # Truth-mode vs adapter consistency. A session that can reach a
        # real agent endpoint may never be silently labeled SIMULATED: the
        # operator must declare live/hybrid, or explicitly accept simulated.
        import os as _os

        _endpoint = self.session_metadata.get("agent")
        if (
            _endpoint
            and self.execution_mode is ExecutionMode.SIMULATED
            and not config.ENABLE_DEMO
            and _os.getenv("AES_ALLOW_IMPLICIT_SIMULATED", "").lower() != "1"
        ):
            raise ValueError(
                f"execution_mode conflict: an agent endpoint ('{_endpoint}') is "
                "configured but execution_mode defaults to 'simulated'. Declare "
                "execution_mode='live' | 'hybrid' | 'record_replay', or pass "
                "metadata execution_mode='simulated' explicitly to attest that "
                "no live verification is claimed."
            )
        self.metadata["execution_mode"] = self.execution_mode.value
        self.metadata["execution_mode_declared"] = execution_mode_declared

        # [AgentV v2.0.0] First-class attempt identity
        import uuid as _uuid

        self.attempt_id: str = _uuid.uuid4().hex

        # [AgentV v1.6.0] Identifier Tracking
        # Note: Purged global os.environ writes (AES_RUN_ID, AES_IDENTIFIER)
        # to ensure parallel evaluation safety. Identity is now strictly context-bound.

        # Session-Scoped Infrastructure
        self.event_bus = EventEmitter(run_id=run_id)
        # [Telemetry Bridge] Propagate events to global subscribers
        if not self.metadata.get("isolate_events", False):
            self.event_bus.subscribe(lambda e: events.emit(e.name, e.data, e.span_context))

        self.plugin_manager = PluginManager()
        self.log_root = log_root or config.RUN_LOG_DIR
        self.run_vault = self.log_root / run_id
        self.forensics = ForensicCollector(run_id, self.run_vault)

        # [Industrial Persistence] Save ORIGINAL scenario baseline
        self.run_vault.mkdir(parents=True, exist_ok=True)
        with open(self.run_vault / "scenario_original.json", "w", encoding="utf-8") as f:
            json.dump(self.scenario, f, indent=2)

        # Decomposed Session Subsystems
        self.turn_state_manager = TurnStateManager(max_turns=self.max_turns)
        self.checkpoint_manager = SessionCheckpointManager(
            run_id=self.run_id, store=self.checkpoint_store
        )
        self.approval_manager = SessionApprovalManager(
            run_id=self.run_id,
            checkpoint_manager=self.checkpoint_manager,
            state_provider=lambda: {
                "scenario_data": self.scenario,
                "turn_state": self.turn_state_manager.snapshot(),
                "tool_state": self.tool_execution_coordinator.snapshot(),
                "metadata": dict(self.metadata),
                "config_hash": getattr(self.resolved_config, "config_hash", None)
                if self.resolved_config
                else None,
            },
        )
        self.tool_execution_coordinator = ToolExecutionCoordinator()
        self.metrics_calculator = SessionMetricsCalculator(session_manager=self)
        self.state_parity_verifier = SessionStateParityVerifier(session_manager=self)

        if resumption_checkpoint:
            self.restore_from_checkpoint(resumption_checkpoint)

        # Initialize plugins for this session
        self.plugin_manager.load_plugins()

        # [Industrial Synchronization] Import ad-hoc plugins from global manager (CLI injection)
        from . import plugins as global_plugins

        for class_name, prov in global_plugins.manager.provenance_map.items():
            if prov.get("origin") == "EXTERNAL":
                try:
                    self.plugin_manager.load(prov["path"])
                except Exception as e:
                    logger.warning(
                        f"   [Session] Failed to re-load ad-hoc plugin {class_name}: {e}"
                    )

        # 2. Forensic Archiving: Preserve logic for non-repudiation
        # Industrial Rule: Only archive 'EXTERNAL' (ad-hoc) plugins to protect proprietary IP.
        # INTERNAL, MEMBER, and PROJECT plugins are tracked via cryptographic provenance (hashes).
        for class_name, prov in self.plugin_manager.provenance_map.items():
            if prov.get("origin") == "EXTERNAL":
                try:
                    self.forensics.archive_plugin(Path(prov["path"]))
                except Exception as e:
                    logger.warning(
                        f"   [Session] Failed to archive ad-hoc plugin {class_name}: {e}"
                    )

        # 3. Provenance Injection: Ensure all plugins are recorded in the session metadata
        self.metadata["plugin_provenance"] = self.plugin_manager.provenance_map

        # [AES v1.6.0] Dynamic Metric Discovery
        self.plugin_manager.trigger("on_discover_metrics", metrics.MetricRegistry)

        # Auto-subscribe plugins to the session bus (Bridge to legacy Hooks)
        def _bridge_event_internal(event: Event):
            # Map events to legacy hook names
            hook_name = f"on_{event.name.lower()}"
            # Standard Unpacking: Pass event data and turns_taken as context proxy
            self.plugin_manager.trigger(hook_name, context=self, **event.data)

        self._bridge_ref = _bridge_event_internal
        self.event_bus.subscribe(self._bridge_ref)

        from .routing import RoutingRegistry

        # 🚀 [AES v1.6.0] Authoritative Routing Resolution
        # Sequence: CLI Override > Capability Discovery > Scenario Metadata > Global Default
        scenario_meta_agent = scenario.get("metadata", {}).get("agent", {})

        curr_agent = self.session_metadata.get("agent")
        curr_proto = self.session_metadata.get("protocol")

        # 1. State Stickiness Detection (CLI/Env Overrides)
        is_sticky_agent = curr_agent and curr_agent != config.AGENT_API_URL
        is_sticky_proto = curr_proto and curr_proto != "http"

        # 2. Level 1: Scenario Metadata (Portable Fallback)
        if isinstance(scenario_meta_agent, dict):
            if not is_sticky_proto and scenario_meta_agent.get("protocol"):
                self.session_metadata["protocol"] = scenario_meta_agent["protocol"]
            if not is_sticky_agent and scenario_meta_agent.get("endpoint"):
                self.session_metadata["agent"] = scenario_meta_agent["endpoint"]

        # 3. Level 2: Capability Discovery (Environment Governance Override)
        capabilities = scenario.get("capabilities") or scenario.get("metadata", {}).get(
            "capabilities", []
        )
        if capabilities:
            resolved = RoutingRegistry.resolve(capabilities)
            if resolved:
                # Dynamic Resolution precedence
                if not is_sticky_proto:
                    self.session_metadata["protocol"] = resolved.get("protocol")
                if not is_sticky_agent:
                    self.session_metadata["agent"] = resolved.get("endpoint")

                # [RFC-003]: Deep-Sync Registry Metadata (mapping_overrides, etc.)
                if resolved.get("metadata"):
                    self.session_metadata.update(resolved["metadata"])
                    logger.debug(
                        f"      [Routing] Metadata Deep-Sync: {list(resolved['metadata'].keys())}"
                    )

                self.event_bus.emit(
                    (
                        CoreEvents.ROUTING_RESOLVED
                        if hasattr(CoreEvents, "ROUTING_RESOLVED")
                        else "ROUTING_RESOLVED"
                    ),
                    {
                        "capabilities": capabilities,
                        "resolved_protocol": resolved.get("protocol"),
                        "resolved_endpoint": resolved.get("endpoint"),
                        "source": "capability_registry",
                    },
                )
                logger.info(f"      [Routing] Infrastructure resolved via: {capabilities}")

        # [Forensic Sync] Deep-sync resolved routing to scenario metadata for reporting parity
        proto_val = self.session_metadata.get("protocol", "http")
        if isinstance(proto_val, str):
            proto_val = proto_val.lower().strip()
        self.session_metadata["protocol"] = proto_val
        self.metadata["protocol"] = proto_val

        # Resolve default agent if still None
        if not self.session_metadata.get("agent"):
            proto = self.metadata["protocol"]
            if proto == "http":
                self.session_metadata["agent"] = config.AGENT_API_URL
            elif proto == "local":
                self.session_metadata["agent"] = os.getenv("AGENT_LOCAL_CMD")
            elif proto == "socket":
                self.session_metadata["agent"] = os.getenv("AGENT_SOCKET_ADDR")

        self.metadata["agent"] = self.session_metadata.get("agent")
        if "metadata" in self.scenario:
            self.scenario["metadata"]["protocol"] = self.metadata["protocol"]
            self.scenario["metadata"]["agent"] = self.metadata["agent"]

        # [Industrial Persistence] Save RESOLVED scenario (post-routing discovery)
        with open(self.run_vault / "scenario_resolved.json", "w", encoding="utf-8") as f:
            json.dump(self.scenario, f, indent=2)

        # 🚀 [Forensic Hardening] Protocol Trace capture
        self.protocol_sequence: list[str] = []

        def _trace_handshake(e: Event):
            # Authoritative Handshake Capture (Industrial Protocol AES v1.4)
            if e.name == CoreEvents.STEP_START:
                step = e.data.get("step")
                if step and (not self.protocol_sequence or self.protocol_sequence[-1] != step):
                    self.protocol_sequence.append(step)
            # Legacy Fallback for global event bus traces
            elif e.name == "MANUAL_INIT":
                self.protocol_sequence.append("init")

        self.event_bus.subscribe(_trace_handshake)

        # [Forensic Hardening] State Snapshot storage
        self.state_snapshots: list[str] = []
        self._current_turn = 0

        # [Forensic Hardening] Resource Telemetry storage
        self.resource_telemetry: list[dict[str, float]] = []
        if not psutil:
            logger.info(
                "      [Session] psutil not found; hardware resource telemetry is disabled."
            )
        else:
            # [Forensic Sidecar] Initialize CSV for industrial audit
            # Ensures O(1) header writing at session start.
            headers = ["timestamp", "cpu_percent", "rss_mb", "vms_mb", "disk_usage_percent"]
            self.forensics.init_telemetry(headers)

    @property
    def turn_number(self) -> int:
        if hasattr(self, "turn_state_manager") and self.turn_state_manager:
            return self.turn_state_manager.current_turn
        return getattr(self, "_current_turn", 0)

    @turn_number.setter
    def turn_number(self, val: int):
        if hasattr(self, "turn_state_manager") and self.turn_state_manager:
            self.turn_state_manager.current_turn = val
        self._current_turn = val

    def save_checkpoint(
        self, checkpoint_id: str | None = None, metadata: dict[str, Any] | None = None
    ) -> str:
        """Explicitly checkpoints current session state via CheckpointStore interface."""
        state = {
            "turn": self.turn_number,
            "history": getattr(self.turn_state_manager, "history", []),
            "metadata": self.metadata,
        }
        return self.checkpoint_manager.create_checkpoint(
            state, checkpoint_id=checkpoint_id, metadata=metadata
        )

    def restore_from_checkpoint(
        self,
        checkpoint_data: dict[str, Any] | None = None,
        resumption_token: str | None = None,
    ) -> bool:
        """Restores session state from latest or provided checkpoint."""
        data = checkpoint_data or self.checkpoint_manager.load_latest_checkpoint()
        if not data:
            return False
        turn = data.get("turn", data.get("current_turn", data.get("turn_number", 0)))
        self.turn_number = int(turn)
        if hasattr(self, "turn_state_manager") and self.turn_state_manager:
            self.turn_state_manager.restore(data.get("turn_state", data))
        if "metadata" in data and isinstance(data["metadata"], dict):
            self.session_metadata.update(data["metadata"])
        if "session_metadata" in data and isinstance(data["session_metadata"], dict):
            self.session_metadata.update(data["session_metadata"])
        return True

    async def execute_tasks(self, attempt_number: int) -> list[dict[str, Any]]:
        all_task_results: list[dict[str, Any]] = []
        global_cumulative_history = []
        node_id = "unknown"

        sandbox = ToolSandbox(
            self.scenario,
            event_bus=self.event_bus,
            forensics=self.forensics,
            plugin_manager=self.plugin_manager,
            jail_root=(self.log_root / self.run_id / "terminal_jail").resolve(),
            policy_evaluator=self.policy_evaluator,
        )
        self.sandbox = sandbox
        try:
            await sandbox.setup()

            # [AgentV v2.0.0] Canonical Execution IR compilation.
            # The DAG is the control-flow contract.
            try:
                plan = compile_workflow(self.scenario)
            except PlanValidationError as e:
                err_msg = f"Execution IR Compilation Failed for {self.run_id}: {e}"
                sys.stderr.write(f"      [IR Error] {err_msg}\n")
                sys.stderr.flush()
                self.event_bus.emit(CoreEvents.ERROR, {"message": err_msg})
                all_task_results.append(
                    {
                        "task_id": "workflow_compilation",
                        "status": "failure",
                        "triage_tag": "EVALUATION_INVALID",
                        "message": err_msg,
                        "metrics": [],
                        "turns_taken": 0,
                        "used_tools": [],
                        "conversation_history": [],
                    }
                )
                return all_task_results

            identity = ExecutionIdentity(
                evaluation_run_id=self.run_id,
                scenario_version_id=ExecutionIdentity.scenario_version_hash(self.scenario),
                case_id=str(self.identifier),
                attempt_id=self.attempt_id,
                attempt_number=attempt_number,
                execution_mode=self.execution_mode,
            )
            self.metadata["attempt_id"] = identity.attempt_id
            self.metadata["scenario_version_id"] = identity.scenario_version_id

            # Execution-instance-scoped context ledger.
            # Parallel branches execute against isolated sandbox forks with independent
            # conversation histories and action ledgers.
            instance_contexts: dict[str, ExecutionInstanceContext] = {}
            state_before_map: dict[str, dict[str, Any]] = {}

            async def _context_provider() -> dict[str, Any]:
                state = (
                    await sandbox.get_full_state()
                    if hasattr(sandbox, "get_full_state")
                    else getattr(sandbox, "state", {})
                )
                return {"state": state}

            async def _executor(node_ir, exec_id: str, parent_exec_id: str | None):
                node_def = node_ir.definition
                node_id_local = node_ir.node_id
                if (
                    self.cancellation_event
                    and getattr(self.cancellation_event, "is_set", lambda: False)()
                ):
                    return {
                        "task_id": node_id_local,
                        "status": "aborted",
                        "message": "Execution cancelled",
                        "turns_taken": 0,
                        "used_tools": [],
                        "conversation_history": [],
                    }

                # Isolated branch sandbox fork
                branch_sandbox = sandbox.fork(exec_id) if hasattr(sandbox, "fork") else sandbox

                # Isolated conversation and action ledger per execution instance
                branch_history: list[dict[str, Any]] = []
                if parent_exec_id and parent_exec_id in instance_contexts:
                    branch_history = copy.deepcopy(instance_contexts[parent_exec_id].history)

                branch_actions: dict[str, Any] = {"used_tools": []}

                try:
                    state_before = (
                        await branch_sandbox.get_full_state()
                        if hasattr(branch_sandbox, "get_full_state")
                        else copy.deepcopy(getattr(branch_sandbox, "state", {}))
                    )
                except Exception:  # noqa: BLE001 - evidence capture must not break execution
                    state_before = None
                if state_before is not None:
                    state_before_map[exec_id] = copy.deepcopy(state_before)

                ctx = ExecutionInstanceContext(
                    scenario_node_id=node_id_local,
                    execution_instance_id=exec_id,
                    parent_execution_id=parent_exec_id,
                    attempt_number=attempt_number,
                    identity=identity,
                    sandbox=branch_sandbox,
                    history=branch_history,
                    actions=branch_actions,
                    state_before=state_before,
                )
                instance_contexts[exec_id] = ctx

                result = await self._execute_node(
                    node_def,
                    attempt_number,
                    0,
                    branch_sandbox,
                    ctx.history,
                    ctx.actions,
                    state_before=state_before,
                    execution_context={
                        "execution_instance_id": exec_id,
                        "parent_execution_id": parent_exec_id,
                        "attempt_id": identity.attempt_id,
                        "evaluation_run_id": identity.evaluation_run_id,
                        "evaluation_plan": plan.evaluation_plan,
                    },
                )
                # [AgentV v2.0.0] Immutable join model on every task result
                result["execution_instance_id"] = exec_id
                result["parent_execution_id"] = parent_exec_id
                result["scenario_node_id"] = node_id_local
                result["evaluation_run_id"] = identity.evaluation_run_id
                result["scenario_version_id"] = identity.scenario_version_id
                result["case_id"] = identity.case_id
                result["attempt_id"] = identity.attempt_id
                result["execution_mode"] = identity.execution_mode.value

                if result.get("status") == "success":
                    ctx.turns_taken += 1

                # [E4] LIVE/HYBRID reconciliation: independently capture the
                # post-node world state and reconcile it against the node's
                # declared expectations using real observations only.
                if identity.execution_mode in (ExecutionMode.LIVE, ExecutionMode.HYBRID):
                    from .reconciliation import build_reconciliation_record

                    try:
                        state_after = (
                            await sandbox.get_full_state()
                            if hasattr(sandbox, "get_full_state")
                            else copy.deepcopy(getattr(sandbox, "state", {}))
                        )
                    except Exception:  # noqa: BLE001 - evidence capture must not break execution
                        state_after = None
                    result["reconciliation"] = build_reconciliation_record(
                        node_id=node_id_local,
                        execution_mode=identity.execution_mode.value,
                        state_before=state_before,
                        state_after=state_after,
                        expected_state_changes=node_def.get("expected_state_changes"),
                        observations={"used_tools": list(result.get("used_tools") or [])},
                    )
                    # Reconciliation evidence is instance-addressable.
                    result["reconciliation"]["execution_instance_id"] = exec_id
                    result["reconciliation"]["attempt_id"] = identity.attempt_id
                    result["reconciliation"]["scenario_node_id"] = node_id_local

                return result

            def _on_batch_complete(exec_ids: list[str]) -> None:
                """
                [F1] Deterministic post-gather state merge.
                Merges branch sandboxes in strict canonical sorted order.
                """
                merged_keys: set[str] = set()
                for eid in exec_ids:
                    ctx = instance_contexts.get(eid)
                    if (
                        ctx
                        and hasattr(sandbox, "merge_branch_state")
                        and ctx.sandbox is not sandbox
                    ):
                        before_keys = (
                            set(sandbox.state.keys())
                            if hasattr(sandbox, "state") and isinstance(sandbox.state, dict)
                            else set()
                        )
                        sandbox.merge_branch_state(ctx.sandbox)
                        after_keys = (
                            set(sandbox.state.keys())
                            if hasattr(sandbox, "state") and isinstance(sandbox.state, dict)
                            else set()
                        )
                        merged_keys.update(after_keys - before_keys)
                if self.event_bus and exec_ids:
                    self.event_bus.emit(
                        "parallel_state_merged",
                        {
                            "run_id": identity.evaluation_run_id,
                            "attempt_id": identity.attempt_id,
                            "merge_order": exec_ids,
                            "keys_affected": sorted(merged_keys),
                        },
                    )

            interpreter = WorkflowInterpreter(
                plan,
                identity,
                event_bus=_InterpreterEventBridge(self.event_bus),
                context_provider=_context_provider,
                should_abort=lambda: bool(
                    self.cancellation_event
                    and getattr(self.cancellation_event, "is_set", lambda: False)()
                ),
                on_batch_complete=_on_batch_complete,
            )

            all_task_results, outcome = await interpreter.run(_executor)
            leaf_contexts = [
                ctx
                for eid, ctx in instance_contexts.items()
                if not any(c.parent_execution_id == eid for c in instance_contexts.values())
            ]
            global_cumulative_history = (
                leaf_contexts[0].history
                if len(leaf_contexts) == 1
                else [
                    item
                    for ctx in (leaf_contexts or list(instance_contexts.values()))
                    for item in ctx.history
                ]
            )

            # 🧬 Global Evaluation Pass (Industrial AES v1.6.0)
            # Process metrics defined at the scenario level (e.g. DNA_STABLE)
            global_evaluation = self.scenario.get("evaluation", {})
            global_metrics = global_evaluation.get("metrics", [])

            verdict_payload: dict[str, Any] = {
                **outcome.to_dict(),
                "failure_policy": plan.failure_policy.value,
                "ir_version": plan.ir_version,
            }

            if global_metrics:
                print(f"      [Session] Running {len(global_metrics)} Global Evaluation Metrics...")
                global_node = {"id": "global_evaluation", "success_criteria": global_metrics}
                global_results = await self._calculate_metrics(
                    global_node,
                    attempt_number,
                    sum(tr.get("turns_taken", 0) for tr in all_task_results),
                    global_cumulative_history,
                    sandbox,
                    {
                        "used_tools": list(
                            set(t for tr in all_task_results for t in tr.get("used_tools", []))
                        )
                    },
                )
                success = all(
                    m.get("success", False) for m in global_results.get("metrics", [])
                ) and global_results.get("evaluation_valid", True)
                # Named explicitly: this status describes GLOBAL
                # metric evaluation only and must never be mistaken for the
                # authoritative workflow verdict (workflow_verdict.status).
                global_results["global_evaluation_status"] = "success" if success else "failed"
                if not success and not global_results.get("evaluation_invalid_reasons"):
                    global_results.setdefault("message", "Global evaluation metrics failed.")
                # Appended once, below, together with the synthetic host.
                verdict_target = global_results
            else:
                # Synthetic verdict host: carries ONLY authoritative
                # verdict fields. It deliberately has NO generic "status" key
                # — nothing downstream may mistake it for a task result.
                verdict_target = {
                    "task_id": "workflow_verdict",
                    "synthetic": True,
                    "metrics": [],
                    "turns_taken": 0,
                    "used_tools": [],
                    "conversation_history": [],
                }
                if not all_task_results:
                    all_task_results.append(verdict_target)

            # [AgentV v2.0.0] Verification decision tree + workflow verdict.
            # Verdict fields live ONLY on the dedicated host row —
            # never bolted onto a real node/task result.
            verdict_target["workflow_verdict"] = verdict_payload

            # Multi-judge consensus — IMPLEMENTED, never ignored.
            # When evaluation.consensus is declared the runtime executes the
            # declared panel through the authoritative LLM-judge primitive;
            # an unprovisionable panel produces an explicit evaluated=false
            # result (loud, artifact-visible) instead of a silent no-op.
            consensus_result = await self._evaluate_consensus(
                global_evaluation or {},
                global_cumulative_history,
            )
            if consensus_result is not None:
                verdict_payload["consensus"] = consensus_result

            decision = self._build_verification_decision(outcome, all_task_results, identity)
            if consensus_result is not None:
                decision["consensus"] = consensus_result
                if consensus_result.get("status") == "INCONCLUSIVE":
                    # AES guide contract: disagreement below ija_threshold
                    # must never certify — it flags human review.
                    decision["decision"] = "INCONCLUSIVE"
                    decision["because"].append(
                        "Judge panel disagreement below ija_threshold "
                        f"(agreement={consensus_result.get('agreement')}) — "
                        "human review required."
                    )
            verdict_target["verification_decision"] = decision
            all_task_results.append(verdict_target)

        except Exception as e:
            err_msg = f"Forensic Exception during node execution: {str(e)}"
            import traceback

            tb = traceback.format_exc()
            print(f"      [Fatal Exception] {err_msg}")
            print(tb)

            self.event_bus.emit(CoreEvents.ERROR, {"message": err_msg, "traceback": tb})
            # [Industrial Resilience] Do not crash the entire process for a single node failure.
            # Capture the failure in the forensic report and stop the node sequence.
            all_task_results.append(
                {
                    "task_id": node_id if node_id != "unknown" else "unknown",
                    "status": "failure",
                    "triage_tag": "FATAL_ENGINE_ERROR",
                    "message": err_msg,
                    "metrics": [],
                    "turns_taken": 0,
                    "used_tools": [],
                    "conversation_history": locals().get("history", []),
                    "traceback": tb,
                }
            )
        finally:
            # [Industrial Resilience] Ensure teardown runs even if IR compilation fails
            # or if initialization crashes before execution begins.
            await self.teardown(sandbox)

        return all_task_results

    @staticmethod
    def _last_agent_summary(history: list[dict[str, Any]]) -> str:
        for msg in reversed(history or []):
            if msg.get("role") != "agent":
                continue
            content = msg.get("content", "")
            if isinstance(content, dict):
                return str(
                    content.get("summary") or content.get("content") or content.get("message") or ""
                )
            return str(content)
        return ""

    async def _evaluate_consensus(
        self,
        evaluation_cfg: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """
        [Category A] Executable multi-judge consensus.

        Panel entries resolve through the SAME authoritative judge plumbing as
        ``luna_judge_score`` (LLMProviderFactory + config.JUDGE_PROVIDER /
        JUDGE_MODEL defaults); a panel entry may also be an explicit
        {provider, model, temperature} object. Quorum = min_judges
        successfully-executed judge votes; unprovisionable judges are recorded
        individually and NEVER replaced by silent fallbacks. An undeclared,
        unprovisionable, or unknown-strategy consensus is a loud, artifact-
        visible evaluated=false result — the runtime no-ops nothing silently.
        """
        cons = evaluation_cfg.get("consensus") or {}
        if not isinstance(cons, dict) or not cons:
            return None

        strategy = str(cons.get("strategy", "Majority_Vote"))
        min_judges = int(cons.get("min_judges", 1) or 1)
        ija_threshold = float(cons.get("ija_threshold", 0.0) or 0.0)
        raw_panel = cons.get("judge_panel") or ["default"]

        expected_message = self._primary_expected_message()
        agent_summary = self._last_agent_summary(history)

        result: dict[str, Any] = {
            "strategy": strategy,
            "min_judges": min_judges,
            "ija_threshold": ija_threshold,
            "panel": [p if isinstance(p, str) else p.get("name", str(p)) for p in raw_panel],
            "votes": [],
            "evaluated": False,
            "status": "NOT_EVALUATED",
        }

        if not expected_message:
            result["reason"] = (
                "No expected outcome available to judge against "
                "(no message-target assertion found)."
            )
            print(
                "      [Consensus] ⚠ NOT EVALUATED — declared consensus has no "
                "expected message to judge: runtime records evaluated=false."
            )
            self.event_bus.emit(
                CoreEvents.ADAPTER_DEBUG,
                {
                    "message": "Consensus declared but NOT evaluated (no expected message).",
                    "category": "CONSENSUS_NOT_EVALUATED",
                },
            )
            return result

        from .llm_providers import LLMProviderFactory

        votes: list[dict[str, Any]] = []
        metric_fn = metrics.MetricRegistry.get("luna_judge_score")

        for entry in raw_panel:
            if isinstance(entry, str):
                name, jc = entry, {}
            else:
                name = str(entry.get("name") or entry.get("provider") or "judge")
                jc = {
                    k: v
                    for k, v in entry.items()
                    if k
                    in ("judge_provider", "judge_model", "judge_temperature", "provider", "model")
                    and v is not None
                }
                # Accept shorthand provider/model keys too.
                if "provider" in jc:
                    jc["judge_provider"] = jc.pop("provider")
                if "model" in jc:
                    jc["judge_model"] = jc.pop("model")

            # Provisioning pre-check: an uncreatable provider can never vote.
            provider_name = jc.get("judge_provider") or config.JUDGE_PROVIDER
            try:
                LLMProviderFactory.create(provider_name)
            except Exception as e:
                votes.append({"judge": name, "status": "UNAVAILABLE", "error": str(e)[:200]})
                continue

            score = await metric_fn(
                {"expected_outcome": expected_message, **jc},
                agent_summary,
                dict(self.session_metadata),
            )
            votes.append({"judge": name, "status": "VOTED", "score": round(float(score), 4)})

        result["votes"] = votes
        executed = [v["score"] for v in votes if v["status"] == "VOTED"]

        if len(executed) < min_judges:
            result["reason"] = (
                f"Quorum not met: {len(executed)} judge(s) executed, "
                f"min_judges={min_judges}. Unavailable judges are never "
                "replaced by fallbacks."
            )
            print(
                f"      [Consensus] ⚠ NOT EVALUATED — quorum failed "
                f"({len(executed)}/{min_judges}); recorded as evaluated=false."
            )
            self.event_bus.emit(
                CoreEvents.ADAPTER_DEBUG,
                {
                    "message": f"Consensus quorum failed ({len(executed)}/{min_judges}).",
                    "category": "CONSENSUS_NOT_EVALUATED",
                },
            )
            return result

        result["evaluated"] = True
        pass_votes = sum(1 for s in executed if s >= 0.5)
        fail_votes = len(executed) - pass_votes
        agreement = round(1.0 - (max(executed) - min(executed)), 4)

        if strategy == "Majority_Vote":
            passed = pass_votes > fail_votes
            result["verdict"] = "PASS" if passed else "FAIL"
            result["tally"] = {"pass": pass_votes, "fail": fail_votes}
        elif strategy == "Absolute_Unanimity":
            buckets = {round(s, 2) for s in executed}
            unanimous = len(buckets) == 1 and all(s >= 0.5 for s in executed)
            result["verdict"] = "PASS" if unanimous else "INCONCLUSIVE"
            result["tally"] = {"buckets": sorted(buckets)}
        elif strategy == "Weighted_Average":
            mean = round(sum(executed) / len(executed), 4)
            result["verdict"] = "PASS" if mean >= 0.5 else "FAIL"
            result["mean_score"] = mean
        else:
            result["evaluated"] = False
            result["reason"] = (
                f"Unknown consensus strategy '{strategy}'. Supported: "
                "Majority_Vote | Absolute_Unanimity | Weighted_Average."
            )
            print(f"      [Consensus] ⚠ Unknown strategy '{strategy}' — NOT EVALUATED.")
            return result

        result["agreement"] = agreement
        if ija_threshold and agreement < ija_threshold:
            result["status"] = "INCONCLUSIVE"
            result["reason"] = (
                f"Judge agreement {agreement} < ija_threshold {ija_threshold}: "
                "certification withheld pending human review."
            )
            print(
                f"      [Consensus] ⚠ INCONCLUSIVE — agreement {agreement} < "
                f"threshold {ija_threshold}."
            )
        else:
            result["status"] = result["verdict"]

        print(
            f"      [Consensus] {result['status']} via {strategy} "
            f"(votes={len(executed)}, agreement={agreement})"
        )
        return result

    def _primary_expected_message(self) -> str:
        """Expected message from the most recent transition evidence, if any."""
        # Transition evidence lives on task results produced this attempt; the
        # verifier component keeps none globally, so scan session-level cache.
        cached = getattr(self, "_last_transition_expectations", None)
        if cached:
            return str(cached[-1])
        return ""

    @staticmethod
    def _build_verification_decision(
        outcome, results: list[dict[str, Any]], identity: ExecutionIdentity
    ) -> dict[str, Any]:
        """
        First-class 'why did this workflow pass/fail' decision tree (P1 #15):

            Scenario -> Preconditions -> Observed execution -> Expected transitions
                -> Assertions -> Policy checks -> Evidence -> Final decision
        """
        assertions: list[dict[str, Any]] = []
        because: list[str] = []
        evaluation_valid = True

        for res in results:
            nid = res.get("task_id") or res.get("scenario_node_id") or "unknown"
            res.get("status")
            for m in res.get("metrics", []):
                row = {
                    "node": nid,
                    "metric": m.get("metric"),
                    "score": m.get("score"),
                    "threshold": m.get("threshold"),
                    "passed": bool(m.get("success")),
                    "source": "success_criteria",
                }
                if m.get("status") == "EVALUATION_INVALID":
                    row["invalid"] = True
                    row["reason"] = m.get("reason")
                    evaluation_valid = False
                assertions.append(row)
            for h in res.get("state_hygiene", []):
                assertions.append(
                    {
                        "node": nid,
                        "assertion": f"hygiene:{h.get('path')}({h.get('op')})",
                        "expected": h.get("expected"),
                        "actual": h.get("actual"),
                        "passed": bool(h.get("success")),
                        "severity": h.get("severity", "required"),
                        "source": "state_hygiene",
                    }
                )
            for ev in res.get("transition_evidence", []) or []:
                a = ev.get("assertion", {})
                assertions.append(
                    {
                        "node": nid,
                        "assertion": f"{a.get('target', 'state')}"
                        + (f".{a.get('property')}" if a.get("property") else ""),
                        "mode": ev.get("mode"),
                        "expected": ev.get("expected"),
                        "actual_before": ev.get("actual_before"),
                        "actual_after": ev.get("actual_after"),
                        "passed": bool(ev.get("passed")),
                        "source": "expected_outcome",
                    }
                )

        failed_assertions = [a for a in assertions if not a["passed"]]
        invalid_assertions = [a for a in assertions if a.get("invalid")]
        required_failures = [a for a in failed_assertions if a.get("severity") != "informational"]

        if not evaluation_valid:
            decision = "EVALUATION_INVALID"
            because.extend(f"Evaluator invalid: {r.get('reason')}" for r in invalid_assertions)
        elif outcome.status == WorkflowStatus.COMPLETED and not required_failures:
            decision = "PASS"
            because.append(f"Workflow {outcome.status.value}: {outcome.reason}")
            because.append(f"All {len(assertions)} recorded assertions passed")
        else:
            decision = "FAIL"
            because.append(f"Workflow {outcome.status.value}: {outcome.reason}")
            for a in required_failures[:20]:
                src = a.get("source", "assertion")
                label = a.get("metric") or a.get("assertion") or "unnamed"
                because.append(f"{src}:{label} failed on node '{a['node']}'")

        evidence_refs = ["run.jsonl"]
        transitions = [t.to_dict() if hasattr(t, "to_dict") else t for t in outcome.transitions]
        observed = [n.to_dict() if hasattr(n, "to_dict") else n for n in outcome.node_executions]

        return {
            "decision": decision,
            "because": because,
            "preconditions": [a for a in assertions if a.get("source") == "state_hygiene"],
            "observed_execution": observed,
            "expected_transitions": transitions,
            "assertions": assertions,
            # Single-commit root over the assertion set: any change to any
            # assertion flips this hash, binding the decision to its evidence.
            "evidence_root_hash": decision_evidence_root_hash(assertions),
            "policy_checks": [],
            "evidence_refs": evidence_refs,
            "identity": {
                "evaluation_run_id": identity.evaluation_run_id,
                "scenario_version_id": identity.scenario_version_id,
                "case_id": identity.case_id,
                "attempt_id": identity.attempt_id,
                "attempt_number": identity.attempt_number,
                "execution_mode": identity.execution_mode.value,
            },
        }

    async def _execute_node(
        self,
        node: dict,
        attempt_number: int,
        turns_taken: int,
        sandbox: ToolSandbox,
        conversation_history: list[dict],
        agent_actions: dict[str, Any],
        state_before: dict[str, Any] | None = None,
        execution_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        node_id = node["id"]
        task_description = node.get("task_description", "Processing node...")
        current_message = task_description
        execution_context = execution_context or {}
        policy_cursor = len(getattr(sandbox, "policy_decisions", []))

        # 1. Forensic Maneuver Start
        print(f"      [Node Execution] ID: {node_id} | Task: {task_description[:50]}...")
        self.event_bus.emit(
            CoreEvents.MANEUVER_START,
            {"node_id": node_id, "task": task_description},
            span_context=self.session_metadata.get("span_context"),
        )

        # 2. Sequential Logic Handshake
        self.event_bus.emit(
            CoreEvents.SUBTASK_START,
            {"subtask_id": f"subtask-{node_id}", "task_description": task_description},
            span_context=self.session_metadata.get("span_context"),
        )

        # If it's a new node, we might want to refresh history or keep context?
        # AES v1.6.0 typically maintains session-scoped history.
        conversation_history.append({"role": "user", "content": current_message})

        node_success = False
        hitl_unresolved = False
        turn = 0
        for turn in range(1, self.max_turns + 1):
            if (
                self.cancellation_event
                and getattr(self.cancellation_event, "is_set", lambda: False)()
            ):
                logger.info(
                    "   [Session] Run %s aborted at turn %d due to cancellation event.",
                    self.run_id,
                    turn,
                )
                break
            self.turn_number = turn
            if config.EVAL_TURN_THROTTLE > 0:
                await asyncio.sleep(config.EVAL_TURN_THROTTLE)

            turn_ctx = TurnContext(
                task_id=node_id,
                turn_number=turn,
                current_message=current_message,
                history=list(conversation_history),
                input_payload=node.get("input_payload", {}),
                span_context=self.session_metadata.get("span_context"),
                sandbox=sandbox,
                metadata={
                    **self.session_metadata,
                    "agent_name": self.metadata.get("agent_name"),
                    "agent": self.metadata.get("agent"),
                    "protocol": self.metadata.get("protocol"),
                },
            )

            self.event_bus.emit(CoreEvents.TURN_START, {"turn": turn, "task_id": node_id})

            try:
                protocol = self.session_metadata.get("protocol", "http")
                endpoint = self.session_metadata.get("agent")

                # [Forensic Trace] Record protocol usage in the protocol sequence
                self.event_bus.emit(CoreEvents.STEP_START, {"step": protocol})

                # [Industrial Protection] Final URI string verification
                agent_response = await AgentAdapterRegistry.call_agent(
                    protocol, endpoint, turn_ctx.current_message, turn_ctx.history, turn_ctx
                )

                # [Forensic Persistence] Snapshoting state after turn completion
                full_state = await sandbox.get_full_state()
                self.forensics.snapshot_state(full_state, turn)
                self._capture_telemetry()

                if agent_response is None:
                    logger.error(f"      [Agent Error] Agent {protocol} at {endpoint} failed.")
                    raise Exception(
                        f"Authoritative Failure: Agent for {protocol} returned no payload."
                    )

                conversation_history.append(
                    {"role": "agent", "content": self._sanitize_for_history(agent_response)}
                )

                action = agent_response.get("action", "")
                if action == "call_tool":
                    await self._handle_tool_call(
                        turn, agent_response, sandbox, conversation_history, agent_actions, turn_ctx
                    )
                    current_message = self._get_last_env_message(conversation_history)
                elif action == "call_multiple_tools":
                    await self._handle_multiple_tools(
                        turn, agent_response, sandbox, conversation_history, agent_actions, turn_ctx
                    )
                    current_message = self._get_last_env_message(conversation_history)
                elif action == "hitl_pause":
                    # Human-In-The-Loop Intervention
                    human_response = await self._handle_hitl(
                        turn, agent_response, conversation_history, agent_actions, turn_ctx
                    )
                    if getattr(self, "_hitl_unresolved", False):
                        # CI/automation never fabricates a human decision.
                        # An unresolved approval is a first-class failure cause.
                        self._hitl_unresolved = False
                        node_success = False
                        hitl_unresolved = True
                        break
                    conversation_history.append({"role": "human", "content": human_response})
                    current_message = human_response
                elif action in ["final_answer", "completed"]:
                    node_success = True
                    break
                elif action == "processing":
                    # Industrial Wait-State: Continue loop if max_turns allows
                    continue
                elif action == "error":
                    # Terminal System/Business Failure
                    node_success = False
                    break
                else:
                    # [Industrial Hardening] Treat unrecognized actions as critical failures
                    err_msg = f"Unknown Agent Action: '{action}' | Protocol: {protocol}"
                    logger.error(f"      [Action Error] {err_msg}")
                    self.event_bus.emit(
                        CoreEvents.ERROR,
                        {
                            "message": err_msg,
                            "run_id": self.run_id,
                            "node_id": node.get("id", "unknown"),
                            "task_id": node.get("id", "unknown"),
                            "turn": turn,
                        },
                    )
                    node_success = False
                    break

            except Exception as e:
                err_msg = f"Agent Node Error: {str(e)}"
                self.event_bus.emit(
                    CoreEvents.ERROR,
                    {
                        "message": err_msg,
                        "run_id": self.run_id,
                        "node_id": node.get("id", "unknown"),
                        "task_id": node.get("id", "unknown"),
                        "turn": turn,
                    },
                )
                # [Industrial Resilience] Create partial results for the forensic audit
                task_results = await self._calculate_metrics(
                    node, attempt_number, turn, conversation_history, sandbox, agent_actions
                )
                task_results["status"] = "failure"
                task_results["message"] = err_msg
                return task_results

            self.event_bus.emit(CoreEvents.TURN_END, {"turn": turn, "task_id": node_id})

        # 3. Implicit Verification Phase (Transition-Based State Parity, AgentV v2.0.0)
        parity_success, parity_evidence = await self._verify_state_parity(
            node, sandbox, conversation_history, state_before=state_before
        )

        # Consensus judges need the scenario's declared expected messages;
        # collect message-target expectations as they are verified.
        if not hasattr(self, "_last_transition_expectations"):
            self._last_transition_expectations = []
        for _row in parity_evidence or []:
            _a = _row.get("assertion", {}) or {}
            if _a.get("target") == "message" and _row.get("expected") is not None:
                self._last_transition_expectations.append(_row.get("expected"))

        # Transition evidence is instance-addressable and hash-bound:
        # attempt_id + execution_instance_id + before/after content hashes.
        exec_id = execution_context.get("execution_instance_id")
        attempt_id = execution_context.get("attempt_id")
        if parity_evidence:
            state_after_for_hash = None
            try:
                state_after_for_hash = (
                    await sandbox.get_full_state()
                    if hasattr(sandbox, "get_full_state")
                    else copy.deepcopy(getattr(sandbox, "state", {}))
                )
            except Exception:  # noqa: BLE001
                state_after_for_hash = None

            def _hash_state(v: Any) -> str | None:
                if v is None:
                    return None
                return "sha3_256:" + crypto.checksum(json.dumps(v, sort_keys=True, default=str))

            for i, row in enumerate(parity_evidence):
                a = row.get("assertion", {}) or {}
                row["assertion_id"] = f"{node_id}:{i}:{a.get('target', 'message')}" + (
                    f".{a.get('property')}" if a.get("property") else ""
                )
                row["attempt_id"] = attempt_id
                row["execution_instance_id"] = exec_id
                row["state_before_hash"] = _hash_state(state_before)
                row["state_after_hash"] = _hash_state(state_after_for_hash)

        # 4. Calculation and Reporting
        task_results = await self._calculate_metrics(
            node, attempt_number, (turn), conversation_history, sandbox, agent_actions
        )

        # ------------------------------------------------------------------
        # THE authoritative NodeVerdict. Nothing downstream may infer
        # node success from the agent action alone: overall == success only
        # when every required oracle passed. Typed oracle outcomes:
        # PASS | FAIL | INVALID | NOT_APPLICABLE.
        # ------------------------------------------------------------------
        metric_rows = task_results.get("metrics") or []
        hygiene_rows = task_results.get("state_hygiene") or []
        parity_rows = parity_evidence or []
        invalid_eval = not task_results.get("evaluation_valid", True)

        def _typed_outcome(row: dict[str, Any]) -> str:
            if row.get("status") == "EVALUATION_INVALID" or row.get("invalid"):
                return "INVALID"
            if row.get("outcome") in ("PASS", "FAIL", "INVALID", "NOT_APPLICABLE"):
                return str(row.get("outcome"))
            if row.get("success") is True or row.get("passed") is True:
                return "PASS"
            if row.get("success") is False or row.get("passed") is False:
                return "FAIL"
            return "NOT_APPLICABLE"

        declared_criteria = node.get("success_criteria") or []
        declared_rules = (node.get("state_hygiene") or {}).get("rules") or []
        declared_outcomes = node.get("expected_outcome") or []

        node_oracle_results: dict[str, OracleResult] = {}

        for idx, row in enumerate(metric_rows):
            crit = (
                declared_criteria[idx]
                if idx < len(declared_criteria) and isinstance(declared_criteria[idx], dict)
                else {}
            )
            oid = str(
                crit.get("id")
                or row.get("oracle_id")
                or f"{node_id}:sc:{crit.get('metric') or row.get('metric', idx)}"
            )
            row["oracle_id"] = oid
            req = bool(crit.get("required", row.get("required", True)))
            req_level = str(
                crit.get("requiredness")
                or row.get("requiredness")
                or ("REQUIRED" if req else "OPTIONAL")
            ).upper()
            row["requiredness"] = req_level
            row["outcome"] = _typed_outcome(row)
            node_oracle_results[oid] = OracleResult(
                oracle_id=oid,
                scenario_node_id=node_id,
                resolver="metrics_calculator",
                requiredness=req_level,
                outcome=row["outcome"],
                expected=crit.get("threshold", row.get("threshold")),
                observed=row.get("score"),
                error=row.get("error"),
            )

        for idx, row in enumerate(hygiene_rows):
            rule = (
                declared_rules[idx]
                if idx < len(declared_rules) and isinstance(declared_rules[idx], dict)
                else {}
            )
            oid = str(
                rule.get("id")
                or row.get("oracle_id")
                or f"{node_id}:hygiene:{rule.get('path') or row.get('path', idx)}"
            )
            row["oracle_id"] = oid
            req = bool(rule.get("required", row.get("required", True)))
            req_level = str(
                rule.get("requiredness")
                or row.get("requiredness")
                or ("REQUIRED" if req else "OPTIONAL")
            ).upper()
            row["requiredness"] = req_level
            row["outcome"] = _typed_outcome(row)
            node_oracle_results[oid] = OracleResult(
                oracle_id=oid,
                scenario_node_id=node_id,
                resolver="state_hygiene",
                requiredness=req_level,
                outcome=row["outcome"],
                expected=rule.get("rule", row.get("rule")),
                observed=row.get("actual"),
                error=row.get("error"),
            )

        for idx, row in enumerate(parity_rows):
            assertion_dict = row.get("assertion") if isinstance(row.get("assertion"), dict) else {}
            out_decl = (
                declared_outcomes[idx]
                if idx < len(declared_outcomes) and isinstance(declared_outcomes[idx], dict)
                else {}
            )
            target_str = str(
                out_decl.get("target") or assertion_dict.get("target") or row.get("target", idx)
            )
            is_synthetic_na = target_str == "__state_parity__" or not declared_outcomes
            oid = str(
                out_decl.get("id")
                or assertion_dict.get("id")
                or row.get("oracle_id")
                or f"{node_id}:parity:{target_str}"
            )
            row["oracle_id"] = oid
            if is_synthetic_na:
                req = False
                req_level = "OPTIONAL"
            else:
                req = bool(
                    out_decl.get(
                        "required",
                        assertion_dict.get("required", row.get("required", True)),
                    )
                )
                req_level = str(
                    out_decl.get("requiredness")
                    or assertion_dict.get("requiredness")
                    or row.get("requiredness")
                    or ("REQUIRED" if req else "OPTIONAL")
                ).upper()
            row["requiredness"] = req_level
            row["outcome"] = _typed_outcome(row)
            node_oracle_results[oid] = OracleResult(
                oracle_id=oid,
                scenario_node_id=node_id,
                resolver="state_parity",
                requiredness=req_level,
                outcome=row["outcome"],
                expected=out_decl.get(
                    "expected", assertion_dict.get("expected", row.get("expected"))
                ),
                observed=row.get("actual", row.get("actual_after")),
                error=row.get("error"),
            )

        oracle_rows: list[tuple[dict[str, Any], str]] = (
            [(r, "success_criteria") for r in metric_rows]
            + [(r, "state_hygiene") for r in hygiene_rows]
            + [(r, "expected_outcome") for r in parity_rows]
        )
        outcomes = [_typed_outcome(r) for r, _ in oracle_rows]

        eval_plan: CompiledEvaluationPlan | None = execution_context.get("evaluation_plan")
        required_missing = False
        required_invalid = False
        required_failed = False
        required_pass_count = 0
        required_na_count = 0
        required_total = 0

        if eval_plan is not None:
            plan_reqs = eval_plan.required_oracles_for_node(node_id)
            required_total = len(plan_reqs)
            for req_oracle in plan_reqs:
                res = node_oracle_results.get(req_oracle.oracle_id)
                if res is None:
                    required_missing = True
                    break
                if res.outcome in ("INVALID", "NOT_EVALUATED"):
                    required_invalid = True
                elif res.outcome == "FAIL":
                    required_failed = True
                elif res.outcome == "PASS":
                    required_pass_count += 1
                elif res.outcome == "NOT_APPLICABLE":
                    if not req_oracle.definition.get("allow_not_applicable", False):
                        # Required oracle that is unjustifiably NOT_APPLICABLE yields INVALID
                        required_invalid = True
                    else:
                        required_na_count += 1
        else:
            for res in node_oracle_results.values():
                if res.requiredness == "REQUIRED":
                    required_total += 1
                    if res.outcome in ("INVALID", "NOT_EVALUATED"):
                        required_invalid = True
                    elif res.outcome == "FAIL":
                        required_failed = True
                    elif res.outcome == "PASS":
                        required_pass_count += 1
                    elif res.outcome == "NOT_APPLICABLE":
                        required_na_count += 1

        if invalid_eval or required_missing or required_invalid or "INVALID" in outcomes:
            verification = "invalid"
        elif required_failed:
            verification = "fail"
        elif required_total > 0 and required_pass_count == (required_total - required_na_count):
            verification = "pass"
        elif required_total > 0 and required_na_count == required_total:
            verification = "not_applicable"
        elif not node_oracle_results:
            verification = "not_applicable"
        elif all(
            r.outcome == "PASS"
            for r in node_oracle_results.values()
            if r.requiredness == "REQUIRED"
        ):
            verification = "pass"
        else:
            verification = "fail"

        task_results["oracle_results"] = [r.to_dict() for r in node_oracle_results.values()]

        # First-class policy assertions: every sandbox policy decision
        # taken during this node's execution attaches here; a denial gates.
        new_policy_decisions = getattr(sandbox, "policy_decisions", [])[policy_cursor:]
        denied_ids = [
            str(d.get("id")) for d in new_policy_decisions if d.get("decision") == "denied"
        ]
        if new_policy_decisions:
            task_results["policy_checks"] = copy.deepcopy(new_policy_decisions)
        policy_component = (
            "denied" if denied_ids else ("pass" if new_policy_decisions else "not_applicable")
        )

        verdict = NodeVerdict(
            execution="success" if node_success else "failed",
            verification=verification,
            policy=policy_component,
            parity="pass" if parity_success else "fail",
            failed_assertion=(
                {
                    **{k: v for k, v in first_fail[0].items() if k != "success"},
                    "source": first_fail[1],
                }
                if (
                    first_fail := next(
                        ((r, src) for r, src in oracle_rows if _typed_outcome(r) == "FAIL"),
                        None,
                    )
                )
                else None
            ),
        )
        overall = verdict.overall
        task_results["node_verdict"] = verdict.to_dict()

        # The workflow-visible status routes on overall — never on raw agent
        # completion. A failed oracle is VERIFICATION_FAILED with exact
        # evidence; an invalid evaluator is EVALUATION_INVALID.
        task_results["status"] = "success" if verdict.success else "failure"
        task_results["parity_verified"] = parity_success
        task_results["transition_evidence"] = parity_evidence
        if hitl_unresolved:
            task_results["triage_tag"] = "HITL_UNRESOLVED"
            task_results["message"] = (
                "HITL approval unresolved: no human decision was made "
                "(CI/automation must never auto-approve)."
            )
        elif overall == "verification_failed":
            task_results["triage_tag"] = "VERIFICATION_FAILED"
            fa = verdict.failed_assertion or {}
            task_results["message"] = (
                f"VERIFICATION_FAILED on node '{node_id}': assertion "
                f"'{fa.get('metric') or fa.get('assertion') or 'unnamed'}' "
                f"(source={fa.get('source')}) did not pass. "
                f"Expected: {fa.get('expected')} | Actual: {fa.get('actual')}"
            )
        elif overall == "evaluation_invalid":
            task_results["triage_tag"] = "EVALUATION_INVALID"
        elif overall == "policy_denied":
            task_results["triage_tag"] = "POLICY_DENIED"
            task_results["message"] = "Policy denial during node execution: " + ", ".join(
                denied_ids
            )
        elif overall == "parity_failed":
            task_results.setdefault(
                "message", f"State parity verification failed on node '{node_id}'."
            )

        if invalid_eval:
            task_results["triage_tag"] = "EVALUATION_INVALID"

        # [Industrial Requirement] Ensure failure context is preserved
        if not verdict.success and "err_msg" in locals() and "message" not in task_results:
            task_results["message"] = locals()["err_msg"]

        self.event_bus.emit(CoreEvents.MANEUVER_END, {"node_id": node_id})
        return task_results

    async def teardown(self, sandbox: Any):
        """
        Industrial Lifecycle Teardown.
        Ensures resources are released, listeners detached, and forensics collected.
        """
        # 1. Physical Cleanup
        await sandbox.teardown()

        # 2. Forensic Collection
        # Gather jail logs (Iteration 2 Physical Isolation)
        if hasattr(sandbox, "terminal_jail"):
            jail_log = Path(sandbox.terminal_jail) / "terminal.log"
            if jail_log.exists():
                self.forensics.register_artifact(jail_log, "terminal.log")

        self.forensics.collect()

        # 3. Lifecycle Defense: Detach Bridge & Reset Bus (Ghost Listener Prevention)
        self.event_bus.unsubscribe(self._bridge_ref)
        self.event_bus.reset()
        logger.info(f"      [Session] Hardened Teardown complete for run_id: {self.run_id}")

    async def _verify_state_parity(
        self,
        node: dict,
        sandbox: Any,
        history: list,
        state_before: dict[str, Any] | None = None,
    ) -> tuple[bool, list[dict[str, Any]]]:
        """
        Authoritative Transition-Based State Parity Verification.
        Delegates to decomposed SessionStateParityVerifier component.
        Returns (passed, transition_evidence).
        """
        return await self.state_parity_verifier.verify_state_parity(
            node, sandbox, history, state_before=state_before
        )

    async def _handle_tool_call(self, turn, agent_response, sandbox, history, actions, turn_ctx):
        tool_name = agent_response["tool_name"]
        tool_params = (
            agent_response.get("tool_params")
            or agent_response.get("parameters")
            or agent_response.get("params")
            or {}
        )

        # [Industrial Interception] Trigger mutative hook for redirection and shimming
        intercept_result = self.plugin_manager.trigger_interceptor(
            "on_tool_request", turn_ctx, tool_name, tool_params
        )

        # 1. Handle Blocking
        if intercept_result is False:
            self.event_bus.emit(
                CoreEvents.ERROR,
                {"message": f"Tool call {tool_name} blocked by plugin."},
            )
            return

        # 2. Apply Mutations (Redirection / Param Modification)
        if isinstance(intercept_result, dict):
            if "tool_name" in intercept_result:
                old_name = tool_name
                tool_name = intercept_result["tool_name"]
                logger.info(f"      [Session] Tool Redirection: {old_name} -> {tool_name}")
            if "arguments" in intercept_result:
                tool_params = intercept_result["arguments"]
                logger.info("      [Session] Tool Arguments Mutated.")

            # Short-circuit logic (Immediate result return)
            if "short_circuit_result" in intercept_result:
                result = intercept_result["short_circuit_result"]
                logger.info("      [Session] Tool Call Short-Circuited by Plugin.")
                # Record result and continue
                self._record_tool_result(
                    turn, tool_name, tool_params, result, history, actions, turn_ctx
                )
                return

        self.event_bus.emit(
            CoreEvents.TOOL_CALL,
            {"step": turn, "tool": tool_name, "arguments": tool_params},
        )
        actions["used_tools"].append(tool_name)

        self.event_bus.emit(
            CoreEvents.ACTION_START,
            {"action_type": "tool_execution", "tool": tool_name},
            span_context=turn_ctx.span_context,
        )

        result = await sandbox.execute(tool_name, tool_params)
        state_after = sandbox.state.copy()

        # O(N) Forensics: Offload state to disk snapshots
        state_after_full = await sandbox.get_full_state()
        self.forensics.snapshot_state(state_after_full, turn + 1000)

        # [Forensic Hardening] capture state fingerprint for stall detection
        self.state_snapshots.append(crypto.checksum(str(sorted(state_after.items()))))

        # [Forensic Hardening] capture resource telemetry
        self._capture_telemetry()

        self.event_bus.emit(
            CoreEvents.ACTION_END,
            {"action_type": "tool_execution", "tool": tool_name},
            span_context=turn_ctx.span_context,
        )

        self._record_tool_result(turn, tool_name, tool_params, result, history, actions, turn_ctx)

    async def _handle_multiple_tools(
        self, turn, agent_response, sandbox, history, actions, turn_ctx
    ):
        """
        Handles parallel tool execution.
        Supports both legacy 'tool_names' (empty params) and new 'tool_calls' (parameterized).
        """
        tool_calls = agent_response.get("tool_calls", [])
        if not tool_calls and "tool_names" in agent_response:
            # Legacy fallback
            tool_calls = [{"tool": tn, "params": {}} for tn in agent_response["tool_names"]]

        all_tool_results = []

        self.event_bus.emit(
            CoreEvents.ACTION_START,
            {
                "action_type": "multi_tool_execution",
                "tools": [c.get("tool") or c.get("tool_name") for c in tool_calls],
            },
            span_context=turn_ctx.span_context,
        )

        for call in tool_calls:
            tn = call.get("tool") or call.get("tool_name")
            actions["used_tools"].append(tn)

        # TRUE parallel tool execution. Independent calls (no declared
        # dependencies) run concurrently under structured concurrency; results
        # aggregate deterministically in declaration order. A call that
        # declares ``depends_on`` is deferred until its producers completed.
        async def _run_single(idx: int, call: dict[str, Any]) -> None:
            tn = call.get("tool") or call.get("tool_name")
            tp = call.get("params") or call.get("tool_params") or {}

            intercept_result = self.plugin_manager.trigger_interceptor(
                "on_tool_request", turn_ctx, tn, tp
            )

            if intercept_result is False:
                all_tool_results[idx] = {
                    "status": "blocked",
                    "message": f"Tool {tn} blocked by plugin.",
                }
                self.event_bus.emit(
                    CoreEvents.ERROR, {"message": f"Tool call {tn} blocked by plugin."}
                )
                return

            active_tn, active_params = tn, tp
            if isinstance(intercept_result, dict):
                if "tool_name" in intercept_result:
                    active_tn = intercept_result["tool_name"]
                if "arguments" in intercept_result:
                    active_params = intercept_result["arguments"]
                if "short_circuit_result" in intercept_result:
                    res = intercept_result["short_circuit_result"]
                    all_tool_results[idx] = res
                    self.event_bus.emit(
                        CoreEvents.TOOL_RESULT,
                        {"step": turn, "tool": active_tn, "result": res},
                    )
                    return

            self.event_bus.emit(
                CoreEvents.TOOL_CALL,
                {"step": turn, "tool": active_tn, "arguments": active_params},
            )
            res = await sandbox.execute(active_tn, active_params)
            all_tool_results[idx] = res
            self.event_bus.emit(
                CoreEvents.TOOL_RESULT,
                {"step": turn, "tool": active_tn, "result": res},
            )

        all_tool_results: list[Any] = [None] * len(tool_calls)
        pending_indices = set(range(len(tool_calls)))
        completed_indices: set[int] = set()
        call_ids = [c.get("id") or f"#{i}" for i, c in enumerate(tool_calls)]
        id_to_idx = {cid: i for i, cid in enumerate(call_ids)}

        while pending_indices:
            runnable = [
                i
                for i in sorted(pending_indices)
                if all(
                    id_to_idx.get(d) in completed_indices
                    for d in (tool_calls[i].get("depends_on") or [])
                )
            ]
            if not runnable:
                cycle_ids = [call_ids[i] for i in sorted(pending_indices)]
                err_msg = (
                    f"Tool dependency deadlock detected: circular or unresolved dependencies "
                    f"among calls {cycle_ids}. Failing execution (fail-closed)."
                )
                self.event_bus.emit(
                    CoreEvents.ERROR,
                    {"error_type": "DEPENDENCY_CYCLE", "message": err_msg, "calls": cycle_ids},
                )
                for i in pending_indices:
                    all_tool_results[i] = {
                        "status": "failed",
                        "error_type": "DEPENDENCY_CYCLE",
                        "message": err_msg,
                    }
                break
            await asyncio.gather(*(_run_single(i, tool_calls[i]) for i in runnable))
            pending_indices -= set(runnable)
            completed_indices |= set(runnable)

        state_after = sandbox.state.copy()

        # O(N) Forensics: Offload state to disk snapshots
        state_after_full = await sandbox.get_full_state()
        self.forensics.snapshot_state(
            state_after_full, turn + 1000
        )  # Offset for after-state transparency

        # [Forensic Hardening] capture state fingerprint for stall detection
        self.state_snapshots.append(crypto.checksum(str(sorted(state_after.items()))))

        # [Forensic Hardening] capture resource telemetry
        self._capture_telemetry()

        self.event_bus.emit(
            CoreEvents.ACTION_END,
            {
                "action_type": "multi_tool_execution",
                "tools": [c.get("tool") or c.get("tool_name") for c in tool_calls],
            },
            span_context=turn_ctx.span_context,
        )

        # Record unified environment response for multi-tool execution
        history.append({"role": "environment", "content": all_tool_results})

    async def _handle_hitl(
        self,
        turn: int,
        agent_response: dict,
        history: list,
        actions: dict,
        turn_ctx: Any,
    ) -> str:
        """
        Industrial HITL Handshake (v1.6.0).
        """
        prompt = agent_response.get("prompt", "Human intervention required.")
        """Handles Human-In-The-Loop interaction."""
        import os

        # Record the pause event for audit/forensics regardless of CI mode
        task_id = turn_ctx.task_id if turn_ctx else "unknown"
        self.event_bus.emit(CoreEvents.HITL_PAUSE, {"task_id": task_id, "prompt": prompt})

        if os.getenv("CI", "").lower() == "true":
            # A human-gated scenario can never pass without a human decision;
            # automation produces an explicit HITL_UNRESOLVED failure.
            self._hitl_unresolved = True
            response = f"[HITL_UNRESOLVED] No human decision available for: {prompt}"
            print(
                f"      [HITL] CI Mode: approval UNRESOLVED for task {task_id} "
                "(auto-approval is forbidden)"
            )
            return response

        import sys

        if sys.stdin.isatty():
            # Interactive terminal: read from stdin directly
            print(f"\n      [HITL] Human intervention required for task '{task_id}'")
            print(f"      Prompt: {prompt}")
            print("      Enter response (or 'exit' to abort): ", end="", flush=True)
            human_input = input()
            if human_input.lower() == "exit":
                raise InterruptedError(f"Human operator aborted task '{task_id}'")
            self.event_bus.emit(
                CoreEvents.HITL_RESUME, {"task_id": task_id, "response": human_input}
            )
            return human_input

        # Non-interactive mode (no TTY): suspend into registry for GUI/API resolution
        if not sys.stdin.isatty() and (
            "pytest" not in sys.modules or os.environ.get("FORCE_HITL_SUSPEND")
        ):
            # 1. Snapshot checkpoint before entering approval wait loop
            hist = (
                self.turn_state_manager.history
                if hasattr(self.turn_state_manager, "history")
                else []
            )
            chk_state = {
                "turn": self.turn_number,
                "task_id": task_id,
                "prompt": prompt,
                "history": hist,
                "sandbox_state": getattr(getattr(self, "sandbox", None), "state", {}),
            }

            chk_id = self.checkpoint_manager.create_checkpoint(
                state=chk_state,
                metadata={"task_id": task_id, "status": "HITL_PENDING"},
            )

            # 2. Use self.approval_manager to coordinate approval gate
            approval = self.approval_manager.request_approval(
                task_id=task_id,
                tool_name="human_intervention",
                params={"prompt": prompt, "checkpoint_id": chk_id},
            )

            # Await the approvals queue wait loop (which runs in an executor thread)
            await approval.wait()

            if approval.action == "reject":
                self.event_bus.emit(
                    CoreEvents.HITL_RESUME, {"task_id": task_id, "response": "[REJECTED]"}
                )
                raise InterruptedError(
                    f"Human reviewer rejected task '{task_id}': {approval.response}"
                )

            self.event_bus.emit(
                CoreEvents.HITL_RESUME, {"task_id": task_id, "response": approval.response}
            )
            return approval.response

        # Non-interactive without GUI (e.g. piped stdin in test): return informative message
        response = f"Skipped (non-interactive, no TTY): {prompt}"
        self.event_bus.emit(CoreEvents.HITL_RESUME, {"task_id": task_id, "response": response})
        return response

    def _record_tool_result(self, turn, tool_name, tool_params, result, history, actions, turn_ctx):
        """Unified helper to record tool results across single and short-circuited paths."""
        self.event_bus.emit(
            CoreEvents.TOOL_RESULT,
            {"step": turn, "tool": tool_name, "result": result},
            span_context=turn_ctx.span_context,
        )

        history.append(
            {
                "role": "environment",
                "content": self._sanitize_for_history(result),
            }
        )
        self.plugin_manager.trigger("on_tool_result", turn_ctx, tool_name, result)

    def _get_last_env_message(self, history):
        if not history:
            return ""
        last = history[-1]
        if last["role"] == "environment":
            content = last["content"]
            if isinstance(content, list):
                return f"Tools returned: {json.dumps(content)}"
            if isinstance(content, dict):
                return content.get("message") or content.get("content") or str(content)
            return str(content)
        return ""

    async def _calculate_metrics(self, node, attempt_number, turns, history, sandbox, actions):
        """
        Calculates task metrics and evaluates state hygiene pre-conditions.
        Delegates to decomposed SessionMetricsCalculator component.
        """
        return await self.metrics_calculator.calculate_metrics(
            node, attempt_number, turns, history, sandbox, actions
        )

    def _extract_agent_summary(self, history):
        """Extracts the latest agent text summary from conversation history."""
        return SessionMetricsCalculator.extract_agent_summary(history)

    async def _get_shim_snapshots(
        self, sandbox: ToolSandbox, shim_ids: list[str]
    ) -> dict[str, Any]:
        """Queries active simulators for point-in-time state snapshots."""
        return await self.state_parity_verifier.get_shim_snapshots(sandbox, shim_ids)

    def _sanitize_for_history(self, obj: Any) -> Any:
        """Coerces objects (especially Mocks) into plain serializable types for history safety."""
        from .trace_utils import AESJsonEncoder

        encoder = AESJsonEncoder()

        if isinstance(obj, dict):
            return {str(k): self._sanitize_for_history(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._sanitize_for_history(i) for i in obj]
        elif isinstance(obj, str | int | float | bool | None):
            return obj

        try:
            # Leverage the specialized encoder's default logic for leaf values
            return encoder.default(obj)
        except TypeError:
            # Fallback to string representation for anything else
            return str(obj)

    # Research fork: creates a shallow session clone. Note the
    # sandbox deep-copy and history partitioning are NOT implemented here
    # — true trajectory reproduction waits for P2.1 per-execution-isolation.
    def fork(self, history: list[dict[str, Any]], sandbox_state: dict[str, Any]) -> SessionManager:
        if getattr(self, "fork_depth", 0) >= MAX_FORK_DEPTH:
            raise RuntimeError(f"Fork Bomb Prevention: Maximum depth ({MAX_FORK_DEPTH}) reached.")
        scenario_copy = copy.deepcopy(self.scenario)
        scenario_copy["_fork_depth"] = getattr(self, "fork_depth", 0) + 1
        new_session = SessionManager(self.run_id, scenario_copy)
        print(f"   [Session] Forking trajectory with {len(history)} messages in history.")
        return new_session

    def _extract_tool_registry(self) -> dict[str, Any]:
        """Extracts tool names and parameter keys from scenario for forensic validation."""
        registry = {}
        tool_defs = self.scenario.get("tools", {})
        for name, defn in tool_defs.items():
            # Initial Depth: Focus on name and top-level parameter keys
            # Supporting 'expected_params' or scanning 'output_logic' if present
            params = defn.get("expected_params", [])
            # Fallback: scan scenario's use of this tool in other nodes to infer params?
            # Better: assume tools define their expected schema in 'parameters' or similar
            if not params and "parameters" in defn:
                params = list(defn["parameters"].keys())

            registry[name] = {"parameters": params}
        return registry

    def _capture_telemetry(self):
        """Captures hardware resource metrics for forensic gradient analysis."""
        if not psutil:
            return

        try:
            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()

            # Simplified Telemetry Packet (Enterprise-Ready)
            metrics = {
                "timestamp": time.time(),
                "cpu_percent": process.cpu_percent(),
                "rss_mb": mem_info.rss / (1024 * 1024),
                "vms_mb": mem_info.vms / (1024 * 1024),
                "disk_usage_percent": psutil.disk_usage(os.getcwd()).percent,
            }
            self.resource_telemetry.append(metrics)

            # [Forensic Sidecar] Export to CSV for industrial audit
            # Standard: Appends current turn telemetry to the pre-initialized CSV.
            telemetry_path = self.forensics.target_dir / "telemetry.csv"
            with open(telemetry_path, "a", encoding="utf-8") as f:
                f.write(",".join(str(v) for v in metrics.values()) + "\n")
        except Exception as e:
            logger.warning(f"   [Session] Telemetry capture failed: {e}")


# Public Session alias
Session = SessionManager


class _InterpreterEventBridge:
    """Adapts WorkflowInterpreter emissions onto the session EventEmitter."""

    def __init__(self, bus: Any):
        self._bus = bus

    def emit(self, name: Any, data: dict[str, Any]) -> None:
        try:
            self._bus.emit(name, data)
        except Exception:  # noqa: BLE001 - telemetry must never break execution
            logger.debug("Interpreter event emission failed for %s", name, exc_info=True)
