# 🌍 World Shims Reference — The 20-Shim Enterprise Suite

World Shims are VFS-aware environment simulators that let agents interact with realistic, stateful systems without touching production infrastructure.

## How to Activate Shims in a Scenario

Add an `enabled_shims` array to your scenario JSON. The evaluation engine will mount only those shims for the duration of the run:

```json
{
  "scenario_id": "my_fintech_scenario",
  "title": "Loan Approval Validation",
  "industry": "fintech",
  "enabled_shims": ["database", "stripe", "security", "slack"],
  "tasks": [...]
}
```

If `enabled_shims` is omitted, **all 20 shims** are mounted (default behavior).

---

## The 20 Built-In World Shims

| # | Registry Key | Class | Domain | Trigger Action(s) |
|---|---|---|---|---|
| 1 | `git` | `GitSimulator` | Version Control | `git_clone`, `git_commit`, `git_push` |
| 2 | `api` | `ApiSimulator` | REST APIs | `GET`, `POST` via `method` + `path` params |
| 3 | `database` | `DatabaseSimulator` | SQL / Data | `database_query` (SELECT, INSERT) |
| 4 | `slack` | `SlackSimulator` | Messaging | `slack_send` |
| 5 | `crm` | `CRMSimulator` | Sales / CRM | `crm_update_lead` |
| 6 | `email` | `EmailSimulator` | Email | `email_send`, `email_list` |
| 7 | `calendar` | `CalendarSimulator` | Scheduling | `calendar_book` |
| 8 | `jira` | `JiraSimulator` | Issue Tracking | `jira_update` |
| 9 | `cloud` | `CloudSimulator` | AWS/GCP Infra | `cloud_launch` |
| 10 | `terminal` | `TerminalSimulator` | SSH / Bash | `ls`, `cd`, arbitrary shell commands |
| 11 | `stripe` | `StripeSimulator` | Payments | `stripe_charge` |
| 12 | `erp` | `ERPSimulator` | ERP (SAP/Oracle) | `erp_create_order` |
| 13 | `browser` | `BrowserSimulator` | Headless Browser | `browser_go` |
| 14 | `kb` | `KnowledgeBaseSimulator` | Confluence/Notion | `kb_search` |
| 15 | `support` | `SupportDeskSimulator` | Zendesk/Intercom | `support_close` |
| 16 | `social` | `SocialMediaSimulator` | X / LinkedIn | `social_post` |
| 17 | `vector` | `VectorDBSimulator` | Pinecone/Milvus | `vector_query` |
| 18 | `cicd` | `CICDSimulator` | Jenkins/Actions | `cicd_deploy` |
| 19 | `iot` | `IoTSimulator` | IoT Devices | device state read/write via `device` + `state` |
| 20 | `security` | `SecuritySimulator` | IAM / Auth0/Okta | `security_auth` |

---

## Shim Behavior & Configuration

### 1. `git` — Git Simulator
Simulates a Git repository with branch tracking and commit history.

```json
{ "action": "git_commit", "params": { "message": "Fix risk threshold" } }
// → {"status": "success", "message": "Committed with message: Fix risk threshold"}
```

**Initial State:** `current_branch: main`, one initial commit in history.

---

### 2. `api` — REST API Simulator
Simulates an HTTP API with configurable endpoints.

```json
{ "action": "api_call", "params": { "method": "GET", "path": "/api/v1/user/1" } }
// → {"status": "success", "data": {"id": 1, "name": "Test User", "plan": "pro"}}
```

**Failure mode:** GET to unknown path returns `{"error": "Not Found"}`.

---

### 3. `database` — SQL Database Simulator
Simulates a secure relational DB. Checks for `SELECT` or `INSERT` in the query string.

```json
{ "action": "database_query", "params": { "query": "SELECT * FROM users" } }
// → {"status": "success", "rows": [{"id": 1, "email": "admin@example.com"}]}
```

**VFS Parity Check:** Expected state changes against `tables` dict are validated post-call.

---

### 4. `slack` — Slack Simulator
Appends messages to an in-memory channel log.

```json
{ "action": "slack_send", "params": { "channel": "#alerts", "message": "Threshold breached" } }
```

---

### 5. `crm` — CRM Simulator
Manages a list of sales leads. Updates lead status by ID.

```json
{ "action": "crm_update_lead", "params": { "id": "L101", "status": "Qualified" } }
```

---

### 6. `email` — Email Simulator
Simulates an SMTP server. Supports sending and listing inbox.

```json
{ "action": "email_send", "params": { "to": "manager@corp.com", "subject": "Alert" } }
{ "action": "email_list" }
```

