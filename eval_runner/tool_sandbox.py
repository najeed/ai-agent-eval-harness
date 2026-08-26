"""tool_sandbox.py

Defines the environment in which the agent's tool calls are executed.
Updated with AbstractSandbox for pluggable implementation and lifecycle hooks.
"""

from __future__ import annotations

import contextvars
import json
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from eval_runner.interfaces.policy import PolicyEvaluator
from eval_runner.reference.field_policy import BasicFieldPolicyEvaluator

from . import config


class ResourceRegistry:
    """Centralized tracking for physical files and directories created during a session."""

    def __init__(self):
        self._tracked_paths: set[Path] = set()

    def register(self, path: str | Path):
        """Registers a path for mandatory physical cleanup."""
        p = Path(path).absolute()
        self._tracked_paths.add(p)

    def cleanup(self):
        """Perform an atomic unlink/rmtree of all registered paths."""
        for path in self._tracked_paths:
            try:
                if path.is_file():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    from .utils import rmtree_resilient

                    rmtree_resilient(path)
            except Exception as e:
                import sys

                sys.stderr.write(
                    f"      [ResourceRegistry] [WARN] Cleanup failed for {path}: {e}\n"
                )


class SharedStateRegistry:
    """Standard protocol for multi-agent state visibility (namespaces)."""

    def __init__(self, topology: dict, event_bus: Any | None = None):
        self.topology = topology
        self.registry: dict[str, Any] = {}
        self.redundant_reads = 0
        self.event_bus = event_bus

    def write(self, agent_name: str, path: str, value: Any) -> bool:
        """Writes to a namespace if agent has permission."""
        namespace = path.split(":")[0] if ":" in path else "global"
        agent_config = self.topology.get(agent_name, {})
        allowed_writes = agent_config.get("writes", [])
        if (
            any(self._match_namespace(namespace, pattern) for pattern in allowed_writes)
            or "*" in allowed_writes
        ):
            self.registry[path] = value
            from . import events

            event_data = {"agent": agent_name, "path": path, "value": value}
            if self.event_bus:
                self.event_bus.emit("state_write", event_data)
            else:
                events.emit("state_write", event_data)
            return True
        return False

    def read(self, agent_name: str, path: str) -> Any:
        """Reads from a namespace if agent has permission."""
        namespace = path.split(":")[0] if ":" in path else "global"
        agent_config = self.topology.get(agent_name, {})
        allowed_reads = agent_config.get("reads", [])
        if (
            any(self._match_namespace(namespace, pattern) for pattern in allowed_reads)
            or "*" in allowed_reads
        ):
            val = self.registry.get(path)
            from . import events

            event_data = {"agent": agent_name, "path": path, "value": val}
            if self.event_bus:
                self.event_bus.emit("state_read", event_data)
            else:
                events.emit("state_read", event_data)
            return val
        return None

    def _match_namespace(self, namespace: str, pattern: str) -> bool:
        if pattern == "*":
            return True
        if pattern.endswith(":*"):
            return namespace == pattern.split(":")[0]
        return namespace == pattern


