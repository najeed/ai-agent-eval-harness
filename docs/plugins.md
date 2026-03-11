# Plugin Development Guide

The AI Agent Evaluation Harness is built on a "Zero-Touch" core, meaning almost any functionality can be extended or modified via plugins without touching the core engine.

## Creating a Plugin

Plugins are Python classes that inherit from `eval_runner.plugins.BaseEvalPlugin`.

```python
from eval_runner.plugins import BaseEvalPlugin

class MyCustomPlugin(BaseEvalPlugin):
    def on_run_start(self, run_id, metadata):
        print(f"Starting run {run_id}!")

    def on_tool_request(self, tool_name, params, context):
        if tool_name == "sensitive_tool":
            return {"status": "blocked", "reason": "Security policy"}
        return None
```

## Lifecycle Hooks

| Hook | Arguments | Description |
|---|---|---|
| `on_run_start` | `run_id`, `metadata` | Triggered before the evaluation begins. |
| `on_run_end` | `results` | Triggered after all scenarios are completed. |
| `on_task_start` | `task_id`, `context` | Triggered before a specific task within a scenario. |
| `on_prompt` | `payload` | Allows modification of the request sent to the agent. |
| `on_agent_response` | `response` | Observe or log the agent's raw output. |
| `on_tool_request` | `name`, `params`, `context` | **Interception Point**. Return a result to bypass real execution. |
| `on_tool_result` | `result`, `context` | Observe the output of a tool call. |
| `on_discover_adapters` | `registry` | Register custom agent protocols (e.g., `grpc://`). |
| `on_eval_complete` | `task_results` | Last chance to modify scores or add triage tags. |
| `extend_cli` | `parser` | Add custom arguments to the `evaluate` command. |

## Registering Plugins

Plugins are automatically discovered if they are present in the `plugins/` directory of your project, or if they are explicitly registered in your `eval_config.json`.

```json
{
  "plugins": [
    "my_custom_module.MyCustomPlugin"
  ]
}
```

## Framework Adapters (Advanced)

Phase 4 introduced built-in support for extending agent communication protocols without touching the core engine. Using the `on_discover_adapters` hook, a plugin can register custom protocol schemes (e.g., `langgraph://`).

```python
from eval_runner.plugins import BaseEvalPlugin

class LangGraphAdapterPlugin(BaseEvalPlugin):
    def on_discover_adapters(self, registry):
        # Register the 'langgraph' protocol pointing to our handler func
        registry.register("langgraph", self.execute_langgraph_node)

    async def execute_langgraph_node(self, node_id: str, input_data: dict) -> dict:
        """Custom execution logic specific to LangGraph."""
        return {"action": "final_answer", "summary": "LangGraph Execution Complete."}
```
If this plugin is active, scenarios can now specify an agent URL like `langgraph://my_agent_node`, and the engine will seamlessly route the task to this adapter bypasssing standard HTTP mechanisms.
