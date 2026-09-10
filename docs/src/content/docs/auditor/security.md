---
title: Security & Authentication
description: Industrial-grade security standards, authentication protocols, and NIST AI-100-1 alignment.
---

AgentV is **Secure-by-Design**. It protects evaluation infrastructure and data veracity using a multi-layered security model including mandatory API keys, sandbox isolation, and NIST-aligned trustworthiness metrics.

## 🔑 Three-Pillar Authentication Architecture

AgentV enforces authentication and authorization across three distinct ingress boundaries:

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

### 1. Static API Keys (`DASHBOARD_API_KEY` & `SERVICE_API_KEY`)
- **`DASHBOARD_API_KEY`**: Authenticates administrative and operator sessions in the Visual Console.
- **`SERVICE_API_KEY`**: Dedicated token for headless CI/CD runners, automated testing pipelines, and programmatic API integrations.
- Set keys via environment variables:
  ```ini
  DASHBOARD_API_KEY=7f8e3a2b1c9d0e5f...
  SERVICE_API_KEY=svc_9a1b2c3d4e5f60...
  ```
- Send via `X-API-Key` or `Authorization: Bearer <key>` headers in HTTP API requests.

### 2. Zero-Config Bootstrap Authentication
To prevent accidental lockouts while eliminating insecure hardcoded defaults:
- **First-Boot Key Generation**: If no secret key is configured in non-production environments (`AGENTV_ENV != production`), AgentV automatically generates a cryptographically secure 64-character SHA3-256 session key and saves it to `.aes/keys/bootstrap.key`.
- **Production Guardrail**: In production environments (`AGENTV_ENV=production`), missing cryptographic secret keys trigger an immediate fail-fast `RuntimeError`, preventing insecure ephemeral startups.

### 3. Session Security & Rate Limiting
- **Cookie Flags**: Flask sessions enforce `SESSION_COOKIE_HTTPONLY=True` (mitigating XSS session hijacking), `SESSION_COOKIE_SAMESITE="Lax"` (mitigating CSRF), and `SESSION_COOKIE_SECURE=True` in production.
- **Sliding-Window IP Rate Limiting**: The `/api/auth/login` endpoint enforces a thread-safe sliding-window rate limit (maximum 10 failed attempts per 60-second window per remote IP) returning HTTP 429 upon threshold breach.
- **Default Viewer Role**: Unauthenticated visitors are assigned a read-only `Viewer` role, permitting exploration of runs, DAGs, and traces without a disruptive blocking modal. Mutations and privileged actions cleanly trigger authentication.

For in-depth security implementation details, review the [Authentication Architecture Specification](/spec/trust_v3/).

---

## 🛡️ Industrial Hardening

### 1. Network & SSRF Protection
The harness implements IP-level validation to prevent **Server-Side Request Forgery (SSRF)**.
- **Forbidden Endpoints**: Loopback (`127.0.0.1`), link-local (`169.254.x.x`), and private subnets are blocked.
- **Cloud Metadata Security**: Access to provider metadata (e.g., AWS IMDSv2) is strictly neutralized.

### 2. File Jail Control (`AEH_STRICT_JAIL`)
- **Default (Standard)**: Allows file access within `PROJECT_ROOT` and system temporary directories for CI/CD flexibility.
- **Strict (Hardened)**: Set `AEH_STRICT_JAIL=1` to enforce an absolute, project-only jail, blocking access to all external directories.

---

## ⚖️ NIST AI-100-1 Alignment

As of **April 2026**, the harness is aligned with the **NIST AI-100-1** trustworthiness framework.

### Weighted Severity Model (WSM)
Aggregate scores are calculated based on NIST's risk-based prioritization:

| Dimension | Weight | NIST Alignment |
| :--- | :--- | :--- |
| **Safety** | 25% | Protection against physical/psychological harm. |
| **Security** | 20% | Resistance to adversarial attacks/exfiltration. |
| **Reliability** | 20% | Consistency in mission-critical tasks. |
| **Fairness** | 15% | Mitigation of algorithmic bias. |

### The Regulatory "Safety Floor"
If foundational **Safety** or **Security** scores fall below **0.5**, the aggregate trustworthiness index is automatically capped at **0.49 (Fail)**, regardless of performance in other categories.

---

## 📑 Trust Protocol Fingerprinting

The [Trust Protocol](/auditor/trust-protocol/) provides immutable proof of run integrity.

1. **Behavioral Fingerprinting**: Uses **SHA3-256** content hashing to sign raw `.jsonl` trace files.
2. **Certification API**: Serves as a public "Trust Anchor" for external CI/CD gates via `GET /v1/certificates/<run_id>`.
3. **HMS-Ready**: Supports **AWS KMS**, **GCP KMS**, and **Azure Key Vault** for private key storage, ensuring keys never reside on the local evaluation disk.

---

## 🛡️ Headless Architecture (The API First Approach)

