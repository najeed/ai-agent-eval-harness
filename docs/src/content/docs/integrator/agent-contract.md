---
title: Agent Interaction Contract & Envelope Protocol
description: Authoritative specification for communication contracts between the AgentV evaluation engine and agent implementations.
---

AgentV separates the remote application's wire payload from the evaluation
context retained inside the harness. Your endpoint receives only the configured
application request; it must not depend on undocumented harness metadata.

## HTTP request

Use `--protocol http --agent http://localhost:8000/execute_task`. The default POST
body is:

```json
{"task_description": "Verify applicant KYC documents."}
```

The default wire body does not include run IDs, turn counters, history, available
tools, or span metadata. `AgentAdapterRegistry` retains history, input payload,
metadata and tracing context separately in `AdapterInvocationContext`; native
provider/framework adapters can opt into that context. HTTP headers and body
fields are separate protocol concerns.

For an application-specific request shape, configure `metadata.payload_template`.
For example, this metadata fragment maps the current task to an `input` field:

```json
{"payload_template": {"input": "{task_description}"}}
```

Templates support `{task_description}`, `{input_payload}`, `{node_id}` and
`{run_id}` substitutions. Supply identity values explicitly where your integration
requires them; the default `TurnContext` does not promise every optional template
identity. An exact `{input_payload}` value preserves the input object's type.
The OpenAPI adapter also supports operation-specific input payloads.

## Action responses

Single tool requests must use `tool_name`. Accepted parameter fields are
`tool_params`, `parameters`, or `params`, in that order. Prefer `tool_params`:

```json
{
  "action": "call_tool",
  "tool_name": "fetch_applicant_kyc",
  "tool_params": {"applicant_id": "APP-98214"}
}
```

For multiple calls, use `tool_calls` with `tool`/`params` (or
`tool_name`/`tool_params`). Dependency ordering can constrain parallel execution:

```json
{
  "action": "call_multiple_tools",
  "tool_calls": [
    {"tool": "fetch_applicant_kyc", "params": {"applicant_id": "APP-98214"}},
    {"tool": "check_credit_score", "params": {"applicant_id": "APP-98214"}}
  ]
}
```

Complete a conversation with:

```json
{"action": "final_answer", "summary": "Underwriting assessment completed."}
```

`completed` also terminates the turn loop. `processing` continues it; `error`
reports failure. A final answer starts evaluation of the declared assertions;
it does not automatically issue a certificate.

An agent may request human review with:

```json
{"action": "hitl_pause", "prompt": "Review this transfer before proceeding."}
```

For a durable pause, use the runtime-issued approval token and checkpoint from
the persisted approval request. Do not treat an arbitrary agent-supplied token
as authorization. Resume with:

```bash
agentv hitl-resume --run-id RUN_ID --approval-token TOKEN --decision APPROVED
```

See [interaction lifecycle](/integrator/interaction-lifecycle/) for scope and
resumption requirements.

## Tool feedback and history

The session records agent responses as `role: "agent"` with the action envelope
inside `content`, and tool outputs as `role: "environment"`. A message does not
necessarily contain an `identity` field. Tool results update the next task
message. HTTP integrations needing a full conversation must explicitly define
their application contract; `conversation_history` is not automatically added
to the wire body. Native adapters translate retained context to their framework.

Scenario tools execute through the harness sandbox. Self-reported external tool
results are a different evidence class and cannot establish sandbox-authoritative
or independently observed state.

## External execution receipts

Autonomous agents can return `execution_receipt.steps` containing `tool`,
`arguments`, `result`, and optional `result_summary`. The session records
`external_tool_call` / `external_tool_result` with
`source="external_agent_telemetry"`, `provenance="reported"`, and a canonical
SHA3-256 `receipt_hash`. These observations remain self-reported; certification
requires the declared independent state/oracle evidence where applicable.

## Local subprocess and sockets

The local adapter starts a subprocess for each invocation, writes one JSON
request to stdin, closes stdin, and reads one JSON response from stdout. Keep
diagnostics on stderr:

```bash
agentv run --path industries/finance/scenarios/loan_approval_risk_check.json --protocol local --agent "python my_agent.py"
```

The socket adapter opens a connection per invocation and exchanges bounded JSON
messages. Accepted addresses include `tcp:host:port`, `host:port`, bracketed IPv6,
and `unix:/path/to/socket`:

```bash
agentv run --path industries/finance/scenarios/loan_approval_risk_check.json --protocol socket --agent tcp:127.0.0.1:9099
```

Use `evaluate` for ordinary scenario directories and `run` for a file/catalog ID.
