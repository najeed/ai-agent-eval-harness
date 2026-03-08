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
    In-process mock tool executor with state persistence.

    Given a scenario, it knows which tools are valid and maintains
    an internal state that can be mutated by tool calls.
    """

    def __init__(self, scenario: dict):
        """
        Initialize the sandbox with the scenario's tool inventory and initial state.

        Args:
            scenario (dict): The loaded scenario data.
        """
        self.known_tools = set()
        for task in scenario.get("tasks", []):
            for tool in task.get("required_tools", []):
                self.known_tools.add(tool)

        # Initialize internal state from scenario
        self.state = scenario.get("initial_state", {}).copy()

        # Initialize policies from scenario
        self.policies = scenario.get("policies", {})

    def execute(self, tool_name: str, params: dict = None) -> dict:
        """
        Execute a mock tool call, enforce policies, and update internal state if applicable.

        Args:
            tool_name (str): Name of the tool the agent wants to call.
            params (dict): Parameters the agent passed to the tool.

        Returns:
            dict: A mock result with status, tool_name, and updated state or policy violation info.
        """
        if params is None:
            params = {}

        if tool_name not in self.known_tools:
            print(f"      [Sandbox] Unknown tool requested: {tool_name}")
            return {
                "status": "error",
                "tool_name": tool_name,
                "output": f"Tool '{tool_name}' is not available in this scenario.",
            }

        # --- POLICY ENFORCEMENT LOGIC ---
        if self.policies and tool_name in self.policies:
            policy = self.policies[tool_name]
            print(f"      [Sandbox] Checking policy for {tool_name}: {policy}")

            # For telecom scenarios (Milestone 2 test)
            amount = params.get("amount")
            if "max_limit" in policy and amount is not None:
                print(f"      [Sandbox] Validating amount {amount} against limit {policy['max_limit']}")
                if amount > policy["max_limit"]:
                    print(f"      [Sandbox] Policy violation: {amount} > {policy['max_limit']}")
                    return {
                        "status": "policy_violation",
                        "tool_name": tool_name,
                        "violation": f"Amount {params['amount']} exceeds maximum allowed limit of {policy['max_limit']}.",
                        "params_received": params
                    }

        print(f"      [Sandbox] Executing mock tool: {tool_name}({params})")

        # --- STATE MUTATION LOGIC ---
        # In a real system, this would be handled by specific tool implementations.
        # For the harness, we use a generic 'update' heuristic.
        output_msg = f"Mock result for {tool_name}"

        if tool_name.startswith("update_") or tool_name.startswith("set_"):
            for key, value in params.items():
                if key in self.state or len(self.state) < 20: # Allow adding new keys if state is small
                    self.state[key] = value
            output_msg = f"Successfully updated state via {tool_name}"

        return {
            "status": "success",
            "tool_name": tool_name,
            "output": output_msg,
            "params_received": params,
            "current_state": self.state
        }
