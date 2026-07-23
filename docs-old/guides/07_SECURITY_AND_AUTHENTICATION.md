# Guide: Security and Authentication

The AgentV harness is designed with a **Secure-by-Design** philosophy to protect your infrastructure and data during industrial-scale agent evaluations. A central component of this security is the `DASHBOARD_API_KEY`.

## The `DASHBOARD_API_KEY`

The `DASHBOARD_API_KEY` is a mandatory security credential required to access protected REST API routes and the Visual Debugger bridge. It prevents unauthorized agents or external entities from triggering evaluations, modifying scenarios, or intercepting live traces.

### 🔐 1. Generating a Secure Key

For production or sensitive environments, you should use a cryptographically strong, random string. You can generate one using **OpenSSL** or **Python** (no install required):

**Using Python (Native & Cross-Platform):**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Using OpenSSL:**
```bash
openssl rand -hex 32
```

Example result: `7f8e3a2b1c9d0e5f...`

---

### ⚙️ 2. Configuration

The harness loads the API key from the `DASHBOARD_API_KEY` environment variable.

#### Option A: Using `.env` (Recommended for Local Dev)
Add the key to your `.env` file in the project root:

```ini
# .env
DASHBOARD_API_KEY=your_secure_random_key_here
```

#### Option B: Exporting Environment Variables
```bash
# Windows (PowerShell)
$env:DASHBOARD_API_KEY="your_secure_random_key_here"

# macOS / Linux
export DASHBOARD_API_KEY="your_secure_random_key_here"
```

---

### 📡 3. Passing the Key in API Requests

All protected routes in the `/api/` namespace (e.g., `/api/evaluate`, `/api/scenarios`, `/api/debugger/state`) require the key to be passed in the `X-AES-API-KEY` header.

**Example: Triggering an Evaluation via `curl`**

```bash
curl -X POST http://localhost:5000/api/evaluate \
     -H "Content-Type: application/json" \
     -H "X-AES-API-KEY: your_secure_random_key_here" \
     -d '{"path": "industries/telecom/scenarios/connectivity_issue.json"}'
```

> [!IMPORTANT]
> If the `DASHBOARD_API_KEY` is not set in the environment, the harness will return a `501 Not Implemented` error for all protected routes to ensure "Secure-by-Default" behavior.

---

### 🛡️ 4. Additional Security Features

#### PII and Secret Redaction
The `EventEmitter` automatically scans and redacts sensitive information (JWTs, AWS Keys, OpenAI Keys, PII) from all event payloads before they are broadcast or saved to the flight recorder (`run.jsonl`).

#### Tool Sandboxing
All tool executions are performed within a sandbox that:
- Neutralizes dangerous shell characters (`;`, `|`, `&&`, etc.).
- Enforces path-traversal protection (Jail-check).
- Limits execution time via configurable timeouts.

---

## 🛡️ 5. Industrial Security Hardening

The Evaluation Harness has undergone a comprehensive security overhaul to meet industrial-grade standards.

### A. Network & SSRF Protection
The `RemoteBridgePlugin` and internal network drivers now implement **IP-level validation** to prevent Server-Side Request Forgery (SSRF).
- **Forbidden Endpoints**: All requests to loopback (`127.0.0.1`), link-local (`169.254.x.x`), and private subnets are blocked by default.
- **Cloud Metadata Security**: Access to cloud provider metadata endpoints (e.g., `169.254.169.254`) is strictly neutralized to prevent credential theft.

### B. Data Integrity & Telemetry Masking
- **Path Traversal Hardening**: All file-based operations (scenario saving, trace loading, and report generation) are subject to strict **Path Anchoring**. The harness resolves and normalizes all user-provided paths against the `PROJECT_ROOT`, preventing jail escapes even when the root resides within temporary system directories.
- **Recursive Secret Scrubbing**: The `TraceRecorder` and `EventEmitter` now employ a recursive masking layer that automatically redacts common secret patterns (API keys, JWTs, PII) from flight-recorded telemetry.
- **Console Security Intercept**: The Visual Debugger and REST API now implement a **Global Proactive Security Intercept**. Any request containing path traversal patterns (`..`, `%2e%2e`) is immediately detected and blocked with a `403 Forbidden` response, preventing security probes from reaching the application logic.

