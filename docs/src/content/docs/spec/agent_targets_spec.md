---
title: "Agent Targets Specification"
description: "Authoritative specification for agent target definitions, connection protocols, and authentication schemes."
---

The persisted target registry follows
[agent-targets.schema.json](/spec/agent-targets/agent-targets.schema.json).
It is separate from CLI model URIs and native framework bindings.

## Registry shape

The root requires `schema_version: "1.0.0"` and `targets`, an object keyed by
target ID. Each target requires `id`, `name`, `protocol`, `endpoint`, `created_at`
and `updated_at`. Unknown fields are rejected.

```json
{
  "schema_version": "1.0.0",
  "targets": {
    "billing-agent": {
      "id": "billing-agent",
      "name": "Billing HTTP service",
      "protocol": "http",
      "endpoint": "http://localhost:8000/execute_task",
      "max_turns": 10,
      "timeout_seconds": 30,
      "created_at": "2026-11-24T00:00:00Z",
      "updated_at": "2026-11-24T00:00:00Z"
    }
  }
}
```

`endpoint` must be HTTP(S); there is no implicit default target. Optional fields
are `model`, `max_turns` (1–100) and `timeout_seconds` (5–600, integer).
The schema enumerates accepted protocol labels; a stored label does not install
an adapter or provision a remote service.

Secrets and `auth` objects are not accepted or persisted in target profiles.
Configure credentials through the runtime's environment/provider integration.
The REST layer also rejects credential-like field names. Do not store bearer
tokens in a target URL.

For direct provider URIs such as `openai://MODEL`, or an in-process
`module:attribute` binding, use the appropriate CLI adapter configuration instead
of inserting those values into this HTTP target registry.
