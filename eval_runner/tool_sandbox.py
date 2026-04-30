from __future__ import annotations

"""
tool_sandbox.py

Defines the environment in which the agent's tool calls are executed.
Updated with AbstractSandbox for pluggable implementation and lifecycle hooks.
"""

from abc import ABC, abstractmethod  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from . import config  # noqa: E402


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
                # Log but do not crash during teardown (Industrial Robustness)
                # In a real system, we'd emit an event here
                import sys

                sys.stderr.write(
                    f"      [ResourceRegistry] [WARN] Cleanup failed for {path}: {e}\n"
                )


class SharedStateRegistry:
    """Standard protocol for multi-agent state visibility (namespaces)."""

    def __init__(self, topology: dict, event_bus: Any | None = None):
        self.topology = topology
        self.registry: dict[str, Any] = {}  # Stores namespace:key -> value
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

            # Granular Taint tracking: Emit write event
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
            # Track redundant reads (reading same value multiple times)
            # This is a metric mentioned in the roadmap
            val = self.registry.get(path)

            # Granular Taint tracking: Emit read event
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
    ):
        self.scenario = scenario
        self.state = scenario.get("initial_state", {}).copy()
        self.shared_state = SharedStateRegistry(
            scenario.get("agent_topology", {}), event_bus=event_bus
        )
        self.current_agent = "default_agent"  # Can be updated per turn
        self.event_bus = event_bus
        self.forensics = forensics
        self.resources = ResourceRegistry()
        self.plugin_manager = plugin_manager

        # [INDUSTRIAL HARDENING] Absolute Session Identity (AgentV v1.6.0)
        # Prevents 'unknown_run' directory pollution in the root runs/ directory.
        self.run_id = self.scenario.get("run_id")
        if not self.run_id:
            # Fallback for unit tests only; production runs MUST have a run_id via SessionManager
            import tempfile

            from . import utils

            self.run_id = utils.generate_id(prefix="transient")
            self.terminal_jail = (
                Path(tempfile.gettempdir()) / "agentv" / self.run_id / "terminal_jail"
            )
        else:
            self.terminal_jail = (config.RUN_LOG_DIR / self.run_id / "terminal_jail").resolve()

        # Workspace management
        self.identifier = self.scenario.get("id", "default")
        # [Industrial Isolation] Workspaces MUST be partitioned by run_id to ensure
        # parallel execution safety and forensic purity.
        self.workspace_dir = Path("workspace") / self.run_id

        # Phase 2: Grounding Coverage Tracking
        # Stores hit counts for 'policies' and 'tools' (KB/Grounding)
        self.grounding_hits: dict[str, dict[str, int]] = {"policies": {}, "tools": {}}

        # Cache for state-aware world simulators
        self._simulator_cache: dict[str, Any] | None = None

        # [Turn 2 Hardening] Session-Scoped Terminal Jail
        import hashlib
        import json

        # [RFC-002 Hybrid Registry] Environmental DNA Snapshot
        # Capture the resolved state of all shims for this run
        full_registry = config.RegistryManager.reload()
        snapshot_json = json.dumps(full_registry, sort_keys=True)
        self.provisioning_hash = hashlib.sha256(snapshot_json.encode()).hexdigest()

        # [REDACTION] Scrub secrets before injecting into the trace (v1.3.0 Hardening)
        self.provisioning_snapshot = config.RegistryManager.get_sanitized_registry()

        # Inject into scenario for first-class status in run traces (Metadata DNA)
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

        # Aggregate states from all active simulators
        # We use get_active_simulators() to ensure we only capture shims
        # that are within the current Forensic Scope.
        simulators = self.get_active_simulators()
        for shim_name, shim_instance in simulators.items():
            try:
                # [Forensic Parity] Capture ground truth from the simulator
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
        # Ensure the terminal_jail exists physically (Iteration 2 Physical Isolation)
        Path(self.terminal_jail).mkdir(parents=True, exist_ok=True)

        # [Forensic Baseline] Capture initial state before any turn execution
        # This allows Turn 1 to be a differential snapshot.
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
        # 1. Mandatory Physical Cleanup (Resource Registry)
        self.resources.register(p)

        # 2. Cryptographic Audit (Forensics) - Optional
        if self.forensics:
            self.forensics.register_artifact(p, alias or p.name)

    async def teardown(self):
        """Perform one-time teardown: Clean up workspace (optional)."""
        import os
        from pathlib import Path

        # 0. Core Hardening (Iteration 6): RELEASE HANDLES FIRST
        # Explicitly teardown all simulators to release resources (DB handles, etc.)
        # This prevents WinError 32 during filesystem cleanup.
        if self._simulator_cache:
            for sim in self._simulator_cache.values():
                try:
                    await sim.cleanup()
                except Exception:  # noqa: E722
                    pass
            print(
                f"      [Sandbox] All {len(self._simulator_cache)} simulators cleaned up "
                "(Registry Teardown)."
            )

        # 1. Industrial Resource Cleanup
        self.resources.cleanup()

        # Only clean up if explicitly requested in scenario metadata or if it's a test run
        metadata = self.scenario.get("metadata", {})
        if metadata.get("cleanup_workspace", self.scenario.get("cleanup_workspace", False)):
            ws_path = Path(self.workspace_dir)
            if ws_path.exists():
                from .utils import rmtree_resilient

                rmtree_resilient(ws_path)
                print("      [Sandbox] Workspace cleaned up.")

        # [Iteration 5: Secure Wipe] Cleanup terminal_jail
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


