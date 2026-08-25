# Agent Targets Specification — Exhaustive Guide

**Registry:** `.aes/agent_targets.json` · **Schema:** `agent-targets.schema.json` · **API:** `/api/v1/agent-targets*` · **Version:** 1.0.0 (additive-only within 1.x)

Companion: TS mirror `ui/visual-console/src/types/agent-target.ts`; REST implementation `eval_runner/console/routes/agent_targets.py`.

---

## 1. Purpose & doctrine

An Agent Target is a **reusable connection profile**: connect once, verify reachability server-side, then reference the same entity from any scenario launch. Doctrine:

- **No implicit targets.** `endpoint` is required; the harness never assumes localhost.
- **No secrets, ever.** Any request field whose name matches credential patterns (`api_key`, `authorization`, `token`, `secret`, `password`, `credential`) is rejected with HTTP 400 before persistence. Auth stays environment-side at run time.
- **Truthful reachability.** Tiers are only ever reported from an actual probe result; an untested target is CONFIGURED at best.

## 2. Registry document

```json
{
  "schema_version": "1.0.0",
  "targets": {
    "<id>": { "...Target": "" }
  }
}
```

- Location: `<PROJECT_ROOT>/.aes/agent_targets.json` (override: env `AGENT_TARGETS_PATH`).
- Writes are atomic (`tmp` + replace) under a process-wide lock.
- Unreadable/corrupt file ⇒ empty registry + WARN log (fail-open read is safer than bricking the console; writes then rebuild a valid file).

### Target fields

| Field | Req | Constraints |
|---|---|---|
| `id` | ✔ | Slug `^[a-z0-9][a-z0-9._-]{0,63}$`; server-generated from name (+suffix on collision) or client-supplied matching the same rule. |
| `name` | ✔ | Non-empty display name. |
| `protocol` | ✔ | One of: http_rest, http, sse, ollama, openai, anthropic, claude, gemini, custom_http, grpc, in_process, local. |
| `endpoint` | ✔ | Absolute `http(s)://…`. Schemes other than http/https rejected at validation AND at probe time (defense in depth). |
| `model` | – | Provider model identifier. |
| `max_turns` | – | 1..100 (default 10). |
| `timeout_seconds` | – | 5..600 (default 60). |
| `created_at` / `updated_at` | ✔ | ISO-8601; `updated_at ≥ created_at`; updates preserve `created_at`. |

## 3. REST surface

| Method & path | Permission | Behavior |
|---|---|---|
| `GET /api/v1/agent-targets` | scenarios:read | `{schema_version, targets:[…]}` sorted by name. |
| `GET /api/v1/agent-targets/<id>` | scenarios:read | Single target or 404. |
| `POST /api/v1/agent-targets` | scenarios:write | Upsert. Body = target fields (+optional `id`). Validation errors → 400 with explicit reason. Secrets → 400 with rejection naming the field. Returns the stored record (201). |
| `DELETE /api/v1/agent-targets/<id>` | scenarios:write | 200 `{status:"deleted"}` / 404. |
| `POST /api/v1/agent-targets/test` | scenarios:read | Probe an UNSAVED payload (wizard pre-save). |
| `POST /api/v1/agent-targets/<id>/test` | scenarios:read | Probe a saved target → `{id?, reachable, tier, latency_ms, message}`. |

## 4. Reachability tiers (truthful semantics)

| Tier | Meaning |
|---|---|
| `REACHABLE` | A real probe succeeded (HTTP <500 response counts — transport proven even on 4xx). |
| `CONFIGURED` | Structurally valid but not provable remotely: missing provider credential (checked FIRST, deterministically), or local/in_process execution mode. Never fabricated success. |
| `UNREACHABLE` | The probe actively failed: DNS error, refused connection, timeout, non-http(s) scheme. |

Probe order: credential check → scheme guard → DNS → HTTP GET (10s default, ≤4KB read, redirect-following disabled by policy of minimal trust).

## 5. Consumption

- Composer/wizard (`AgentTargetSelector`) lists saved targets above presets, runs per-target probes, saves/updates/deletes via the API, and maps a selected target onto launch config (`protocol/endpoint/model/max_turns/timeout`).
- Launch payloads carry these values explicitly; the runtime's no-implicit-target and execution_mode-consistency rules still apply downstream.

---

## Reference Walkthrough: Production Registry Document

```json
{
  "schema_version": "1.0.0",
  "targets": {
    "primary-agent": {
      "id": "primary-agent",
      "name": "Primary Agent (Production)",
      "protocol": "custom_http",
      "endpoint": "https://agents.acme.example.com/v1/dispatch",
      "model": "internal-orchestrator",
      "max_turns": 25,
      "timeout_seconds": 120,
      "created_at": "2026-08-21T09:14:03",
      "updated_at": "2026-08-24T16:40:11"
    },
    "local-deepseek-r1": {
      "id": "local-deepseek-r1",
      "name": "Local Ollama Fleet (DeepSeek-R1)",
      "protocol": "ollama",
      "endpoint": "http://localhost:11434/v1",
      "model": "deepseek-r1:70b",
      "max_turns": 15,
      "timeout_seconds": 90,
      "created_at": "2026-08-22T11:02:47",
      "updated_at": "2026-08-22T11:02:47"
    }
  }
}
```

Walkthrough notes:

- `primary-agent` was **updated** once (`updated_at > created_at`) — an upsert
  against the same `id` preserves `created_at` and refreshes only changed
  fields.
- `local-deepseek-r1` shows a never-updated target (`created_at ==
  updated_at`) and a dev-tier endpoint; its reachability probe would report
  tier from an actual loopback HTTP attempt, never assumed.
- Credentials appear nowhere in the document by construction: a POST body
  containing `"api_key": "sk-…"` is rejected with HTTP 400 before it can ever
  touch this file.
