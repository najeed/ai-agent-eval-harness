---
title: "Agent Interaction Lifecycle & Protocol Handshake"
description: "Integrator guide to multi-turn conversation cycles, tool calling protocols, HITL interventions, and runtime events."
---

The runtime resolves a target, executes the node turn loop, evaluates assertions,
then finalizes the run. Certification is a separate operation after execution.

## Request and response cycle

1. Resolve protocol and endpoint from explicit configuration, capability routing,
   scenario metadata and global defaults. Record `routing_resolved`.
2. Emit `turn_start` and protocol `step_start`, then render the configured wire
   payload. The default HTTP body contains only `task_description`.
3. Receive an action. Execute `call_tool`/`call_multiple_tools` through the sandbox,
   continue on `processing`, or finish on `final_answer`/`completed`.
4. Evaluate the node's registered metrics and declared state assertions. Record
   graph outcomes and aggregate attempts into evaluator finalization.

See the [agent contract](/integrator/agent-contract/) for exact request fields,
parameter aliases and internal history roles.

## Sandbox events

A single tool request uses:

```json
{"action": "call_tool", "tool_name": "transfer_funds", "tool_params": {"amount": 5000}}
```

The session's `tool_call` event carries `step`, `tool`, `arguments` and
`provenance`; `tool_result` carries `step`, `tool`, `result` and `provenance`.
These session events do not promise a `call_id`. External receipts emit distinct
`external_tool_call` and `external_tool_result` events with reported provenance.

## Durable human approval

The approval manager binds a request to the run, outbound payload, checkpoint and
verified scope. It persists and emits `approval_created` before the session emits
`hitl_pause` and transitions the provider to `PAUSED_FOR_APPROVAL`. This preserves
the pause evidence while the trace is still writable.

Durable approval events serialize `ApprovalRequest`, including `approval_token`,
`run_id`, `turn_index`, `outbound_payload_hash`, `status`, `scope`, `scope_digest`,
`manifest_id`, checkpoint and decision metadata. Use the persisted token:

```bash
agentv hitl-resume --run-id RUN_ID --approval-token TOKEN --decision APPROVED --reviewer compliance_officer --reason "Reviewed the bound action"
```

`REJECTED` terminates the operation. Resolution verifies the request's scope and
payload/checkpoint bindings; a token alone does not bypass authorization.
`approval_resolved` records `APPROVED`/`REJECTED`, `decided_by`, `decision_reason`
and decision timestamps. Interactive HITL events can have a different payload
from this durable approval path.

Resumption preserves the provider-owned execution manifest and scenario snapshot,
continues event sequence numbers, and appends to the existing run. Terminal or
sealed runs cannot be resumed as writable evaluations.

## Completion and certification

`run_end` is the terminal execution event and includes evaluator finalization.
Required oracle, scenario, manifest and execution-truth checks determine whether
the result is eligible for [certification](/auditor/verification/). Conversation
completion or a self-reported external receipt is insufficient on its own.
