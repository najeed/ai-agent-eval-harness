---
title: Security & Authentication
description: Industrial-grade security standards, authentication protocols, and NIST AI-100-1 alignment.
---

MultiAgentEval is **Secure-by-Design**. It protects evaluation infrastructure and data veracity using a multi-layered security model including mandatory API keys, sandbox isolation, and NIST-aligned trustworthiness metrics.

## 🔑 The `DASHBOARD_API_KEY`

The `DASHBOARD_API_KEY` is a mandatory credential required for all protected REST API routes and the [Integrated Console](/ai-agent-eval-harness/extender/api-reference/).

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

### 3. Path Traversal Protection
The [Integrated Console](/ai-agent-eval-harness/extender/api-reference/) implements a **Global Proactive Security Intercept**. Any request containing traversal patterns (`..`, `%2e%2e`) is immediately blocked with a **403 Forbidden** response.

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

The [Trust Protocol](/ai-agent-eval-harness/auditor/trust-protocol/) provides immutable proof of run integrity.

1. **Behavioral Fingerprinting**: Uses **SHA-256** content hashing to sign raw `.jsonl` trace files.
2. **Certification API**: Serves as a public "Trust Anchor" for external CI/CD gates via `GET /api/v1/certificates/<run_id>`.
3. **HMS-Ready**: Supports **AWS KMS**, **GCP KMS**, and **Azure Key Vault** for private key storage, ensuring keys never reside on the local evaluation disk.

---

## 🔐 PBAC Integration

For enterprise environments, the harness supports **Permission-Based Access Control (PBAC)**:
- **`READ_ONLY`**: View-only access to scenarios and runs.
- **`OPERATOR`**: Trigger evaluations and refresh indexes.
- **`ADMIN`**: Full control over system configuration and scenario writing.

Plugins can subclass `AuthManager` to integrate with **Okta** or **Azure AD** using the [Plugin System](/ai-agent-eval-harness/extender/plugins/).
