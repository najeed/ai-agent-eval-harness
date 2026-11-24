---
title: "Event Lifecycle & Chronological Emission Specification"
description: "Authoritative specification of the AgentV trace event lifecycle, emission sequence, and forensic invariants across system personas."
---

Execution events belong to the scoped RunStorageProvider. Optional telemetry and
certificate publication must not extend a completed execution stream.

## Execution order

1. `run_start`, `strategy_start` and `phase_start` establish run and attempt context.
2. `routing_resolved` records target selection. Workflow graph node events track
   activation and execution instances.
3. Node maneuvers emit subtask/turn/protocol events, tool activity and observed
   oracle outcomes. Sibling branches may execute concurrently in isolated forks;
   deterministic merge and edge events record their control flow.
4. Phase/strategy telemetry finishes before terminal `run_end`, which contains
   evaluator finalization. `run_end` is the final execution event.
5. A separate certification transaction verifies evidence and commits the
   certificate and sealed provider lifecycle together. It does not append a
   `verification_certificate_issued` or `trace_sealed` event to the terminal trace.

## Tool events

Single tool request:

```json
{"action": "call_tool", "tool_name": "transfer_funds", "tool_params": {"amount": 25}}
```

Session `tool_call` carries `step`, `tool`, `arguments`, `provenance`;
`tool_result` carries `step`, `tool`, `result`, `provenance`. These are not a
guarantee of `call_id` fields. Sandbox provenance is distinct from external
receipts, which emit `external_tool_call`/`external_tool_result` with reported
source and a canonical receipt digest. Self-reporting does not authenticate
external state changes.

## Durable approval order

The approval manager persists `ApprovalRequest` and emits `approval_created`
while the provider is still writable. The session then emits `hitl_pause` and
transitions to `PAUSED_FOR_APPROVAL`.

Approval events serialize the request: `approval_token`, `run_id`, `turn_index`,
`outbound_payload_hash`, checkpoint/action metadata, `status`, `scope`,
`scope_digest`, `manifest_id` and idempotency information. Resolution uses
`APPROVED`/`REJECTED`, `decided_by`, `decision_reason` and timestamps. Durable pause
payloads contain the approval token/checkpoint; interactive HITL payloads can
differ. Do not treat a fixed `approval_id`/lower-case decision sample as universal.

```bash
agentv hitl-resume --run-id RUN_ID --approval-token TOKEN --decision APPROVED --reviewer operator --reason "Reviewed bound action"
```

Use `--decision REJECTED` to reject. There are no built-in `resume`, `approve`
or `reject` top-level CLI commands. REST resume is
`POST /api/v1/runs/<run_id>/resume` with the route's authorization requirements.

Resume verifies scope, request, checkpoint and payload bindings, preserves the
original execution manifest/scenario snapshot and continues monotonic sequence
numbers. It cannot reopen sealed or terminal evidence as a new writable run.

## Evidence delivery and data handling

Required evidence consumers must acknowledge delivery; failures can invalidate
the run. Optional telemetry can run asynchronously; default event mode is
synchronous. Sanitization redacts selected secret patterns on presentation paths.
Mandatory evidence preserves exact committed objects and is not a universal
pre-persistence PII filter. PII analyzers diagnose histories, not every data sink.

## Finalization and independent verification

Terminal finalization commits to scenario/manifest identity, evidence root,
required oracle inventory, outcome, score and terminal sequence. Verify it with
the actual scenario, actual execution manifest and raw trace bytes. Current
artifact signatures use [digest envelopes](/spec/digest-signature-envelope/).
Missing/conflicting finalization, post-terminal execution events or failed
required evidence prevent authoritative certification. See
[verification](/auditor/verification/) and [interaction lifecycle](/integrator/interaction-lifecycle/).
