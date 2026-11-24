---
title: Agent Integration Guide
description: Step-by-step instructions for connecting your AI agents to the AgentV harness.
---

Expose an HTTP POST endpoint that accepts the configured application request and
returns an AgentV action response. The default request is:

```json
{"task_description": "Help me with my bill."}
```

A completion response is:

```json
{"action": "final_answer", "summary": "The billing issue has been resolved."}
```

For tools, use `action: "call_tool"`, `tool_name` and `tool_params`. Full history,
run IDs and tool schemas are not automatically included in the remote request.
Use the [agent contract](/integrator/agent-contract/) to configure custom payloads.

## Evaluate an HTTP service

Start your service first, then run:

```bash
agentv run --path industries/finance/scenarios/loan_approval_risk_check.json --protocol http --agent http://localhost:5001/execute_task
```

Use `evaluate` for a directory. Provider protocols such as `openai`, `claude`,
`gemini`, `grok` and `ollama` accept their documented model targets. Select
`--protocol` explicitly; supplying an agent URI alone does not select an adapter.

## Framework bindings

| Adapter | Native target | Remote target |
| --- | --- | --- |
| `langgraph` | Import path such as `my_module.graph:app` or `metadata.graph_path` | HTTP(S) LangGraph Server, with the required assistant configuration |
| `langchain` | `metadata.chain_path` for a Runnable | LangServe deployment |
| `ag2` | `metadata.agent_path` for an AG2 agent/factory | HTTP(S) A2A Agent Card service |
| `crewai` | `metadata.crew_path` for a Crew/factory | Use `http`/`openapi` for a custom remote wrapper |

Install the relevant framework dependencies before using a native binding. The
`framework-crewai` extra is currently empty; install a compatible CrewAI release
explicitly in an environment supported by that framework.

## Inspect and certify

```bash
agentv replay --run-id RUN_ID
agentv console
```

Authenticate before accessing protected console APIs. Execution and certification
are separate: undeclared execution mode defaults to simulated. Authoritative
certification needs declared eligible execution and independent evidence, a
configured signer and trusted verification inputs. Follow the
[verification workflow](/auditor/verification/) before using results as an
assurance claim.
