"""
tool_sandbox.py

Defines the environment in which the agent's tool calls are executed.
Updated with AbstractSandbox for pluggable implementation and lifecycle hooks.
"""

import json
from abc import ABC, abstractmethod

class AbstractSandbox(ABC):
    """Abstract base class for tool execution sandboxes."""

    def __init__(self, scenario: dict):
        self.scenario = scenario
        self.state = scenario.get("initial_state", {}).copy()

    def setup(self):
        """Perform one-time setup (e.g., spinning up Docker, init DB)."""
        pass

    def teardown(self):
        """Perform one-time teardown (e.g., stopping containers)."""
        pass

    @abstractmethod
    def execute(self, tool_name: str, params: dict) -> dict:
        """Executes a tool and returns the result."""
        pass

class ToolSandbox(AbstractSandbox):
    """
    Standard implementation of the tool sandbox.
    Uses a static mapping of tool behaviors defined in the scenario.
    """

    def execute(self, tool_name: str, params: dict) -> dict:
        """
        Executes a tool based on the mock behaviors defined in the scenario.
        Updates the internal state if requested by the tool definition.
        """
        # 1. Identify tool behaviors in the scenario
        # We look for a top-level 'tools' dictionary that defines effects.
        all_tool_defs = self.scenario.get("tools", {})
        tool_def = all_tool_defs.get(tool_name, {})

        # 2. Check for Policy Violations (Simulated)
        # We simulate this by checking if 'amount' exceeds a limit in 'policies'
        policies = self.scenario.get("policies", {})
        if tool_name in policies:
            limit = policies[tool_name].get("max_limit")
            if limit and params.get("amount", 0) > limit:
                return {
                    "status": "policy_violation",
                    "violation": f"Amount {params.get('amount')} exceeds limit of {limit}"
                }

        # 3. Apply State Changes
        state_changes = tool_def.get("state_changes", [])
        for change in state_changes:
            path = change.get("path")
            value = change.get("value")
            if path:
                self.state[path] = value

        # 4. Return Output
        return tool_def.get("output", {"status": "success", "message": f"Executed {tool_name}"})
