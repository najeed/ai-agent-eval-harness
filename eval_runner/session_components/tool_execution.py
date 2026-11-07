"""
eval_runner.session_components.tool_execution
Decomposed Session Component: ToolExecutionCoordinator
"""

from collections.abc import Callable
from typing import Any

import eval_runner.tool_sandbox as tool_sandbox


class ToolExecutionCoordinator:
    """Coordinates tool invocations, policy gating, and simulator dispatch within a session."""

    def __init__(self, sandbox: tool_sandbox.ToolSandbox | None = None):
        self.sandbox = sandbox
        self.executed_tools: list[dict[str, Any]] = []

    def execute(
        self,
        tool_name: str,
        params: dict[str, Any],
        handler: Callable[..., Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> Any:
        """Executes a tool within the configured sandbox, recording call telemetry."""
        record = {
            "tool_name": tool_name,
            "params": params,
        }
        try:
            if self.sandbox:
                res = self.sandbox.execute_tool(tool_name, params)
            elif handler:
                res = handler(**params)
            else:
                raise RuntimeError(
                    f"ToolUnavailable: no sandbox or executable handler is bound for '{tool_name}'"
                )

            record["result"] = res
            record["status"] = "success"
            self.executed_tools.append(record)
            return res
        except Exception as e:
            record["status"] = "error"
            record["error"] = str(e)
            self.executed_tools.append(record)
            raise

    def snapshot(self) -> dict[str, Any]:
        """Serializes executed tool history."""
        return {
            "executed_count": len(self.executed_tools),
            "tool_names": [t["tool_name"] for t in self.executed_tools],
            "executed_tools": list(self.executed_tools),
        }

    def restore(self, state: dict[str, Any] | None) -> None:
        """Restores executed tool state from a checkpoint snapshot."""
        if not state or not isinstance(state, dict):
            return
        if "executed_tools" in state and isinstance(state["executed_tools"], list):
            self.executed_tools = [dict(t) for t in state["executed_tools"]]
        elif "tool_names" in state and isinstance(state["tool_names"], list):
            self.executed_tools = [
                {"tool_name": name, "status": "restored"} for name in state["tool_names"]
            ]
