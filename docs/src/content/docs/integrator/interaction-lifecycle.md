---
title: "Agent Interaction Lifecycle & Protocol Handshake"
description: "Integrator guide to multi-turn conversation cycles, tool calling protocols, HITL interventions, and runtime events."
---

# Agent Interaction Lifecycle & Protocol Handshake

When integrating an external agent framework (LangChain, LangGraph, CrewAI, AutoGen/AG2, or custom REST/WebSocket servers) with AgentV, the harness orchestrates execution through a standardized, multi-turn interaction cycle.

---

## 1. Interaction Sequence Diagram

```
Agent Adapter                 AgentV Harness                 Tool Sandbox / Environment
     │                              │                                     │
     │◄── routing_resolved ─────────┤ (Dynamic capability discovery)      │
     │                              │                                     │
     │                    ┌─────────┴─────────┐                           │
     │                    │  Node Turn Loop   │                           │
     │                    │  turn_start       │                           │
     │                    │  step_start       │                           │
     │                    └─────────┬─────────┘                           │
     │                              │                                     │
     │◄── Dispatch Prompt / History ┤                                     │
     │    (POST /turn or protocol)  │                                     │
     ├─────────────────────────────►│ Agent Response                      │
     │                              │                                     │
     │                 [Action: "call_tool"]                              │
     │                              ├─── tool_call ──────────────────────►│
     │                              │                                     │ Execute tool
     │                              │◄── tool_result ─────────────────────┤
     │                              │                                     │
     │                 [Action: "hitl_pause"]                             │
     │                              ├─── hitl_pause ───► (Await Operator) │
     │                              │◄── hitl_resume ── (Human Input)     │
     │                              │                                     │
     │                 [Action: "completed"]                              │
     │                              ├─── maneuver_end                     │
     │                              │    (State Parity + Oracles)         │
     │                              │                                     │
```

---

## 2. Protocol Handshake & Discovery

### Dynamic Capability Routing
If the scenario specifies required capabilities (e.g. `["streaming", "tools"]`), AgentV consults the `RoutingRegistry`:
1. Resolves protocol (`http`, `local`, `socket`, `stdio`) and endpoint URI.
2. Emits `routing_resolved` with `resolved_protocol` and `resolved_endpoint`.
3. Injects connection metadata into the attempt execution context.

### The Forensic Protocol Ledger (`step_start`)
At the start of every turn, before calling the agent adapter, AgentV emits:
```json
{
  "event": "step_start",
  "step": "http",
  "timestamp": "2026-09-12T05:00:00.000000Z"
}
```
This produces a cryptographically tamper-evident audit trail of protocol transitions across attempts; immutable retention requires an external retention-enforcing ArtifactStore.

---

## 3. Tool Execution Protocol

When an agent requests environment modification or data retrieval:

1. **Agent Action**: The agent emits a tool call payload:
   ```json
   {
     "action": "call_tool",
     "tool": "transfer_funds",
     "arguments": {
       "recipient": "GB8937040044053201300",
       "amount": 5000,
       "currency": "USD"
     }
   }
   ```

2. **Harness Telemetry (`tool_call`)**:
   AgentV records the outgoing tool invocation to the trace:
   ```json
   {
     "event": "tool_call",
     "tool": "transfer_funds",
     "arguments": { "recipient": "GB8937040044053201300", "amount": 5000 },
     "call_id": "call_12345"
   }
   ```

3. **Policy Gate & Sandbox Execution**:
   - The `ToolSandbox` evaluates declared security policies (e.g. max transfer limits).
   - If denied, the tool execution is blocked and recorded in policy forensics.

4. **Telemetry Feedback (`tool_result`)**:
   The harness records the result before returning it to the agent:
   ```json
   {
     "event": "tool_result",
     "tool": "transfer_funds",
     "result": { "status": "success", "tx_id": "tx-9821" },
     "call_id": "call_12345"
   }
    ```

### External Tool Telemetry Receipts
When evaluating autonomous agents that invoke tools internally outside the harness (e.g. LangGraph, CrewAI):
- The agent embeds an `execution_receipt` with executed steps in its response envelope.
- AgentV ingests each step, emitting `external_tool_call` and `external_tool_result` events with `source="external_agent_telemetry"` and `provenance="reported"`.
- Each receipt is bound by a canonical RFC 8785 SHA3-256 hash (`receipt_hash`), ensuring complete evidentiary separation from sandbox-executed tools.

---

## 4. Human-in-the-Loop (HITL) Interventions & Resumption

For critical actions requiring explicit operator oversight:

1. **Agent Pause**: The agent responds with `action: "hitl_pause"`:
   ```json
   {
     "action": "hitl_pause",
     "prompt": "Authorization required: Transfer 5000 USD to external account.",
     "approval_token": "req_hitl_882910"
   }
   ```
2. **Engine Suspension (`approval_created` / `hitl_pause`)**:
   - AgentV halts turn execution and records the approval request in the configured `ApprovalStore`.
   - Emits `approval_created` and `hitl_pause` events.
   - Flushes the execution manifest to disk with `execution_status: "PAUSED_FOR_APPROVAL"` and snapshots `scenario_resolved.json`.
3. **Operator Resolution (`agentv hitl-resume` / Console)**:
   The operator reviews the paused run and submits a decision (`APPROVED` or `REJECTED`):
   ```bash
   agentv hitl-resume \
     --run-id run_fintech_2026_01 \
     --approval-token req_hitl_882910 \
     --decision APPROVED \
     --reviewer "compliance_officer_42" \
     --reason "Valid underwriting exemption granted"
   ```
4. **Monotonic Event Sequence Continuation (`is_resume=True`)**:
   - The engine reloads the existing run through its bound provider without overwriting evidence.
   - Reads provider events to compute `start_seq = max(_seq) + 1`, guaranteeing strictly monotonic sequence ordering.
   - Emits `approval_resolved` and `hitl_resume` with reviewer identity, decision, and rationale.
   - If approved, the agent turn loop resumes with operator feedback injected into context; if rejected, the turn loop aborts fail-closed with `POLICY_DENIED`.

---

## 5. Completing the Node

The turn loop terminates when:
- The agent returns `action: "completed"` or `action: "final_answer"`.
- Maximum turns (`max_turns`) are exhausted without completion (fails with `TIMEOUT`).
- The agent returns `action: "error"` or an unhandled exception occurs (fails with `NODE_EXECUTION_FAILURE`).