---

### 7. `calendar` — Calendar Simulator (GCal/Outlook)
Books meetings into an in-memory event list.

```json
{ "action": "calendar_book", "params": { "title": "Risk Review", "time": "2026-04-01T14:00" } }
```

---

### 8. `jira` — Jira / Issue Tracker Simulator
Updates issue status by ticket ID.

```json
{ "action": "jira_update", "params": { "id": "PROJ-1", "status": "In Progress" } }
```

---

### 9. `cloud` — Cloud Infrastructure Simulator (AWS/GCP)
Spins up virtual instances.

```json
{ "action": "cloud_launch", "params": { "type": "c5.xlarge" } }
// → {"status": "success", "id": "i-5678"}
```

**Failure mode:** Returns `Quota exceeded` to simulate resource limits.

---

### 10. `terminal` — SSH / Bash Terminal Simulator
Executes shell-like commands in a virtual working directory.

```json
{ "action": "terminal_exec", "params": { "cmd": "ls" } }
// → {"status": "success", "output": "file1.txt\nfile2.py"}
```

---

### 11. `stripe` — Payment Gateway Simulator
Simulates charge creation and tracks payment history.

```json
{ "action": "stripe_charge", "params": { "amount": 4999, "currency": "usd" } }
// → {"status": "success", "id": "ch_123"}
```

**Failure mode:** Returns `Card declined` for invalid configurations.

---

### 12. `erp` — ERP Simulator (SAP / Oracle)
Manages purchase orders in an in-memory order book.

```json
{ "action": "erp_create_order", "params": { "item": "Server Rack", "qty": 5 } }
```

**Failure mode:** Returns `Inventory low`.

---

### 13. `browser` — Headless Browser Simulator
Simulates DOM navigation for web automation agents.

```json
{ "action": "browser_go", "params": { "url": "https://dashboard.internal" } }
// → {"status": "success", "title": "Mock Page"}
```

---

### 14. `kb` — Knowledge Base Simulator (Confluence / Notion)
Searches a document store.

```json
{ "action": "kb_search", "params": { "query": "onboarding" } }
// → {"status": "success", "results": [{"id": "D001", "title": "Onboarding"}]}
```

---

### 15. `support` — Support Desk Simulator (Zendesk / Intercom)
Opens and closes support tickets.

```json
{ "action": "support_close", "params": { "id": "TKT-123" } }
```

---

### 16. `social` — Social Media Simulator (X / LinkedIn)
Posts content and returns a feed.

```json
{ "action": "social_post", "params": { "text": "Launching v2.0!", "platform": "X" } }
```

---

### 17. `vector` — Vector Database Simulator (Pinecone / Milvus)
Handles embedding queries for RAG agents.

```json
{ "action": "vector_query", "params": { "embedding": [0.1, 0.2, ...] } }
// → {"status": "success", "matches": [{"id": "v1", "score": 0.99}]}
```

---

### 18. `cicd` — CI/CD Pipeline Simulator (Jenkins / GitHub Actions)
Triggers build pipelines and tracks build status.

```json
{ "action": "cicd_deploy", "params": { "branch": "main", "env": "staging" } }
// → {"status": "success", "id": "B-2"}
```

---

### 19. `iot` — IoT Device Simulator
Reads and writes state to a virtual device mesh.

```json
{ "action": "iot_control", "params": { "device": "thermostat", "state": "68F" } }
// → {"status": "success", "state": "68F"}
```

**Failure mode:** Returns `Device offline` for unknown devices.

---

### 20. `security` — IAM / Auth Simulator (Auth0 / Okta)
Handles authentication and token issuance. Integrates with policy guardrails.

```json
{ "action": "security_auth", "params": { "user_id": "u_99", "scope": "admin" } }
// → {"status": "success", "token": "jwt_token_xyz"}
```

**Policy Integration:** When the Security Shim blocks an action (e.g., data exfiltration via regex match), the Triage Engine flags this as a `policy_violation`.

---

## Adding Custom Shims (Zero-Touch)

You can register additional shims without modifying core code via the `on_register_simulators` plugin hook:

```python
from eval_runner.plugins import BaseEvalPlugin

class MyCustomShimPlugin(BaseEvalPlugin):
    def on_register_simulators(self, registry: dict):
        registry["my_erp_v2"] = MyERPv2Simulator()
```

📖 See [`docs/plugins.md`](/docs/plugins.md) for the full plugin lifecycle reference.
📖 See [`06_TRIAGE_ENGINE_AND_VFS.md`](06_TRIAGE_ENGINE_AND_VFS.md) for how shims integrate with the VFS triage engine.