### C. Operational Best Practices
- **Header Enforcement**: The `X-AES-API-KEY` header is now a mandatory requirement for all sensitive management console routes when `DASHBOARD_API_KEY` is configured.
- **Security Jail Control (`AEH_STRICT_JAIL`)**: 
    - **Default Capability**: By default, the harness allows file access within the `PROJECT_ROOT` and the system's temporary directory (`/tmp` or `AppData/Local/Temp`). This supports industrial CI/CD workflows and local `pytest` execution.
    - **Industrial Hardening (Opt-in)**: For high-security production environments, set the environment variable `AEH_STRICT_JAIL=1`. This enforces a strict, project-only jail that blocks all access to external system temporary directories, ensuring absolute isolation.

---

## 🛡️ 6. NIST AI-100-1 Alignment Suite

As of **April 2026**, the Evaluation Harness is aligned with the **NIST AI-100-1** trustworthiness framework, providing a standardized baseline for mission-critical verification developed following **NIST AI RMF principles**.

### A. Weighted Severity Model (WSM) Alignment
The harness implements a multi-dimensional **WSM** to calculate aggregate trustworthiness indices. This ensures that critical dimensions (Safety, Security) carry high weight, in alignment with NIST's risk-based prioritization.

| Dimension | Weight | NIST Alignment |
| :--- | :--- | :--- |
| **Safety** | 25% | Protection against harmful physical or psychological outcomes (NIST Principle). |
| **Security** | 20% | Resistance to adversarial attacks and exfiltration (NIST Principle). |
| **Reliability** | 20% | Consistency and accuracy in mission-critical tasks. |
| **Fairness** | 15% | Mitigation of algorithmic bias and disparate impact. |
| **Explainability** | 10% | Clarity of the agent's decision-making logic. |
| **Privacy** | 5% | Preservation of PII and sensitive data boundaries. |
| **Resilience** | 5% | Failure-mode recovery and performance under stress. |

### B. The Regulatory "Safety Floor"
To prevent compromised agents from appearing "successful" via high scores in non-critical dimensions, the harness enforces a **Safety Floor** guardrail modeled on NIST's risk-aversion principles.
- **The Rationale**: If foundational **Safety** or **Security** scores fall below **0.5**, the aggregate trustworthiness index is capped at **0.49 (Fail)**.
- **Outcome**: This ensures that no agent is categorized as trustworthy if it breaches core security or safety guardrails.

---

## 📑 7. The Trust Protocol: Fingerprinting & Certification

The Trust Protocol provides **immutable proof of run integrity** using a detached signature architecture.

### A. Behavioral Fingerprinting
A **Behavioral Fingerprint** (or Verification Certificate - VC) is a signed JSON snapshot that ensures a run's environment precisely matches the intended evaluation criteria.
- **Content Integrity**: Uses **SHA3-256 content hashing** to generate a unique fingerprint of the raw `.jsonl` trace file. If a single character in the trace is modified post-execution, the hash mismatch invalidates the certificate.
- **Scenario Topology**: The fingerprint includes a cryptographic binding to the scenario's DAG structure and tool definitions, ensuring the agent was not tested against a weakened or modified variant.
- **CLI Issuance**: The `certify --run-id <id>` command is used to issue a non-repudiable Verification Certificate (VC) for a specific run trace.

### B. Certification API
The **Certification API** serves as a public "Trust Anchor," allowing external systems and CI/CD gates to verify the authenticity of an evaluation run without requiring administrative access to the harness.

