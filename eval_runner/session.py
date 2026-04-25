"""
session.py

Manages the state and trajectory of an evaluation session.
Handles conversation history, tool results, and plugin interception.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
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
from .tool_sandbox import ToolSandbox  # noqa: E402
from .utils.path_resolver import PathResolver  # noqa: E402

# Security Guardrails: Fork Bomb Prevention
MAX_FORK_DEPTH = config.MAX_FORK_DEPTH
MAX_FORK_BREADTH = config.MAX_FORK_BREADTH


class SessionManager:
    """
    Manages a single evaluation attempt's lifecycle.
    Updated for Session-Scoped Lifecycle (Inversion of Control).
    """

    def __init__(self, run_id: str, scenario: dict, metadata: dict | None = None):
        from .plugins import PluginManager

        self.run_id = run_id
        # [Forensic Isolation] Ensure parallel runs don't mutate shared scenario state
        self.scenario = copy.deepcopy(scenario)
        # Authoritatively inject run_id for downstream forensic affinity (e.g., ToolSandbox)
        self.scenario["run_id"] = run_id

        # [AgentV v1.5.0] Authoritative Metadata Propagation (Ensured mutable)
        self.metadata = dict(metadata or {})
        # Centralized identifier (resolved and normalized in Loader)
        self.identifier = scenario["id"]

        # [AgentV v1.5.0] Authoritative Metadata Discovery
        self.session_metadata = {
            "protocol": "http",
            "agent": None,
            "identifier": self.identifier,
            "span_context": self.metadata.get("span_context"),
        }
        if metadata:
            self.session_metadata.update(metadata)

        self.max_turns = int(scenario.get("max_turns", config.EVAL_MAX_TURNS)) or 10
        self.fork_depth = scenario.get("_fork_depth", 0)

        # Identity Propagation (v1.4.1 Hardening)
        # Allows external tools/plugins to align artifacts with the session identity.
        os.environ["AES_RUN_ID"] = run_id
        os.environ["AES_IDENTIFIER"] = self.identifier

        # Session-Scoped Infrastructure
        self.event_bus = EventEmitter(run_id=run_id)
        # [Telemetry Bridge] Propagate events to global subscribers
        if not self.metadata.get("isolate_events", False):
            self.event_bus.subscribe(lambda e: events.emit(e.name, e.data, e.span_context))

        self.plugin_manager = PluginManager()
        self.forensics = ForensicCollector(run_id, config.RUN_LOG_DIR / run_id)

        # [Industrial Persistence] Save ORIGINAL scenario baseline
        run_vault = config.RUN_LOG_DIR / run_id
        run_vault.mkdir(parents=True, exist_ok=True)
        with open(run_vault / "scenario_original.json", "w", encoding="utf-8") as f:
            json.dump(self.scenario, f, indent=2)

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

        # [AES v1.4.1] Dynamic Metric Discovery
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

        # 🚀 [AES v1.4.1] Authoritative Routing Resolution
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
        self.metadata["protocol"] = self.session_metadata.get("protocol", "http")

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
        with open(run_vault / "scenario_resolved.json", "w", encoding="utf-8") as f:
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

    async def execute_tasks(self, attempt_number: int) -> list[dict[str, Any]]:
        from graphlib import CycleError, TopologicalSorter

        all_task_results = []
        global_cumulative_history = []

        # 🚀 Move Sandbox into the forensic recovery block
        sandbox = ToolSandbox(self.scenario, event_bus=self.event_bus, forensics=self.forensics)
        await sandbox.setup()
        workflow = self.scenario.get("workflow", {})
        nodes_data = {node["id"]: node for node in workflow.get("nodes", [])}

        # 1. Build Dependency Graph (Industrial AES v1.4)
        print(f"      [Forensic Debug] Building Graph for {len(nodes_data)} nodes...")
        self.event_bus.emit(
            CoreEvents.PHASE_START,
            {"phase": "workflow_sort"},
            span_context=self.session_metadata.get("span_context"),
        )

        ts = TopologicalSorter()
        for node_id in nodes_data:
            ts.add(node_id)

        for edge in workflow.get("edges", []):
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

        try:
            for node_id in execution_order:
                node = nodes_data.get(node_id)
                if not node:
                    continue

                task_res = await self._execute_node(
                    node, attempt_number, turns_taken, sandbox, history, actions
                )
                global_cumulative_history.extend(history)

                if task_res.get("status") == "success":
                    turns_taken += 1
                    all_task_results.append(task_res)
                else:
                    print(f"      [Node Failure] {node_id}: {task_res.get('message')}")
                    all_task_results.append(task_res)
                    break

        except Exception as e:
            err_msg = f"Forensic Exception during node execution: {str(e)}"
            print(f"      [Fatal Exception] {err_msg}")
            import traceback

            print(traceback.format_exc())
            self.event_bus.emit(CoreEvents.ERROR, {"message": err_msg})
            # [Industrial Resilience] Do not crash the entire process for a single node failure.
            # Capture the failure in the forensic report and stop the node sequence.
            all_task_results.append(
                {
                    "task_id": node_id if "node_id" in locals() else "unknown",
                    "status": "failure",
                    "message": err_msg,
                }
            )
        finally:
            await self.teardown(sandbox)

        # 🧬 Global Evaluation Pass (Industrial AES v1.4.1)
        # Process metrics defined at the scenario level (e.g. DNA_STABLE)
        global_evaluation = self.scenario.get("evaluation", {})
        global_metrics = global_evaluation.get("metrics", [])

        if global_metrics:
            print(f"      [Session] Running {len(global_metrics)} Global Evaluation Metrics...")
            # We treat the run summary as a pseudo-node for metric evaluation
            global_node = {"id": "global_evaluation", "success_criteria": global_metrics}

            global_results = await self._calculate_metrics(
                global_node,
                1,
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
        # AES v1.4.1 typically maintains session-scoped history.
        conversation_history.append({"role": "user", "content": current_message})

        node_success = False
        for turn in range(1, self.max_turns + 1):
            if config.EVAL_TURN_THROTTLE > 0:
                await asyncio.sleep(config.EVAL_TURN_THROTTLE)

            turn_ctx = TurnContext(
                task_id=node_id,
                turn_number=turn,
                current_message=current_message,
                history=list(conversation_history),
                input_payload=node.get("input_payload", {}),
                span_context=self.session_metadata.get("span_context"),
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
                else:
                    # Treat unrecognized actions as implicit terminal states for safety
                    node_success = True  # Assume success if agent finished with unknown terminal
                    break

            except Exception as e:
                err_msg = f"Agent Node Error: {str(e)}"
                self.event_bus.emit(CoreEvents.ERROR, {"message": err_msg})
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
        Queries simulators/shims for point-in-time snapshots and validates assertions.
        Includes industrial retry logic for asynchronous state propagation.
        """
        assertions = node.get("expected_outcome", [])
        if not isinstance(assertions, list) or not assertions:
            return True

        # 1. Industrial Polling Configuration
        # Respect node-level timeout or default to 30s
        timeout = float(node.get("timeout", 30))
        interval = 2.0  # Standard Industrial Interval
        start_time = asyncio.get_event_loop().time()

        logger.info(
            f"      [Session] Starting Implicit Verification Phase "
            f"({len(assertions)} assertions) | Timeout: {timeout}s"
        )

        shim_ids = list(
            {
                a.get("target").split(":", 1)[1].split(".", 1)[0]
                for a in assertions
                if str(a.get("target")).startswith("shim:")
            }
        )

        import re

        while True:
            shim_snapshots = await self._get_shim_snapshots(sandbox, shim_ids)
            all_passed = True
            failed_reason = None

            for assertion in assertions:
                target = assertion.get("target", "message")
                expected = assertion.get("expected")
                property_path = assertion.get("property")
                mode = assertion.get("mode", "exact")

                if target.startswith("shim:"):
                    # [Industrial Resolve] Support combined shim:id.path syntax
                    raw_target = target.split(":", 1)[1]
                    if "." in raw_target:
                        shim_id = raw_target.split(".", 1)[0]
                        # Use everything after the first dot as the property path extension
                        property_path_ext = raw_target.split(".", 1)[1]
                        actual_val = shim_snapshots.get(shim_id)
                        if property_path:
                            property_path = f"{property_path_ext}.{property_path}"
                        else:
                            property_path = property_path_ext
                    else:
                        shim_id = raw_target
                        actual_val = shim_snapshots.get(shim_id)
                elif target == "message":
                    actual_val = self._extract_agent_summary(history)
                elif target == "state":
                    actual_val = await sandbox.get_full_state()
                else:
                    logger.warning(
                        f"      [Session] [Parity] Unsupported assertion target: {target}"
                    )
                    all_passed = False
                    failed_reason = f"Unsupported target: {target}"
                    break

                # Resolve property in snapshot/message using Unified Resolver
                if property_path:
                    actual_val = PathResolver.resolve(actual_val, property_path)

                # Comparison Logic
                match = False
                if mode == "exact":
                    match = actual_val == expected
                elif mode == "regex" or (
                    isinstance(expected, str) and expected.startswith("regex:")
                ):
                    pattern = (
                        str(expected)[6:] if str(expected).startswith("regex:") else str(expected)
                    )
                    match = bool(re.search(pattern, str(actual_val), re.IGNORECASE))
                elif mode == "numerical_tolerance":
                    try:
                        match = abs(float(actual_val) - float(expected)) < 1e-9
                    except (ValueError, TypeError):
                        match = False

                if not match:
                    all_passed = False
                    failed_reason = (
                        f"{target}.{property_path or ''} | "
                        f"Expected: {expected} | Actual: {actual_val}"
                    )
                    break  # Optimization: Retry on first failure

            if all_passed:
                logger.info(f"      [Session] [Parity] All {len(assertions)} assertions PASSED.")
                return True

            # Check for timeout
            if asyncio.get_event_loop().time() - start_time > timeout:
                logger.info(
                    f"      [Session] [Parity-Audit] TIMEOUT reached. Last failure: {failed_reason}"
                )

                # [Forensics] Broadcast divergence for auditability & automated triage
                self.event_bus.emit(
                    CoreEvents.ADAPTER_DEBUG,
                    {
                        "message": f"Parity FAILED after {timeout}s: {failed_reason}",
                        "category": "PARITY_STATE_DIVERGENCE",
                        "is_root_cause": True,
                    },
                )
                return False

            await asyncio.sleep(interval)

    async def _handle_tool_call(self, turn, agent_response, sandbox, history, actions, turn_ctx):
        tool_name = agent_response["tool_name"]
        tool_params = agent_response.get("tool_params", {})

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
        self.state_snapshots.append(
            hashlib.sha256(str(sorted(state_after.items())).encode()).hexdigest()
        )

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
        tool_names = agent_response["tool_names"]
        actions["used_tools"].extend(tool_names)

        all_tool_results = []

        for tn in tool_names:
            # [Industrial Interception] Per-tool mutation support
            intercept_result = self.plugin_manager.trigger_interceptor(
                "on_tool_request", turn_ctx, tn, {}
            )

            # 1. Handle Blocking
            if intercept_result is False:
                all_tool_results.append(
                    {"status": "blocked", "message": f"Tool {tn} blocked by plugin."}
                )
                self.event_bus.emit(
                    CoreEvents.ERROR, {"message": f"Tool call {tn} blocked by plugin."}
                )
                continue

            active_tn = tn
            active_params = {}

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
        # ... rest of the logic ...

        # O(N) Forensics: Offload state to disk snapshots
        state_after_full = await sandbox.get_full_state()
        self.forensics.snapshot_state(
            state_after_full, turn + 1000
        )  # Offset for after-state transparency

        # [Forensic Hardening] capture state fingerprint for stall detection
        self.state_snapshots.append(
            hashlib.sha256(str(sorted(state_after.items())).encode()).hexdigest()
        )

        # [Forensic Hardening] capture resource telemetry
        self._capture_telemetry()

        history.append(
            {
                "role": "environment",
                "content": all_tool_results,
            }
        )

    async def _handle_hitl(
        self,
        turn: int,
        agent_response: dict,
        history: list,
        actions: dict,
        turn_ctx: Any,
    ) -> str:
        """
        Industrial HITL Handshake (v1.5.0).
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

        # Standard interactive input

        # Check if we are in a TTY or have a way to get input
        import sys

        if sys.stdin.isatty():
            print(f"\n      [HITL] Agent is requesting intervention for task '{task_id}':")
            print(f"      > {prompt}")
            response = input("      Enter response (or 'exit' to abort): ").strip()
            if response.lower() == "exit":
                raise InterruptedError("User aborted evaluation.")
            self.event_bus.emit(CoreEvents.HITL_RESUME, {"task_id": task_id, "response": response})
            return response
        else:
            summary = prompt[:50] + "..." if len(prompt) > 50 else prompt
            response = (
                f"[Simulation] Interaction for '{summary}' acknowledged in non-interactive mode."
            )
            self.event_bus.emit(CoreEvents.HITL_RESUME, {"task_id": task_id, "response": response})
            print(f"      [HITL] Non-interactive environment: {response}")
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
            return content.get("message") or content.get("content") or str(content)
        return ""

    async def _calculate_metrics(self, node, attempt_number, turns, history, sandbox, actions):
        node_id = node.get("id")
        results = {
            "task_id": node_id,
            "attempt": attempt_number,
            "turns_taken": turns,
            "conversation_history": history,
            "metrics": [],
            "protocol_sequence": list(self.protocol_sequence),
            "state_snapshots": list(self.state_snapshots),
            "resource_telemetry": list(self.resource_telemetry),
            "tool_registry": self._extract_tool_registry(),
        }

        # v1.2 Hardened Metrics: Pre-condition check (State Hygiene)
        sh = node.get("state_hygiene", {})
        if sh:
            self.event_bus.emit(
                CoreEvents.STEP_START,
                {"step_name": "state_hygiene_check"},
                span_context=self.session_metadata.get("span_context"),
            )
            from .utils.path_resolver import PathResolver

            hygiene_results = []
            for rule in sh.get("rules", []):
                path = rule.get("path")
                expected = rule.get("expected")
                op = rule.get("op", "eq")  # eq, exists, not_exists, contains

                # Resolve nested path using Unified Resolver
                val = PathResolver.resolve(sandbox.state, path)

                success = False
                if op == "eq":
                    success = val == expected
                elif op == "exists":
                    success = val is not None
                elif op == "not_exists":
                    success = val is None
                elif op == "contains":
                    success = expected in val if val else False

                hygiene_results.append({"path": path, "op": op, "success": success})

            # Record hygiene as a meta-metric or log it
            if hygiene_results:
                results["state_hygiene"] = hygiene_results
            self.event_bus.emit(
                CoreEvents.STEP_END,
                {"step_name": "state_hygiene_check"},
                span_context=self.session_metadata.get("span_context"),
            )

        # --- [AES v1.4.1] Forensic Performance Evaluation ---
        # We exclusively iterate through declared success_criteria.
        criteria = node.get("success_criteria", [])
        expected_outcome = node.get("expected_outcome")

        for criterion in criteria:
            try:
                m_name = criterion.get("metric")
                threshold = criterion.get("threshold", 1.0)
                metric_func = metrics.MetricRegistry.get(m_name)

                if not metric_func:
                    logger.warning(f"   [Session] Warning: Metric '{m_name}' not found. Skipping.")
                    continue

                # Prepare standard evaluation context
                summary = self._extract_agent_summary(history)

                # Dynamic Dispatch Context
                # [Industrial Hardening] Pure Assertion Model: find the primary message baseline
                eval_context = criterion.copy()
                if "expected" not in eval_context and isinstance(expected_outcome, list):
                    primary_msg = next(
                        (a["expected"] for a in expected_outcome if a.get("target") == "message"),
                        None,
                    )
                    eval_context["expected"] = primary_msg

                async def _invoke(func, *args):
                    import inspect

                    if inspect.iscoroutinefunction(func):
                        return await func(*args)
                    return func(*args)

                # Specialized Metric handling (Minimal set for architectural requirements)
                if m_name == "tool_call_correctness":
                    score = await _invoke(
                        metric_func, node.get("required_tools", []), actions["used_tools"]
                    )
                elif m_name == "state_verification":
                    score = await _invoke(
                        metric_func, node.get("expected_state_changes", []), sandbox.state
                    )
                elif m_name == "policy_compliance":
                    score = await _invoke(metric_func, history)
                else:
                    # Generic Metric: (config_dict, stimulus_text)
                    score = await _invoke(metric_func, eval_context, summary)

                results["metrics"].append(
                    {
                        "metric": m_name,
                        "score": score,
                        "threshold": threshold,
                        "success": score >= threshold,
                    }
                )
                self.event_bus.emit(
                    CoreEvents.ADAPTER_DEBUG,
                    {"message": f"[Metric] {m_name}: {score:.2f} (Threshold: {threshold})"},
                )
            except Exception as e:
                print(f"      [Metric Error] {node_id}: {e}")

        return results

    def _extract_agent_summary(self, history):
        agent_msgs = [m for m in history if m["role"] == "agent"]
        if not agent_msgs:
            return ""
        last_content = agent_msgs[-1].get("content", "")
        if isinstance(last_content, dict):
            # Try to find a meaningful string across common fields
            return (
                last_content.get("summary")
                or last_content.get("instructions")
                or last_content.get("content")
                or ""
            )
        return str(last_content)

    async def _get_shim_snapshots(
        self, sandbox: ToolSandbox, shim_ids: list[str]
    ) -> dict[str, Any]:
        """Queries active simulators for point-in-time state snapshots."""
        simulators = sandbox.get_active_simulators()
        shim_snapshots = {}
        if not shim_ids:
            return shim_snapshots

        tasks = []
        valid_ids = []
        for sid in shim_ids:
            shim = simulators.get(sid)
            if shim:
                tasks.append(shim.get_snapshot())
                valid_ids.append(sid)
            else:
                logger.warning(f"      [Session] [Parity] Unknown shim target: {sid}")

        if tasks:
            results = await asyncio.gather(*tasks)
            shim_snapshots = dict(zip(valid_ids, results, strict=True))
        return shim_snapshots

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