class AbstractSandbox(ABC):
    """Abstract base class for tool execution sandboxes."""

    def __init__(
        self,
        scenario: dict,
        event_bus: Any | None = None,
        forensics: Any | None = None,
        plugin_manager: Any | None = None,
        workspace_root: Path | None = None,
        jail_root: Path | None = None,
        policy_evaluator: PolicyEvaluator | None = None,
    ):
        self.scenario = scenario
        self.policy_evaluator = policy_evaluator or BasicFieldPolicyEvaluator()
        self.state = scenario.get("initial_state", {}).copy()
        self.shared_state = SharedStateRegistry(
            scenario.get("agent_topology", {}), event_bus=event_bus
        )
        self.current_agent = "default_agent"
        self.event_bus = event_bus
        self.forensics = forensics
        self.resources = ResourceRegistry()
        self.plugin_manager = plugin_manager
        self.run_id = self.scenario.get("run_id")
        if not self.run_id:
            import tempfile

            from . import utils

            self.run_id = utils.generate_id(prefix="transient")
            self.terminal_jail = (
                jail_root or Path(tempfile.gettempdir()) / "agentv" / self.run_id / "terminal_jail"
            )
        else:
            self.terminal_jail = (
                jail_root or (config.RUN_LOG_DIR / self.run_id / "terminal_jail").resolve()
            )
        self.identifier = self.scenario.get("id", "default")
        base_ws = workspace_root or Path("workspace")
        self.workspace_dir = base_ws / self.run_id
        self.grounding_hits: dict[str, dict[str, int]] = {"policies": {}, "tools": {}}
        # [A4] First-class policy decision ledger. Every sandbox policy
        # evaluation (allowed AND denied) is recorded as a structured
        # assertion with id / input-hash / decision / reason / evidence.
        self.policy_decisions: list[dict[str, Any]] = []
        self._simulator_cache: dict[str, Any] | None = None
        import json

        from .utils import crypto

        full_registry = config.RegistryManager.reload()
        snapshot_json = json.dumps(full_registry, sort_keys=True)
        self.provisioning_hash = crypto.checksum(snapshot_json)
        self.provisioning_snapshot = config.RegistryManager.get_sanitized_registry()
        if "metadata" not in self.scenario:
            self.scenario["metadata"] = {"name": "unnamed", "compliance_level": "Standard"}
        self.scenario["metadata"]["provisioning_hash"] = self.provisioning_hash
        self.scenario["environmental_snapshot"] = self.provisioning_snapshot

    async def get_full_state(self) -> dict[str, Any]:
        """
        [Industrial Requirement] Aggregates the base world state and the snapshots
        from all active shims (simulators).
        """
        full_state = {"world": self.state}
        simulators = self.get_active_simulators()
        for shim_name, shim_instance in simulators.items():
            try:
                full_state[shim_name] = await shim_instance.get_snapshot()
            except Exception as e:
                import sys

                sys.stderr.write(
                    f"      [Sandbox] Warning: Failed to snapshot shim '{shim_name}': {e}\n"
                )
                full_state[shim_name] = {"error": str(e)}
        return full_state

    async def setup(self):
        """Perform one-time setup: Create workspace and terminal_jail directories."""
        from pathlib import Path

        Path(self.workspace_dir).mkdir(parents=True, exist_ok=True)
        Path(self.terminal_jail).mkdir(parents=True, exist_ok=True)
        if self.forensics:
            try:
                initial_state = await self.get_full_state()
                self.forensics.snapshot_state(initial_state, 0)
            except Exception as e:
                import sys

                sys.stderr.write(
                    f"      [Sandbox] Warning: Failed to capture initial forensic baseline: {e}\n"
                )
        print(f"      [Sandbox] Workspace initialized at: {self.workspace_dir}")
        print(f"      [Sandbox] Terminal Jail provisioned: {self.terminal_jail}")

    def register_artifact(self, path: str | Path, alias: str | None = None):
        """
        [Industrial Proxy] Single entry point for physical state tracking.
        Registers path for cleanup (Registry) and auditing (Forensics).
        """
        from pathlib import Path

        p = Path(path)
        self.resources.register(p)
        if self.forensics:
            self.forensics.register_artifact(p, alias or p.name)

    async def teardown(self):
        """Perform one-time teardown: Clean up workspace (optional)."""
        import os
        from pathlib import Path

        if self._simulator_cache:
            for sim in self._simulator_cache.values():
                try:
                    await sim.cleanup()
                except Exception as e:
                    import logging

                    logging.getLogger(__name__).warning(f"Failed simulator cleanup for {sim}: {e}")
            sim_count = len(self._simulator_cache)
            print(f"      [Sandbox] All {sim_count} simulators cleaned up (Registry Teardown).")
        self.resources.cleanup()
        metadata = self.scenario.get("metadata", {})
        if metadata.get("cleanup_workspace", self.scenario.get("cleanup_workspace", False)):
            ws_path = Path(self.workspace_dir)
            if ws_path.exists():
                from .utils import rmtree_resilient

                rmtree_resilient(ws_path)
                print("      [Sandbox] Workspace cleaned up.")
        cleanup_jail = metadata.get(
            "cleanup_terminal_jail", os.getenv("CLEANUP_TERMINAL_JAIL", "true").lower() == "true"
        )
        if cleanup_jail:
            jail_path = Path(self.terminal_jail)
            if jail_path.exists():
                from .utils import rmtree_resilient

                rmtree_resilient(jail_path)
                print(f"      [Sandbox] Secure Wipe: Terminal Jail deleted at {jail_path}")

    @abstractmethod
    def execute(self, tool_name: str, params: dict, agent_name: str | None = None) -> dict:
        """Executes a tool and returns the result."""
        pass


