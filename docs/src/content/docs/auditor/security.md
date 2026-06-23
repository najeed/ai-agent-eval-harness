---
title: Security & Authentication
description: Industrial-grade security standards, authentication protocols, and NIST AI-100-1 alignment.
---

AgentV is **Secure-by-Design**. It protects evaluation infrastructure and data veracity using a multi-layered security model including mandatory API keys, sandbox isolation, and NIST-aligned trustworthiness metrics.

## 🔑 The `DASHBOARD_API_KEY`

The `DASHBOARD_API_KEY` is a mandatory credential required for all protected REST API routes and the [Integrated Console](/extender/api-reference/).

### Generating a Secure Key
```bash
# Using Python (Native)
python -c "import secrets; print(secrets.token_hex(32))"
```

### Configuration
Set the key in your environment or a `.env` file:
```ini
DASHBOARD_API_KEY=7f8e3a2b1c9d0e5f...
```

### Usage in API Requests
Pass the key in the `X-AES-API-KEY` header for all requests to the `/api/` namespace.
```bash
curl -X POST http://localhost:5000/api/evaluate \
     -H "X-AES-API-KEY: your_secure_key" \
     -d '{"path": "scenarios/my_scenario.json"}'
```

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

1. **Behavioral Fingerprinting**: Uses **SHA-256** content hashing to sign raw `.jsonl` trace files.
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
