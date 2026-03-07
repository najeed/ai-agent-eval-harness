"""
tool_sandbox.py

Provides an in-process mock tool execution environment for the AI Agent Evaluation Harness.
When the engine's multi-turn loop receives a tool call from the agent, this sandbox
returns a simulated success response, allowing the conversation to continue
without requiring an external tool server.

Typical usage:
    from eval_runner.tool_sandbox import ToolSandbox
    sandbox = ToolSandbox(scenario)
    result = sandbox.execute("get_customer_details", {"customer_id": "cust_123"})
"""
# eval-runner/tool_sandbox.py


class ToolSandbox:
    """
    In-process mock tool executor.

    Given a scenario, it knows which tools are valid (from required_tools across all tasks).
    When asked to execute a tool, it returns a generic success response.
    """

    def __init__(self, scenario: dict):
        """
        Initialize the sandbox with the scenario's tool inventory.

        Args:
            scenario (dict): The loaded scenario data.
        """
        self.known_tools = set()
        for task in scenario.get("tasks", []):
            for tool in task.get("required_tools", []):
                self.known_tools.add(tool)

    def execute(self, tool_name: str, params: dict = None) -> dict:
        """
        Execute a mock tool call.

        Args:
            tool_name (str): Name of the tool the agent wants to call.
            params (dict): Parameters the agent passed to the tool.

        Returns:
            dict: A mock result with status and tool_name.
        """
        if params is None:
            params = {}

        if tool_name in self.known_tools:
            print(f"      [Sandbox] ✅ Executed mock tool: {tool_name}({params})")
            return {
                "status": "success",
                "tool_name": tool_name,
                "output": f"Mock result for {tool_name}",
                "params_received": params,
            }
        else:
            print(f"      [Sandbox] ❌ Unknown tool requested: {tool_name}")
            return {
                "status": "error",
                "tool_name": tool_name,
                "output": f"Tool '{tool_name}' is not available in this scenario.",
            }