class ToolSandboxInterceptor(ABC):
    """Abstract Base Class for Tool Sandbox Interceptors in the execution pipeline."""

    @abstractmethod
    def can_isolate(self, tool_name: str) -> bool:
        """Determines if this interceptor can isolate or intercept the requested tool."""
        pass

    @abstractmethod
    async def isolate_call(
        self, call_data: dict, next_executor: Callable[[dict], Coroutine[None, None, dict]]
    ) -> dict:
        """Applies middleware processing (Preempt, Audit, or Augment tool execution)."""
        pass


class ToolSandboxService:
    """Thread-safe context management service for dynamic interceptors."""

    def __init__(self):

        self._lock = threading.Lock()
        self._global_interceptors: list[ToolSandboxInterceptor] = []
        self._local_interceptors = contextvars.ContextVar("local_interceptors", default=None)

    @property
    def _interceptors(self) -> list[ToolSandboxInterceptor]:
        """Provides contextvars-local copy of registered interceptors to ensure
        async task isolation.
        """
        val = self._local_interceptors.get()
        if val is None:
            with self._lock:
                val = list(self._global_interceptors)
            self._local_interceptors.set(val)
        return val

    def register_interceptor(self, interceptor: ToolSandboxInterceptor):
        """Registers an async interceptor thread-safely at the head of the chain."""
        with self._lock:
            self._global_interceptors.insert(0, interceptor)
            val = self._local_interceptors.get()
            if val is None:
                self._local_interceptors.set([interceptor])
            else:
                val.insert(0, interceptor)

    def reset(self):
        """Thread-safely clears all custom async interceptors."""
        with self._lock:
            self._global_interceptors.clear()
            self._local_interceptors.set(None)

    @asynccontextmanager
    async def override_interceptor(self, interceptor: ToolSandboxInterceptor):
        """Async context manager to temporarily register an async interceptor.

        Prevents leak pollution.
        """
        with self._lock:
            self._global_interceptors.insert(0, interceptor)
        current = self._interceptors
        new_list = [interceptor] + [x for x in current if x is not interceptor]
        token = self._local_interceptors.set(new_list)
        try:
            yield
        finally:
            self._local_interceptors.reset(token)
            with self._lock:
                if interceptor in self._global_interceptors:
                    self._global_interceptors.remove(interceptor)

    async def isolate(
        self, call_data: dict, fallback_executor: Callable[[dict], Coroutine[None, None, dict]]
    ) -> dict:
        """Executes the tool call through the interceptor pipeline chain with cycle protection."""
        tool_name = call_data.get("tool_name")

        def make_next(index: int, depth: int) -> Callable[[dict], Coroutine[None, None, dict]]:
            if depth > 50:
                raise RecursionError("Max tool sandbox pipeline depth exceeded. Cycle detected.")
            interceptors_list = self._interceptors
            if index >= len(interceptors_list):
                return fallback_executor
            interceptor = interceptors_list[index]

            async def call_next(data: dict) -> dict:
                if interceptor.can_isolate(tool_name):
                    try:
                        return await interceptor.isolate_call(data, make_next(index + 1, depth + 1))
                    except (RecursionError, KeyboardInterrupt, SystemExit, GeneratorExit):
                        raise
                    except Exception as e:
                        import logging

                        cls_name = interceptor.__class__.__name__
                        logging.error(
                            f"[ToolSandboxService] Interceptor '{cls_name}' failed: {e}. Bypassing."
                        )
                        return await make_next(index + 1, depth + 1)(data)
                else:
                    return await make_next(index + 1, depth + 1)(data)

            return call_next

        return await make_next(0, 0)(call_data)


tool_sandbox_service = ToolSandboxService()


