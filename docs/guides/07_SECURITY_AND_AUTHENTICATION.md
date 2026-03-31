# Guide: Security and Authentication

The MultiAgentEval harness is designed with a **Secure-by-Design** philosophy to protect your infrastructure and data during industrial-scale agent evaluations. A central component of this security is the `DASHBOARD_API_KEY`.

## The `DASHBOARD_API_KEY`

The `DASHBOARD_API_KEY` is a mandatory security credential required to access protected REST API routes and the Visual Debugger bridge. It prevents unauthorized agents or external entities from triggering evaluations, modifying scenarios, or intercepting live traces.

### 🔐 1. Generating a Secure Key

For production or sensitive environments, you should use a cryptographically strong, random string. You can generate one using `openssl`:

```bash
# Generate a 64-character hex key
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

#### Asymmetric Trace Signing
For high-integrity environments, the harness supports signing evaluation traces using **ED25519** keys. See the [Advanced Security Guide](docs/guides/advanced/04_INTEGRITY_SIGNING.md) for details.

---

## Troubleshooting

- **`401 Unauthorized`**: The `X-AES-API-KEY` header is missing or incorrect.
- **`501 Not Implemented`**: The `DASHBOARD_API_KEY` is not configured on the server. Check your `.env` file.
- **CORS Errors**: Ensure the `DASHBOARD_API_KEY` is correctly shared between the frontend and backend if running custom UI components.