While the [Integrated Console](/extender/api-reference/) provides a high-fidelity visual interface, AgentV is built as a **Headless Engine**. This allows enterprises to integrate the harness into their own proprietary portals or SOC (Security Operations Center) workflows.

### 1. The Global REST Fabric
Every core function (Evaluation, Triage, Certification) is exposed via the Namespace API (`/api/v1/`). 
- **Statelessness**: The engine remains stateless; scenario state is passed via JWTs in the `Secure Handoff` protocol.
- **Async-by-Default**: Long-running evaluations return a `202 Accepted` with a `TaskID` for status polling.

### 2. PBAC (Permission-Based Access Control)
Industrial environments require granular control over who can perform which forensic action. AgentV implements a **Middleware-First PBAC** model.

| Role | Permissions |
| :--- | :--- |
| **`VIEWER`** | Read scenarios, browse completed runs, export JSONL. |
| **`AUDITOR`** | Verify certificates, sign runs (with key access), read audit manifests. |
| **`OPERATOR`** | Launch evaluations, manage shims, refresh catalogs. |
| **`SUPERVISOR`** | Full registry control, identity management, PBAC configuration. |

---

## 🔐 Enterprise SSO & OIDC Authentication

AgentV supports out-of-the-box **OAuth2/OIDC JWT Bearer Token validation** alongside its standard static API keys. This enables seamless integration with identity providers like Okta, Azure AD, or Keycloak.

### ⚙️ Configuration Properties
The OIDC layer is configured using the following environment variables:

| Environment Variable | Purpose | Example Value |
| :--- | :--- | :--- |
| `OIDC_JWKS_URL` | The JSON Web Key Set URL to fetch public signing keys. | `https://auth.example.com/.well-known/jwks.json` |
| `OIDC_ISSUER` | Optional. Issuer (`iss`) claim to validate in the JWT. | `https://auth.example.com` |
| `OIDC_AUDIENCE` | Optional. Audience (`aud`) claim to validate in the JWT. | `agentv-service` |
| `OIDC_JWKS_CACHE_TTL` | Cache TTL in seconds for public keys (Default: `3600`). | `3600` |

### 🛡️ Token Validation & Hardening Guardrails
1. **Dynamic JWKS Caching**: The core validation engine caches and reuses `PyJWKClient` instances, preventing redundant network round-trips to key servers and mitigating rate-limiting or DDoS vectors.
2. **Clock-Skew Tolerance**: Incorporates a 10-second validation `leeway` to accommodate minor clock synchronization differences between servers.
3. **Multi-Algorithm Filtering**: Restricts signatures to safe cryptographic configurations (`RS256`, `RS384`, `RS512`, `ES256`, `ES384`, `ES512`) during decode.
4. **Granular PBAC Mapping**: Token scopes (`scope`), roles (`roles`), or custom permissions arrays are parsed to map standard or custom granular permission nodes (e.g. `scenarios:read`).

### 📡 Request Header Extraction
Credentials are extracted using a decoupled, case-insensitive helper which supports:
- `Authorization: Bearer <JWT>` headers.
- `X-AES-API-KEY` or `X-API-Key` custom headers (matched case-insensitively).
- `apiKey` URL query parameters.

For custom authentication mappings, plugins can subclass `AuthManager` using the [Plugin System](/extender/plugins/).

---

## 🏛️ SOC 2 Type 1 Trust Services Criteria (TSC) Mapping

AgentV incorporates continuous governance controls directly aligned with AICPA SOC 2 Type 1 Trust Services Criteria:

| SOC 2 TSC Category | Control Identifier | AgentV Architectural Control | Verification Artifact |
| :--- | :--- | :--- | :--- |
| **Common Criteria 6.1 (Logical Access)** | `CC6.1.1` | Granular PBAC/RBAC validation via `AuthorizationBackend` and `AuthPrincipal`. | Route-level permission gates (`@require_permission`). |
| **Common Criteria 6.3 (Least Privilege)** | `CC6.3.2` | Workspace isolation, terminal jail sandboxing, and non-root execution boundaries. | `is_path_safe` path safety enforcement. |
| **Common Criteria 6.6 (Boundary Protection)** | `CC6.6.1` | SSRF IP blocklists, cloud metadata (IMDSv2) access neutralization, and local subnet isolation. | Network security tests in `tests/security/`. |
| **Common Criteria 6.7 (Data Transmission & Signing)** | `CC6.7.3` | Asymmetric Ed25519 trace signing with SHA3-256 digests and Fail-Closed Cryptography. | Verifiable Credentials (VC v3.0.0) generated via `TraceVerifier`. |
| **Common Criteria 7.2 (Security Monitoring)** | `CC7.2.1` | Real-time audit logging via `FlightRecorder` with SHA3-256 fingerprinting and telemetry event bus. | Immutable `run.jsonl` trace vaults. |
| **Common Criteria 8.1 (Change & Config Management)** | `CC8.1.1` | Schema-validated `ResolvedRuntimeConfig` model with deterministic `config_hash`. | Sealed configuration snapshots per evaluation run. |