class ToolSandbox(AbstractSandbox):
    """
    Standard implementation of the tool sandbox.
    Uses a static mapping of tool behaviors defined in the scenario.
    """

    async def execute(self, tool_name: str, params: dict, agent_name: str | None = None) -> dict:
        """
        Executes a tool based on the mock behaviors defined in the scenario.
        Updates the internal state and shared state registry.
        """
        active_agent = agent_name or self.current_agent

        # 1. Identify tool behaviors in the scenario
        all_tool_defs = self.scenario.get("tools", {})
        tool_def = all_tool_defs.get(tool_name, {})

        # 2. Check for Built-in Simulators (v3) - Refactored for Hot-Swap
        if not tool_def:
            active_simulators = self.get_active_simulators()
            for sim_name, simulator in active_simulators.items():
                if tool_name.startswith(f"{sim_name}_"):
                    return await simulator.execute(tool_name, params)

        # Record hit for Tool/KB access
        self.grounding_hits["tools"][tool_name] = self.grounding_hits["tools"].get(tool_name, 0) + 1

        # 2. Check for Policy Violations
        policies = self.scenario.get("policies", {})
        if tool_name in policies:
            # Record hit for Policy enforcement
            self.grounding_hits["policies"][tool_name] = (
                self.grounding_hits["policies"].get(tool_name, 0) + 1
            )
            limit = policies[tool_name].get("max_limit")
            if limit and params.get("amount", 0) > limit:
                return {
                    "status": "policy_violation",
                    "violation": f"Amount {params.get('amount')} exceeds limit of {limit}",
                }

        # 3. Apply Local State Changes
        state_changes = tool_def.get("state_changes", [])
        for change in state_changes:
            path = change.get("path")
            value = change.get("value")
            if path:
                self.state[path] = value

        # 4. Handle Shared State (v2)
        # Check if params contain shared state interactions
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

        # 5. Return Output
        output = tool_def.get("output", {"status": "success", "message": f"Executed {tool_name}"})

        # Notify observers of internal state changes
        from . import events

        # Sandbox Escape Prevention: Chroot/Virtualize paths before emitting
        # Security: Sanitize both keys AND values; strip shell meta-characters (Audit Point #5)
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

        # 1. Simple keys (no separators, no traversals) are returned as is
        if not any(x in path for x in ["..", "/", "\\"]):
            return path

        # 2. If traversal is attempted, collapse to basename for maximum safety (Audit Point #5)
        if ".." in path:
            # Normalize to forward slashes for basename processing
            clean_path = os.path.basename(path.replace("\\", "/"))
            return f"{config.SANDBOX_VFS_PREFIX}{clean_path}"

        # 3. Otherwise, normalize and virtualize nested paths
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
        nodes = workflow.get("nodes", [])

        # 1. Discover from Tool Usage (Global and Local)
        # Dynamically resolve sanctioned shim prefixes from the Global Gate
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

        # 2. Discover from Outcome Contracts
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

        # 1. Load the Authoritative Registry (merged baseline + .d extensions)
        resolved_registry = config.RegistryManager.get_resolved_registry()
        shim_configs = resolved_registry.get("shims", {})

        # 2. Get the industrial class mapping
        shim_classes = simulators.get_simulator_registry(plugin_manager=self.plugin_manager)

        # 3. Resolve Activation Policies
        global_enabled = config.GLOBAL_ENABLED_SHIMS

        # [Industrial Hardening] Resolve Activation Strategy
        # Case 1: If 'enabled_shims' is omitted, use 'Strict Discovery Mode'.
        # Case 2: If 'enabled_shims' is provided, it acts as an 'Authoritative Whitelist'.
        scenario_enabled = self.scenario.get("enabled_shims")
        relevant_shims = self._get_scenario_relevant_shims()

        active_registry = {}

        # Discover across all unique configured shims and supported classes
        # (Iteration 9: Full Spectrum Discovery)
        all_potential_shims = set(shim_configs.keys()) | set(shim_classes.keys())

        for shim_name in all_potential_shims:
            shim_cfg = shim_configs.get(shim_name, {})
            # If not in configs, we might still have a built-in class
            base_cls = shim_classes.get(shim_name)

            # Priority 1: Master System Filter (Hard Gate)
            # If a shim is not globally sanctioned, it is never available to the scenario.
            is_globally_enabled = "*" in global_enabled or shim_name in global_enabled
            if not is_globally_enabled:
                continue

            # Priority 2: Scenario Activation Policy
            # Only shims that are relevant to the contract or explicitly enabled are activated.
            is_relevant = shim_name in relevant_shims
            if scenario_enabled is None:
                # Case 1: Strict Discovery Mode (Auto-activate relevant only)
                should_activate = is_relevant
            else:
                # Case 2: Explicit Whitelist Mode (Guardrail)
                should_activate = "*" in scenario_enabled or shim_name in scenario_enabled

            if not should_activate:
                continue

            # Layer 3: Authoritative Type Resolution
            shim_type = shim_cfg.get("type", shim_name)

            # Re-verify class affinity if type was overridden or using built-in
            target_cls = shim_classes.get(shim_type, base_cls)

            if target_cls:
                try:
                    # [Zero-Touch Injection] Instantiate with registry-provided resources
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
            # Strip path traversals
            value = re.sub(r"\.\.[\\/]+", "", value)
            value = value.replace("../", "").replace("..\\", "")
            # Strip shell meta-characters
            for char in config.SHELL_METABLOCKS:
                value = value.replace(char, "")
        elif isinstance(value, dict):
            return {k: ToolSandbox._sanitize_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [ToolSandbox._sanitize_value(v) for v in value]
        return value
