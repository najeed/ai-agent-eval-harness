# Authentication & Authorization Architecture

This document provides a single source of truth for platform engineers, DevSecOps evaluators, and system integrators deploying and operating AgentV and the Visual Console.

---

## 1. Overview of Authentication Pillars

AgentV enforces authentication and authorization across three distinct layers depending on the request origin and integration boundary:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        AgentV Ingress Boundaries                        │
├────────────────────────────┬────────────────────────────┬───────────────┤
│ 1. Web UI / Visual Console │ 2. CI/CD & API Integrations │ 3. Extensions │
│    (Session PBAC)          │    (Bearer / API Key)      │    (JWT)      │
├────────────────────────────┼────────────────────────────┼───────────────┤
│ Flask Session Cookie       │ Authorization: Bearer <key>│ X-Handoff-    │
│ RBAC / Permission Bitset   │ X-API-Key: <key>           │ Token: <JWT>  │
│ require_permission(...)    │ provider.authenticate(...) │ Capability    │
│                            │                            │ Gating        │
└────────────────────────────┴────────────────────────────┴───────────────┘
```

---

## 2. Pillar 1: Session-Based PBAC (Visual Console)

### Mechanism
- Used for interactive operator sessions in the Visual Console.
- On login via `/api/auth/login`, credentials authenticate against the active `AuthorizationBackend` (default: `StaticKeyProvider` / `SimpleAPIKeyAuthBackend`).
- On successful authentication, a cryptographically signed cookie session (`session["user"]`) is established.

### Session Security & Hardening
- **HTTP-Only Enforcement**: `SESSION_COOKIE_HTTPONLY = True` prevents client-side JavaScript access, neutralizing session hijacking via XSS.
- **CSRF Mitigation**: `SESSION_COOKIE_SAMESITE = "Lax"` isolates cookies from cross-site request contexts.
- **Transport Security**: `SESSION_COOKIE_SECURE = True` is enforced automatically in production (`AGENTV_ENV=production`), requiring TLS/HTTPS.
- **IP Rate Limiting**: The `/api/auth/login` endpoint enforces a thread-safe sliding-window rate limiter:
  - Threshold: 10 failed attempts within a 60-second window per remote IP.
  - Exceeding the threshold immediately yields `HTTP 429 Too Many Requests`.

### Non-Blocking Unauthenticated Experience & RBAC
- **Default Viewer Role**: Unauthenticated operators receive an implicit read-only `Viewer` role.
- **Exploration Without Lockout**: Viewers can inspect scenarios, completed runs, debugger DAGs, and trust artifacts without a blocking modal.
- **Mutation Boundary**: Any write or privileged action (running tests, modifying scenarios, changing lifecycle states, resolving HITL approvals) triggers the dismissable `LoginModal`.

### Route Protection
Protected console routes apply `@require_permission(Permission.<NAME>)`:
- `Permission.RUNS_READ` / `Permission.RUNS_WRITE`
- `Permission.SCENARIOS_READ` / `Permission.SCENARIOS_WRITE`
- `Permission.CERTIFY_WRITE`
- `Permission.HITL_RESOLVE`
- `Permission.SYSTEM_ADMIN`

```python
from eval_runner.console.auth_manager import require_permission, Permission