class ToolSandbox(AbstractSandbox):
    """
    Standard implementation of the tool sandbox.
    Uses a static mapping of tool behaviors defined in the scenario.
    """

    async def execute(self, tool_name: str, params: dict, agent_name: str | None = None) -> dict:
        """Executes a tool and returns the result, routing through the

        tool sandbox interceptor pipeline.
        """
        call_data = {
            "tool_name": tool_name,
            "params": params,
            "agent_name": agent_name,
            "sandbox": self,
        }

        async def core_executor(data: dict) -> dict:
            return await self._execute_core(
                tool_name=data["tool_name"], params=data["params"], agent_name=data["agent_name"]
            )

        return await tool_sandbox_service.isolate(call_data, core_executor)

    async def _execute_core(
        self, tool_name: str, params: dict, agent_name: str | None = None
    ) -> dict:
        """Executes a tool based on the mock behaviors defined in the scenario.

        Updates the internal state and shared state registry.
        """
        active_agent = agent_name or self.current_agent
        all_tool_defs = self.scenario.get("tools", {})
        if tool_name not in all_tool_defs:
            active_simulators = self.get_active_simulators()
            for sim_name, simulator in active_simulators.items():
                if tool_name.startswith(f"{sim_name}_"):
                    raw_result = await simulator.execute(tool_name, params)
                    if hasattr(simulator, "quiesce"):
                        try:
                            import asyncio
                            import logging

                            await asyncio.wait_for(simulator.quiesce(), timeout=5.0)
                        except TimeoutError:
                            import logging

                            c_name = simulator.__class__.__name__
                            logging.getLogger(__name__).warning(f"Quiescence timeout for {c_name}.")
                        except Exception as e:
                            import logging

                            logging.getLogger(__name__).error(
                                f"Error during quiescence for {simulator.__class__.__name__}: {e}"
                            )
                    from .simulators import ShimResultProxy

                    secure_metadata = {"dna_hash": self.provisioning_hash}
                    if "dna" in raw_result:
                        secure_metadata.update(raw_result["dna"])
                    return ShimResultProxy(raw_result, metadata=secure_metadata)

            # [A1] Fail-closed: a tool that is registered neither in the
            # scenario tools manifest nor among active simulators can never
            # synthesize success. The kernel returns a hard UNREGISTERED_TOOL
            # error so upstream verdicts stay truth-authoritative.
            return {
                "status": "error",
                "error_code": "UNREGISTERED_TOOL",
                "tool_name": tool_name,
                "message": (
                    f"Tool '{tool_name}' is not registered in this scenario "
                    "(tools manifest or active simulators). Refusing to "
                    "synthesize a successful result (fail-closed)."
                ),
            }
        else:
            tool_def = all_tool_defs[tool_name]
        self.grounding_hits["tools"][tool_name] = self.grounding_hits["tools"].get(tool_name, 0) + 1
        policies = self.scenario.get("policies", {})
        if tool_name in policies:
            self.grounding_hits["policies"][tool_name] = (
                self.grounding_hits["policies"].get(tool_name, 0) + 1
            )
            policy_spec = policies[tool_name]
            eval_result = self.policy_evaluator.evaluate_policy(
                policy_spec=policy_spec,
                input_data=params,
                context={"tool_name": tool_name, "agent": active_agent, "state": self.state},
            )
            violation_msg = eval_result.reason
            if not eval_result.allowed and eval_result.violations:
                v = eval_result.violations[0]
                if "message" in v:
                    violation_msg = v["message"]
                elif "field" in v and "limit" in v:
                    violation_msg = (
                        f"Parameter '{v['field']}' with value {v.get('value')} "
                        f"exceeds limit of {v['limit']}"
                    )

            # [A4] Record the decision as a first-class policy assertion with
            # a deterministic input commitment (SHA3-256 over canonical
            # tool+params JSON) so verdicts can cite exact evaluated inputs.
            import hashlib

            input_commitment_src = json.dumps(
                {"tool": tool_name, "params": params}, sort_keys=True, default=str
            ).encode("utf-8")
            self.policy_decisions.append(
                {
                    "id": eval_result.policy_id,
                    "input_hash": f"sha3_256:{hashlib.sha3_256(input_commitment_src).hexdigest()}",
                    "decision": "allowed" if eval_result.allowed else "denied",
                    "reason": violation_msg
                    or ("policy satisfied" if eval_result.allowed else "policy denied"),
                    "evidence": eval_result.to_dict(),
                    "tool_name": tool_name,
                    "agent": active_agent,
                }
            )

            if not eval_result.allowed:
                return {
                    "status": "policy_violation",
                    "violation": violation_msg,
                    "policy_id": eval_result.policy_id,
                    "details": eval_result.to_dict(),
                }
        state_changes = tool_def.get("state_changes", [])
        for change in state_changes:
            path = change.get("path")
            value = change.get("value")
            if path:
                self.state[path] = value
        if "shared_write" in params:
            write_path = params["shared_write"].get("path")
            write_val = params["shared_write"].get("value")
            if write_path:
                success = self.shared_state.write(active_agent, write_path, write_val)
                if not success:
                    return {
                        "status": "error",
                        "message": f"Agent {active_agent} has no write permission for {write_path}",
                    }
        if "shared_read" in params:
            read_path = params["shared_read"].get("path")
            if read_path:
                val = self.shared_state.read(active_agent, read_path)
                if val is None and read_path in self.shared_state.registry:
                    return {
                        "status": "error",
                        "message": f"Agent {active_agent} has no read permission for {read_path}",
                    }
        output = tool_def.get("output", {"status": "success", "message": f"Executed {tool_name}"})
        from . import events

        safe_state = {}
        for k, v in self.state.items():
            safe_key = self._sanitize_path(k)
            safe_val = self._sanitize_value(v)
            safe_state[safe_key] = safe_val
        if self.event_bus:
            self.event_bus.emit(
                "world_state_change",
                {"state": safe_state, "shared_state": self.shared_state.registry},
            )
        else:
            events.emit(
                "world_state_change",
                {"state": safe_state, "shared_state": self.shared_state.registry},
            )
        return output

    async def get_full_state(self) -> dict[str, Any]:
        """
        Deep State Aggregation.
        Walks the simulator cache and performs a bulk snapshot of shims.
        """
        full_state = {
            "world": self.state.copy(),
            "shared": self.shared_state.registry.copy(),
            "shims": {},
        }
        simulators = self.get_active_simulators()
        for name, sim in simulators.items():
            try:
                full_state["shims"][name] = await sim.get_snapshot()
            except Exception as e:
                import sys

                sys.stderr.write(
                    f"      [Sandbox] Warning: Failed to snapshot shim '{name}': {e}\n"
                )
        return full_state

    @staticmethod
    def _sanitize_path(path: str) -> str:
        """
        [Security Protocol] Path Virtualization.
        Strips directory traversal sequences and prepends vfs:// root.
        Aggressively collapses to basename if traversal is attempted.
        """
        import os

        from . import config

        if not any(x in path for x in ["..", "/", "\\"]):
            return path
        if ".." in path:
            clean_path = os.path.basename(path.replace("\\", "/"))
            return f"{config.SANDBOX_VFS_PREFIX}{clean_path}"
        clean_path = path.replace("\\", "/").lstrip("/")
        if not clean_path.startswith(config.SANDBOX_VFS_PREFIX):
            clean_path = f"{config.SANDBOX_VFS_PREFIX}{clean_path}"
        return clean_path

    def _get_scenario_relevant_shims(self) -> set[str]:
        """
        [Forensic Relevance Engine] Extracts all shims explicitly mentioned in the
        scenario contracts (expected_outcome, success_criteria, etc.) or required tools.
        """
        relevant = set()
        workflow = self.scenario.get("workflow", {})
        if isinstance(workflow, list):
            nodes = workflow
        elif isinstance(workflow, dict):
            nodes = workflow.get("nodes", [])
        else:
            nodes = []
        from . import config, simulators

        global_enabled = config.GLOBAL_ENABLED_SHIMS
        all_registered = set(
            simulators.get_simulator_registry(plugin_manager=self.plugin_manager).keys()
        )
        if "*" in global_enabled:
            shim_prefixes = all_registered
        else:
            shim_prefixes = all_registered.intersection(set(global_enabled))
        all_tools = set(self.scenario.get("tools", {}).keys())
        for node in nodes:
            all_tools.update(node.get("required_tools", []))
        for tool in all_tools:
            if "_" in tool:
                prefix = tool.split("_", 1)[0]
                if prefix in shim_prefixes:
                    relevant.add(prefix)
        for node in nodes:
            outcomes = node.get("expected_outcome", [])
            if outcomes:
                outcome_list = [outcomes] if isinstance(outcomes, dict) else outcomes
                for outcome in outcome_list:
                    if not isinstance(outcome, dict):
                        continue
                    target = outcome.get("target", "")
                    if target.startswith("shim:"):
                        shim_id = target.split("shim:", 1)[1].split(".", 1)[0]
                        relevant.add(shim_id)
        return relevant

    def get_active_simulators(self) -> dict:
        """
        [Industrial Discovery] Dynamically instantiates shims from the Registry
        based on type mapping and administrative activation policy.
        """
        if self._simulator_cache is not None:
            return self._simulator_cache
        import sys

        from . import config, simulators

        resolved_registry = config.RegistryManager.get_resolved_registry()
        shim_configs = resolved_registry.get("shims", {})
        shim_classes = simulators.get_simulator_registry(plugin_manager=self.plugin_manager)
        global_enabled = config.GLOBAL_ENABLED_SHIMS
        scenario_enabled = self.scenario.get("enabled_shims")
        relevant_shims = self._get_scenario_relevant_shims()
        active_registry = {}
        all_potential_shims = set(shim_configs.keys()) | set(shim_classes.keys())
        for shim_name in all_potential_shims:
            shim_cfg = shim_configs.get(shim_name, {})
            base_cls = shim_classes.get(shim_name)
            is_globally_enabled = "*" in global_enabled or shim_name in global_enabled
            if not is_globally_enabled:
                continue
            is_relevant = shim_name in relevant_shims
            if scenario_enabled is None:
                should_activate = is_relevant
            else:
                should_activate = "*" in scenario_enabled or shim_name in scenario_enabled
            if not should_activate:
                continue
            shim_type = shim_cfg.get("type", shim_name)
            target_cls = shim_classes.get(shim_type, base_cls)
            if target_cls:
                try:
                    instance = target_cls(config=shim_cfg)
                    instance.terminal_jail = self.terminal_jail
                    instance.sandbox = self
                    active_registry[shim_name] = instance
                except Exception as e:
                    sys.stderr.write(
                        f"      [Sandbox] Error: Failed to instantiate '{shim_name}': {e}\n"
                    )
            else:
                sys.stderr.write(
                    f"      [Sandbox] Warning: Unknown shim type '{shim_type}' for '{shim_name}'\n"
                )
        self._simulator_cache = active_registry
        return active_registry

    @staticmethod
    def _sanitize_value(value):
        """Strip shell meta-characters and path traversals from emitted values."""
        import re

        if isinstance(value, str):
            value = re.sub("\\.\\.[\\\\/]+", "", value)
            value = value.replace("../", "").replace("..\\", "")
            for char in config.SHELL_METABLOCKS:
                value = value.replace(char, "")
        elif isinstance(value, dict):
            return {k: ToolSandbox._sanitize_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [ToolSandbox._sanitize_value(v) for v in value]
        return value

    def fork(self, branch_id: str, state_semantics: str = "isolated") -> ToolSandbox:
        """
        [P2.1/P2.2] Creates an isolated branch sandbox instance for concurrent
        workflow node execution. Branch mutations (state, policy decisions,
        shared state) remain isolated until explicitly committed via merge_branch_state.
        """
        import copy

        forked = ToolSandbox(
            scenario=copy.deepcopy(self.scenario),
            event_bus=self.event_bus,
            forensics=self.forensics,
            plugin_manager=self.plugin_manager,
            workspace_root=self.workspace_dir,
            jail_root=self.terminal_jail,
            policy_evaluator=self.policy_evaluator,
        )
        forked.state = copy.deepcopy(self.state)
        forked.shared_state = SharedStateRegistry(
            self.scenario.get("agent_topology", {}), event_bus=self.event_bus
        )
        forked.shared_state.registry = copy.deepcopy(self.shared_state.registry)
        forked.policy_decisions = list(self.policy_decisions)
        forked.current_agent = self.current_agent
        return forked

    def merge_branch_state(self, source_fork: ToolSandbox, keys: list[str] | None = None) -> None:
        """
        [P2.2] Explicit join-level state commit primitive.
        Merges candidate state transitions and policy decisions from a branch fork.
        """
        import copy

        if keys is not None:
            for k in keys:
                if k in source_fork.state:
                    self.state[k] = copy.deepcopy(source_fork.state[k])
        else:
            self.state.update(copy.deepcopy(source_fork.state))

        # Merge shared state registry additions
        self.shared_state.registry.update(copy.deepcopy(source_fork.shared_state.registry))

        # Append new policy decisions
        existing_hashes = {d.get("input_hash") for d in self.policy_decisions if "input_hash" in d}
        for decision in source_fork.policy_decisions:
            if decision.get("input_hash") not in existing_hashes:
                self.policy_decisions.append(copy.deepcopy(decision))
                if "input_hash" in decision:
                    existing_hashes.add(decision["input_hash"])
