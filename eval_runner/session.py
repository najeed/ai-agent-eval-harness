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
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

try:
    import psutil  # Forensic telemetry fallback
except ImportError:
    psutil = None

logger = logging.getLogger(__name__)

from . import config, events, metrics  # noqa: E402
from .context import TurnContext  # noqa: E402
from .engine import AgentAdapterRegistry  # noqa: E402
from .events import CoreEvents, Event, EventEmitter  # noqa: E402
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

# Security Guardrails: Fork Bomb Prevention
MAX_FORK_DEPTH = config.MAX_FORK_DEPTH
MAX_FORK_BREADTH = config.MAX_FORK_BREADTH


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
        from graphlib import CycleError, TopologicalSorter

        all_task_results = []
        global_cumulative_history = []

        # 🚀 Move Sandbox into the forensic recovery block
        sandbox = ToolSandbox(
            self.scenario,
            event_bus=self.event_bus,
            forensics=self.forensics,
            plugin_manager=self.plugin_manager,
            jail_root=(self.log_root / self.run_id / "terminal_jail").resolve(),
            policy_evaluator=self.policy_evaluator,
        )
        try:
            await sandbox.setup()
            workflow = self.scenario.get("workflow", {})
            if isinstance(workflow, list):
                nodes_data = {
                    node["id"]: node for node in workflow if isinstance(node, dict) and "id" in node
                }
                workflow_edges = []
            elif isinstance(workflow, dict):
                nodes_data = {
                    node["id"]: node
                    for node in workflow.get("nodes", [])
                    if isinstance(node, dict) and "id" in node
                }
                workflow_edges = workflow.get("edges", [])
            else:
                nodes_data = {}
                workflow_edges = []

            # 1. Topologically Sort Execution Graph
            from graphlib import CycleError, TopologicalSorter

            ts = TopologicalSorter()
            for node_id in nodes_data:
                ts.add(node_id)

            for edge in workflow_edges:
                src = edge.get("from")
                trg = edge.get("to")
                if src and trg:
                    ts.add(trg, src)

            # 2. Sequential State Initialization
            turns_taken = 0
            history = []
            actions = {"used_tools": []}

            # 🚀 Topological Sorting Complete. Proceeding to execution dispatch.
            try:
                execution_order = list(ts.static_order())
            except CycleError:
                err_msg = (
                    f"Industrial Shield Block: Cyclic dependencies detected in "
                    f"workflow DAG for {self.run_id}."
                )
                sys.stderr.write(f"      [Cycle Error] {err_msg}\n")
                sys.stderr.flush()
                self.event_bus.emit(CoreEvents.ERROR, {"message": err_msg})
                raise ValueError(err_msg) from None

            # Check for empty topology explicitly to fail-fast
            if not execution_order:
                err_msg = f"Industrial Fail-Fast (v1.4.0): Empty Topology for Run {self.run_id}."
                sys.stderr.write(f"      [FATAL] {err_msg}\n")
                sys.stderr.flush()
                raise ValueError(err_msg)

            for node_id in execution_order:
                if (
                    self.cancellation_event
                    and getattr(self.cancellation_event, "is_set", lambda: False)()
                ):
                    all_task_results.append(
                        {
                            "task_id": node_id,
                            "status": "aborted",
                            "message": "Execution cancelled",
                            "turns_taken": turns_taken,
                            "used_tools": [],
                            "conversation_history": history,
                        }
                    )
                    break

                node = nodes_data.get(node_id)
                if not node:
                    continue

                task_res = await self._execute_node(
                    node, attempt_number, turns_taken, sandbox, history, actions
                )

                if task_res.get("status") == "success":
                    turns_taken += 1
                    all_task_results.append(task_res)
                else:
                    print(f"      [Node Failure] {node_id}: {task_res.get('message')}")
                    all_task_results.append(task_res)
                    break

            # 🚀 All nodes executed. Global history is now fully captured in 'history'.
            global_cumulative_history = list(history)
            # 🧬 Global Evaluation Pass (Industrial AES v1.6.0)
            # Process metrics defined at the scenario level (e.g. DNA_STABLE)
            global_evaluation = self.scenario.get("evaluation", {})
            global_metrics = global_evaluation.get("metrics", [])

            if global_metrics:
                print(f"      [Session] Running {len(global_metrics)} Global Evaluation Metrics...")
                # We treat the run summary as a pseudo-node for metric evaluation
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
                success = all(m.get("success") for m in global_results.get("metrics", []))
                global_results["status"] = "success" if success else "failed"
                all_task_results.append(global_results)

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
                    "task_id": node_id if "node_id" in locals() else "unknown",
                    "status": "failure",
                    "triage_tag": "FATAL_ENGINE_ERROR",
                    "message": err_msg,
                    "metrics": [],
                    "turns_taken": 0,
                    "used_tools": [],
                    "conversation_history": history if "history" in locals() else [],
                    "traceback": tb,
                }
            )
        finally:
            # [Industrial Resilience] Ensure teardown runs even if topological sort fails
            # or if initialization crashes before execution begins.
            await self.teardown(sandbox)

        return all_task_results

    async def _execute_node(
        self,
        node: dict,
        attempt_number: int,
        turns_taken: int,
        sandbox: ToolSandbox,
        conversation_history: list[dict],
        agent_actions: dict[str, Any],
    ) -> dict[str, Any]:
        node_id = node["id"]
        task_description = node.get("task_description", "Processing node...")
        current_message = task_description

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
        start_turn = (
            self.turn_number + 1 if hasattr(self, "turn_number") and self.turn_number > 0 else 1
        )
        for turn in range(start_turn, self.max_turns + 1):
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

        # 3. Implicit Verification Phase (Industrial State Parity)
        parity_success = await self._verify_state_parity(node, sandbox, conversation_history)
        if not parity_success:
            node_success = False
            logger.info(
                f"      [Session] [Parity-Audit] Failure: Node {node_id} state parity check failed."
            )

        # 4. Calculation and Reporting
        task_results = await self._calculate_metrics(
            node, attempt_number, (turn), conversation_history, sandbox, agent_actions
        )
        task_results["status"] = "success" if node_success else "failure"
        task_results["parity_verified"] = parity_success

        # [Industrial Requirement] Ensure failure context is preserved
        if not node_success and "err_msg" in locals():
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

    async def _verify_state_parity(self, node: dict, sandbox: Any, history: list) -> bool:
        """
        Authoritative State Parity Verification.
        Delegates to decomposed SessionStateParityVerifier component.
        """
        return await self.state_parity_verifier.verify_state_parity(node, sandbox, history)

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
            tp = call.get("params") or call.get("tool_params") or {}

            actions["used_tools"].append(tn)

            # [Industrial Interception] Per-tool mutation support
            intercept_result = self.plugin_manager.trigger_interceptor(
                "on_tool_request", turn_ctx, tn, tp
            )

            # 1. Handle Blocking
            if intercept_result is False:
                res = {"status": "blocked", "message": f"Tool {tn} blocked by plugin."}
                all_tool_results.append(res)
                self.event_bus.emit(
                    CoreEvents.ERROR, {"message": f"Tool call {tn} blocked by plugin."}
                )
                continue

            active_tn = tn
            active_params = tp

            # 2. Apply Mutations
            if isinstance(intercept_result, dict):
                if "tool_name" in intercept_result:
                    active_tn = intercept_result["tool_name"]
                if "arguments" in intercept_result:
                    active_params = intercept_result["arguments"]

                if "short_circuit_result" in intercept_result:
                    res = intercept_result["short_circuit_result"]
                    all_tool_results.append(res)
                    self.event_bus.emit(
                        CoreEvents.TOOL_RESULT, {"step": turn, "tool": active_tn, "result": res}
                    )
                    continue

            self.event_bus.emit(
                CoreEvents.TOOL_CALL, {"step": turn, "tool": active_tn, "arguments": active_params}
            )

            res = await sandbox.execute(active_tn, active_params)
            all_tool_results.append(res)
            self.event_bus.emit(
                CoreEvents.TOOL_RESULT,
                {"step": turn, "tool": active_tn, "result": res},
            )

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
            response = f"Auto-approved (CI-Override): {prompt}"
            self.event_bus.emit(CoreEvents.HITL_RESUME, {"task_id": task_id, "response": response})
            print(f"      [HITL] CI Mode: Auto-approving task {task_id}")
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
        if not sys.stdin.isatty() and "pytest" not in sys.modules:
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
                "sandbox_state": getattr(self.sandbox, "state", {}),
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

    def fork(self, history: list[dict[str, Any]], sandbox_state: dict[str, Any]) -> SessionManager:
        """
        Creates a clone of the current session at a specific checkpoint.
        Supports research into non-linear trajectories.
        """
        if getattr(self, "fork_depth", 0) >= MAX_FORK_DEPTH:
            raise RuntimeError(f"Fork Bomb Prevention: Maximum depth ({MAX_FORK_DEPTH}) reached.")
        scenario_copy = copy.deepcopy(self.scenario)
        scenario_copy["_fork_depth"] = getattr(self, "fork_depth", 0) + 1
        new_session = SessionManager(self.run_id, scenario_copy)
        # Note: In a full implementation, we'd need to deep copy the sandbox
        # and ensure the conversation history is properly partitioned.
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