@app.route("/api/v1/runs/<run_id>/terminate", methods=["POST"])
@require_permission(Permission.RUNS_WRITE)
def terminate_run(run_id): ...
```

---

## 3. Pillar 2: Header / Bearer API Key Authentication (CLI & CI/CD)

### Mechanism
- Used for programmatic pipelines, CI/CD runners, and headless automation.
- Supports both standard header formats:
  - `Authorization: Bearer <API_KEY>`
  - `X-API-Key: <API_KEY>` / `X-AES-API-KEY: <API_KEY>`
- Resolved via `eval_runner.console.auth.get_current_user()` and verified by `AuthorizationBackend`.

### Zero-Config Bootstrap Authentication (Local Development)
To eliminate developer onboarding friction while maintaining strict RBAC integrity:
- If no `DASHBOARD_API_KEY` or `SERVICE_API_KEY` is defined in non-production environments:
  1. The server generates a high-entropy 32-byte secret via `secrets.token_urlsafe(32)`.
  2. The key is saved to `.aes/keys/bootstrap.key` (with `0600` file permissions on POSIX systems).
  3. The key is clearly logged in the terminal startup banner for operator access.
  4. The generated key is bound to `config.SERVICE_API_KEY` and `config.DASHBOARD_API_KEY`.
- Subsequent console restarts automatically load the existing key from `.aes/keys/bootstrap.key`.

### Production Key Enforcement
In production environments (`AGENTV_ENV=production`):
- `DASHBOARD_API_KEY`, `SERVICE_API_KEY`, or `JWT_SECRET` must be explicitly configured in the environment.
- Bootstrap key auto-generation and fallback to random ephemeral keys are strictly forbidden. The server fails fast and raises a `RuntimeError` at boot if production keys are missing.

---

## 4. Pillar 3: Scoped Extension Handoff Tokens (Micro-Frontends & Plugins)

### Mechanism
- Used when bridging the Visual Console to sandboxed extension panels, remote components, or external verification micro-services.
- An authenticated user requests a short-lived, audience-bound handoff token from `/api/auth/handoff?plugin_id=<ID>`.
- The token is a signed HS256 JWT containing:
  - `sub`: User ID / Principal
  - `aud`: `agentv-plugin`
  - `plugin_id`: Target extension / plugin identifier
  - `scope`: `console-handoff`
  - `exp`: 15 minutes (900 seconds)
  - `jti`: Unique token nonce

### Verification & Capability Boundary Status
- **Server Enforcement**: Provided via `eval_runner.console.auth.handoff_required` — a published route decorator that extensions apply to their own routes. It validates `X-Handoff-Token` or `?token=` parameter for audience (`agentv-plugin`), signature, and expiration against `JWT_SECRET`. OSS-internal routes do not use this decorator because the OSS layer does not host extension-owned endpoints; the decorator is part of the **extension API contract** consumed by the enterprise control plane and other micro-frontends.
- **Client Manifest Capabilities**: Extension declared capabilities (e.g. `canCallHostApi`, `canReadRuns`) and Subresource Integrity (SHA-384 SRI) are currently validated client-side by the Extension Host module loader upon importing signed plugin manifests.
- **Open Architectural Decision (Iframe & Realm Isolation)**:
  - *Current OSS Boundary*: Remote components are dynamically loaded as ECMAScript modules (ESM) into the host realm, gated by cryptographic signature and SRI verification.
  - *Target Boundary (v2.1+)*: Transitioning to cross-origin sandboxed `<iframe>` or ShadowRealm execution with structured `postMessage` RPC to prevent untrusted plugins from accessing host DOM, window storage, or memory.

---

## 5. Security & Trust Boundaries

| Layer | Mechanism | Cryptographic Primitive | Verification Boundary |
|---|---|---|---|
| **PQC Verification** | ML-DSA-65 / Falcon-512 | NIST FIPS 204 Post-Quantum | `TraceVerifier` & Flight Recorder |
| **Integrity Checks** | SHA-384 SRI | Subresource Integrity Digest | ESM Module & Asset Fetch |
| **Extension Trust** | Signed Manifests | Ed25519 / RSA Keyroot | Extension Host & SRI Gating (Client Verified) |
| **Runtime Sessions** | Flask Session Cookies | itsdangerous / HMAC-SHA256 | Console Web Gateway |
| **Plugin Handoff** | Scoped JWTs | HMAC-SHA256 (Audience Bound) | `/api/auth/handoff` & `@handoff_required` |


---

## 6. Environment Configuration Reference

| Environment Variable | Description | Default / Production Behavior |
|---|---|---|
| `AGENTV_ENV` | Runtime environment (`development`, `production`, `testing`) | Defaults to `development`. In `production`, requires explicit secrets. |
| `DASHBOARD_API_KEY` | Master API Key for console administrative operations | Auto-generated in dev at `.aes/keys/bootstrap.key`; must be set in `production`. |
| `SERVICE_API_KEY` | API Key for headless engine service automation & CI/CD | Synced with `DASHBOARD_API_KEY` by default; required in `production`. |
| `JWT_SECRET` | Secret key for signing console sessions and handoff JWTs | Falls back to `DASHBOARD_API_KEY` or fails in `production`. |
| `EVAL_SIGNING_KEY` | Ed25519 private key path for Flight Recorder trace signing | Required when `EVAL_REQUIRE_SIGNING=true`. |
| `DEV_PERSONA_SIMULATOR` | Enables local loopback persona switching for UI dev | Ignored in `production`. |
