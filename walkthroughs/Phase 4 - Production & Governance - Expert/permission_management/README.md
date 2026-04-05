# README: Permission Management (The Gatekeeper)

Learn how to manage industrial access levels using **Permission-Based Access Control (PBAC)**.

## 🎯 Objectives
- Understand the difference between `READ_ONLY`, `OPERATOR`, and `ADMIN`.
- Learn how the `DASHBOARD_API_KEY` secures the industrial console.
- Configure granular permission nodes for custom plugins.

## 🚀 Steps

### Step 1: The Lockdown
In industrial environments, not everyone can trigger a multi-million token evaluation. Access is restricted via the `X-AES-API-KEY` header.

### Step 2: Audit Your Keys
Run the permission verification script to see what your current mock key allows:
```bash
python walkthroughs/Phase 4 - Production & Governance - Expert/permission_management/verify_permissions.py
```

### Step 3: Escalate Access
The script defaults to a `READ_ONLY` key. Modify the script to use a mock `OPERATOR` key and notice how the `eval:trigger` permission changes from `🔴 DENIED` to `🟢 GRANTED`.

## 🏗️ Industrial Reality
> [!IMPORTANT]
> In this tutorial, you are manually editing a mock identity script. In a **Production Deployment**, identity management is never handled by human-edited files. It is bound to an **Industrial Identity Provider (IdP)** or an encrypted cloud vault.
> 
> **Why this matters**: Even if a developer had access to this harness, they could not "simulated their way" into an admin role. The harness validates the **Cryptographic Trace** against the **Trust Anchor** before any action is permitted. If the key in the payload isn't signed by an authorized node, the action fails.

## 📊 Key Concepts
- **PBAC**: Granular strings (e.g., `scenarios:delete`) instead of rigid roles.
- **Header Enforcement**: Ensuring every API call is cryptographically bound to an identity.
- **NIST AI-100-1 Resilience**: Ensuring least-privilege for AI agents to prevent adversarial misuse of system shims.

---
*Ready to take control of the harness? Check out the [STORY.md](./STORY.md) next!*
