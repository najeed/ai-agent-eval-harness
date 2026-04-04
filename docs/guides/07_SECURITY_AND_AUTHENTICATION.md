# Guide: Security and Authentication

The MultiAgentEval harness is designed with a **Secure-by-Design** philosophy to protect your infrastructure and data during industrial-scale agent evaluations. A central component of this security is the `DASHBOARD_API_KEY`.

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

## 🛡️ 5. Industrial Security Hardening (v1.2.3)

For the v1.2.3 release, the Evaluation Harness has undergone a comprehensive security overhaul to meet industrial-grade compliance standards.

### A. Network & SSRF Protection (R1)
The `RemoteBridgePlugin` and internal network drivers now implement **IP-level validation** to prevent Server-Side Request Forgery (SSRF).
- **Forbidden Endpoints**: All requests to loopback (`127.0.0.1`), link-local (`169.254.x.x`), and private subnets are blocked by default.
- **Cloud Metadata Security**: Access to cloud provider metadata endpoints (e.g., `169.254.169.254`) is strictly neutralized to prevent credential theft.

### B. Data Integrity & Telemetry Masking (R2)
- **Path Traversal Hardening**: All file-based operations (scenario saving, trace loading, and report generation) are subject to strict `Path.resolve()` jail-checks. The harness will refuse to interact with any file path outside of authorized project directories.
- **Recursive Secret Scrubbing**: The `TraceRecorder` and `EventEmitter` now employ a recursive masking layer that automatically redacts common secret patterns (API keys, JWTs, PII) from flight-recorded telemetry.

### C. Operational Best Practices (R3)
- **Turn Throttling**: The `EVAL_TURN_THROTTLE` configuration allows for tunable delays between agent turns, preventing resource exhaustion and satisfying rate-limiting requirements in sensitive industrial environments.
- **Header Enforcement**: The `X-AES-API-KEY` header is now a mandatory requirement for all sensitive management console routes when `DASHBOARD_API_KEY` is configured.

---

## 📑 6. The Trust Protocol: Fingerprinting & Certification

The Trust Protocol provides **immutable proof of run integrity** using a detached signature architecture.

### A. Behavioral Fingerprinting
A **Behavioral Fingerprint** (or Verification Certificate - VC) is a signed JSON snapshot that ensures a run's environment precisely matches the intended evaluation criteria.
- **Content Integrity**: Uses **SHA-256 content hashing** to generate a unique fingerprint of the raw `.jsonl` trace file. If a single character in the trace is modified post-execution, the hash mismatch invalidates the certificate.
- **Scenario Topology**: The fingerprint includes a cryptographic binding to the scenario's DAG structure and tool definitions, ensuring the agent was not tested against a weakened or modified variant.

### B. Certification API
The **Certification API** serves as a public "Trust Anchor," allowing external systems and CI/CD gates to verify the authenticity of an evaluation run without requiring administrative access to the harness.

- **Endpoint**: `GET /api/v1/certificates/<run_id>`
- **Response**: Returns a non-repudiable JSON object containing the trace hash, run metadata, and the **ED25519 signature** from the issuing harness.
- **Public Verification**: Stakeholders can use the harness's **Public Key** to verify the signature and re-compute the trace hash locally to prove absolute veracity.

### C. HMS-Ready Architecture
The Trust Protocol is designed for **HMS-Readiness**, supporting the transition to professional Hardware Security Modules (HSM) or Cloud KMS providers.
- **Pluggable KeyLoader**: The harness uses a modular interface for key retrieval. While the `LocalFileKeyLoader` is the default, **custom extensions** can implement loaders for AWS KMS, GCP KMS, or Azure Key Vault, ensuring that private keys never reside on the local evaluation disk.

---

## 🔑 7. Custom Extensions Identity & PBAC Integration

For professional and high-compliance environments, the harness uses a **Permission-Based Access Control (PBAC)** system, which replaces rigid roles with granular, string-based permission nodes.

#### Permission Nodes
- **`READ_ONLY`**: Access to `scenarios:read`, `runs:read`, `docs:read`, `debugger:read`.
- **`OPERATOR`**: Adds `eval:trigger`, `index:refresh`, `demo:execute`, and `debugger:event`.
- **`ADMIN`**: Full control including `scenarios:write`, `scenarios:delete`, `debugger:reset`, and `system:config`.

#### SSO Implementation (SAML/OIDC)
Plugins can subclass `AuthManager` to integrate with **Okta**, **Azure AD**, or other OIDC providers. This allows you to:
- Map custom extensions groups (e.g., `Harness-SuperUser`) to granular permission nodes (e.g., `EVAL_TRIGGER`).
- Define custom extensions permission strings (e.g., `governance:audit:export`) for protected plugin routes.
- Enforce multi-factor authentication (MFA).

For technical details on extending authentication, see the [Developer Guide](help/03_DEVELOPER_GUIDE.md#11-extending-authentication--rbac).

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
- **Environment Variable**: Run `multiagent-eval doctor` to verify that the `DASHBOARD_API_KEY` is correctly detected by the harness.
- **501 Not Implemented**: If you see this error, it means **no key** is configured. The harness will block all sensitive routes until a key is provided.

For further assistance, contact `ai.eval.harness.contact+security@gmail.com`.