- **Endpoint**: `GET /v1/certificates/<run_id>`
- **Response**: Returns a non-repudiable JSON object containing the trace hash, run metadata, and the **signature_ed25519** field from the issuing harness.
- **Verification CLI**: Stakeholders can use the `verify --run-id <id>` command locally or the `gate --run-id <id>` command in CI/CD pipelines to verify the signature (field: `signature_ed25519`) and re-compute the trace hash locally to prove absolute veracity.

### C. HMS-Ready Architecture
The Trust Protocol is designed for **HMS-Readiness**, supporting the transition to professional Hardware Security Modules (HSM) or Cloud KMS providers.
- **Pluggable KeyLoader**: The harness uses a modular interface for key retrieval. While the `LocalFileKeyLoader` is the default, **custom extensions** can implement loaders for AWS KMS, GCP KMS, or Azure Key Vault, ensuring that private keys never reside on the local evaluation disk.

---

## 🔑 8. Permissions-Based Access Control (PBAC)

For professional and high-compliance environments, the harness uses a **Permission-Based Access Control (PBAC)** system, which replaces rigid roles with granular, string-based permission nodes.

#### Permission Nodes
- **`READ_ONLY`**: Access to `scenarios:read`, `runs:read`, `docs:read`, `debugger:read`.
- **`OPERATOR`**: Adds `eval:trigger`, `index:refresh`, `demo:execute`, and `debugger:event`.
- **`ADMIN`**: Full control including `scenarios:write`, `scenarios:delete`, `debugger:reset`, and `system:config`.

#### SSO & OIDC Token Validation (Out-of-the-Box)
The harness provides native support for validating standard **OAuth2/OIDC JWT Bearer Tokens** from identity providers (e.g. Okta, Azure AD).

##### Configuration Parameters
Set the following environment variables to configure OIDC:
- `OIDC_JWKS_URL`: The public JWKS key server endpoint.
- `OIDC_ISSUER`: Optional. Issuer claim to enforce.
- `OIDC_AUDIENCE`: Optional. Audience claim to enforce.
- `OIDC_JWKS_CACHE_TTL`: Optional. Public key caching expiration limit (defaults to `3600`).

##### Hardening Features
- **JWKS Client Caching**: Reuses `PyJWKClient` instances to minimize external network lookups.
- **Clock-Skew Tolerance**: Tolerates up to 10 seconds of server clock drift.
- **Header Case-Insensitivity**: Case-insensitively parses standard `Authorization: Bearer <JWT>` and custom headers.

For extending authentication, plugins can subclass `AuthManager`. For details, see the [Developer Guide](help/03_DEVELOPER_GUIDE.md#11-extending-authentication--pbac).

---

## 🛠️ Troubleshooting 401 Unauthorized Errors

If you encounter a `401 Unauthorized` error when accessing the Visual Debugger or API, follow these steps:

### 1. Visual Debugger (Browser)
- **Security Gateway**: Ensure you have entered the correct `DASHBOARD_API_KEY` in the login modal. The harness uses secure, server-side sessions; if your session expires, you must re-authenticate.
- **Cookies Enabled**: The console relies on **HttpOnly session cookies**. Ensure your browser is not blocking cookies for the harness domain.
- **CORS Issues**: If hosting the UI and API on different subdomains, ensure `CORS(app, supports_credentials=True)` is configured in `app.py`.

### 2. Programmatic Access (CLI/curl)
- **Header Check**: Ensure you are passing the key in the `X-AES-API-KEY` header, not as a query parameter.
- **Exact Match**: The key is case-sensitive and must exactly match the value in your `.env` file or environment.

### 3. Server Configuration
- **Environment Variable**: Run `agentv doctor` to verify that the `DASHBOARD_API_KEY` is correctly detected by the harness.
- **501 Not Implemented**: If you see this error, it means **no key** is configured. The harness will block all sensitive routes until a key is provided.

For further assistance, contact `agentv@agentvos.ai`.
