---
title: Lifecycle Hooks Reference
description: Detailed reference for all available MultiAgentEval plugin lifecycle hooks.
---

Hooks are the primary way to inject logic into the evaluation engine. All hooks are synchronous unless specified otherwise.

## 🏁 Global Lifecycle

### `before_evaluation(self, context)`
- **Trigger**: Before the scenario begins.
- **Context**: `EvaluationContext`
- **Use Case**: Initialize plugin-specific metrics, reset external state, or register dynamic rubrics.

### `after_evaluation(self, context)`
- **Trigger**: After the final task is complete and metrics are calculated.
- **Context**: `EvaluationContext`
- **Use Case**: Export custom results, cleanup resources, or notify external systems.

## 🔄 Turn Lifecycle

### `on_agent_turn_start(self, context)`
- **Trigger**: Before the harness calls the agent.
- **Context**: `TurnContext`
- **Use Case**: Log the outgoing prompt, inject custom telemetry headers, or modify the user instruction.

### `on_turn_end(self, context)`
- **Trigger**: After the agent action is processed (including tool calls).
- **Context**: `TurnContext`
- **Use Case**: Analyze agent response timing, capture agent-side metadata, or update state trackers.

## 🛠️ Tool & Environment

### `on_tool_request(self, context, tool_name, args)`
- **Trigger**: When an agent attempts to call a tool.
- **Return Value**: `bool` (Return `False` to block the call).
- **Use Case**: Implement security guardrails (e.g., prevent PII exposure), log specific tool parameters, or enforce rate limits.

### `on_tool_result(self, context, tool_name, result)`
- **Trigger**: After a tool simulator returns a result.
- **Use Case**: Track "Grounding Hits" for RAG analysis or modify the tool result before the agent sees it.

## 🛡️ Error & Debugging

### `on_error(self, context, exception)`
- **Trigger**: When an unhandled exception occurs in the engine or another plugin.
- **Use Case**: Log errors to a centralized monitoring system (e.g., Sentry) or perform emergency state cleanup.

## 🖥️ UI & CLI Extensions

### `on_register_commands(self, registry)`
- **Trigger**: During CLI initialization.
- **Use Case**: Add custom subcommands under `multiagent-eval plugin`.

### `on_register_console_routes(self, app, nav_registry)`
- **Trigger**: When the Visual Suite (Flask) server starts.
- **Use Case**: Inject custom REST API routes or add tabs to the React dashboard sidebar.

### `on_discover_adapters(self, registry)`
- **Trigger**: When the engine initializes communication protocols.
- **Use Case**: Register custom agent adapters (e.g., `my-agent://`).
