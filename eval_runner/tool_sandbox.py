"""
tool_sandbox.py

Defines the environment in which the agent's tool calls are executed.
Updated with AbstractSandbox for pluggable implementation and lifecycle hooks.
"""

import json
from typing import Any, Optional, Dict
from abc import ABC, abstractmethod

class SharedStateRegistry:
    """Standard protocol for multi-agent state visibility (namespaces)."""
    def __init__(self, topology: dict):
        self.topology = topology
        self.registry: dict[str, Any] = {}  # Stores namespace:key -> value
        self.redundant_reads = 0

    def write(self, agent_name: str, path: str, value: Any) -> bool:
        """Writes to a namespace if agent has permission."""
        namespace = path.split(":")[0] if ":" in path else "global"
        
        agent_config = self.topology.get(agent_name, {})
        allowed_writes = agent_config.get("writes", [])
        
        if any(self._match_namespace(namespace, pattern) for pattern in allowed_writes) or "*" in allowed_writes:
            self.registry[path] = value
            return True
        return False

    def read(self, agent_name: str, path: str) -> Any:
        """Reads from a namespace if agent has permission."""
        namespace = path.split(":")[0] if ":" in path else "global"
        
        agent_config = self.topology.get(agent_name, {})
        allowed_reads = agent_config.get("reads", [])
        
        if any(self._match_namespace(namespace, pattern) for pattern in allowed_reads) or "*" in allowed_reads:
            # Track redundant reads (reading same value multiple times)
            # This is a metric mentioned in the roadmap
            return self.registry.get(path)
        return None

    def _match_namespace(self, namespace: str, pattern: str) -> bool:
        if pattern == "*": return True
        if pattern.endswith(":*"):
            return namespace == pattern.split(":")[0]
        return namespace == pattern

class AbstractSandbox(ABC):
    """Abstract base class for tool execution sandboxes."""

    def __init__(self, scenario: dict):
        self.scenario = scenario
        self.state = scenario.get("initial_state", {}).copy()
        self.shared_state = SharedStateRegistry(scenario.get("agent_topology", {}))
        self.current_agent = "default_agent" # Can be updated per turn
        
        # Phase 2: Grounding Coverage Tracking
        # Stores hit counts for 'policies' and 'tools' (KB/Grounding)
        self.grounding_hits: Dict[str, Dict[str, int]] = {
            "policies": {},
            "tools": {}
        }

    def setup(self):
        """Perform one-time setup (e.g., spinning up Docker, init DB)."""
        pass

    def teardown(self):
        """Perform one-time teardown (e.g., stopping containers)."""
        pass

    @abstractmethod
    def execute(self, tool_name: str, params: dict, agent_name: Optional[str] = None) -> dict:
        """Executes a tool and returns the result."""
        pass

class ToolSandbox(AbstractSandbox):
    """
    Standard implementation of the tool sandbox.
    Uses a static mapping of tool behaviors defined in the scenario.
    """

    def execute(self, tool_name: str, params: dict, agent_name: Optional[str] = None) -> dict:
        """
        Executes a tool based on the mock behaviors defined in the scenario.
        Updates the internal state and shared state registry.
        """
        active_agent = agent_name or self.current_agent
        
        # 1. Identify tool behaviors in the scenario
        all_tool_defs = self.scenario.get("tools", {})
        tool_def = all_tool_defs.get(tool_name, {})
        
        # 2. Check for Built-in Simulators (v3)
        if not tool_def:
            from . import simulators
            for sim_name, simulator in simulators.SIMULATOR_REGISTRY.items():
                if tool_name.startswith(f"{sim_name}_"):
                    return simulator.execute(tool_name, params)

        # Record hit for Tool/KB access
        self.grounding_hits["tools"][tool_name] = self.grounding_hits["tools"].get(tool_name, 0) + 1

        # 2. Check for Policy Violations
        policies = self.scenario.get("policies", {})
        if tool_name in policies:
            # Record hit for Policy enforcement
            self.grounding_hits["policies"][tool_name] = self.grounding_hits["policies"].get(tool_name, 0) + 1
            limit = policies[tool_name].get("max_limit")
            if limit and params.get("amount", 0) > limit:
                return {
                    "status": "policy_violation",
                    "violation": f"Amount {params.get('amount')} exceeds limit of {limit}"
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
                    return {"status": "error", "message": f"Agent {active_agent} has no write permission for {write_path}"}

        if "shared_read" in params:
            read_path = params["shared_read"]
            if read_path:
                val = self.shared_state.read(active_agent, read_path)
                # We can inject this value into the output if needed, but for now just validation
                if val is None and read_path in self.shared_state.registry:
                    return {"status": "error", "message": f"Agent {active_agent} has no read permission for {read_path}"}

        # 5. Return Output
        return tool_def.get("output", {"status": "success", "message": f"Executed {tool_name}"})
