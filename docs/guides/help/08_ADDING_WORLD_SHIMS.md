## Dynamic Discovery & Dashboard
The system includes **20 default shims**, categorized for full-spectrum enterprise simulation:

### Core Infrastructure
- **Git**: VFS-aware repository and version control simulation.
- **API**: Generic REST/gRPC endpoint mocking with state.
- **Database**: SQL table simulation with persistent row storage.
- **Terminal**: SSH and shell execution environment (sandboxed).
- **Cloud**: Cloud infrastructure simulator (AWS/GCP/Azure resources).

### Communication & Collaboration
- **Slack**: Corporate messaging, channels, and bot interaction mock.
- **Email**: SMTP/IMAP simulator for transactional and user mail.
- **Jira**: Ticketing, agile boards, and project management simulation.
- **Social**: Social media posting and feed simulation (X/LinkedIn).
- **Support**: Desk/Tickets simulator (Zendesk/Intercom).

### Business & Fintech
- **CRM**: Customer/Lead management simulation (Salesforce-like).
- **ERP**: Enterprise resource planning and supply chain mock.
- **Stripe**: Payment processing, subscriptions, and invoice simulation.
- **Calendar**: Meeting scheduling and availability management.

### AI & Modern Web
- **Browser**: Headless browser automation and DOM interaction simulator.
- **Vector**: Vector database simulation for RAG (Pinecone/Milvus).
- **KB**: Knowledge base search and retrieval (Confluence/Notion).
- **CI/CD**: Build pipeline and deployment status simulator.
- **IoT**: Smart device and sensor interaction mock.
- **Security**: Identity & Access Management (Auth0/Okta/IAM).

These are automatically reflected in your **Dashboard** under "World Shims."

## Shims vs. VFS State Parity
A common question is: *How do shims allow for VFS state parity checks?*

1.  **The Sandbox State (VFS)**: The [ToolSandbox](/eval_runner/tool_sandbox.py#95-225) maintains a "Virtual File System" (the `.state` dict).
2.  **Execution Hook**: When an agent calls `database_query`, the [ToolSandbox](/eval_runner/tool_sandbox.py#95-225) routes it to the [DatabaseSimulator](/eval_runner/simulators.py#49-65).
3.  **State Reflection**: The shim executes the action and can optionally return `state_changes` that are applied to the VFS.
4.  **Parity Check**: At the end of a run, the `Evaluator` compares the current VFS state against the **"Ground Truth"** defined in the scenario. This is how we ensure "State Parity."

## Configuration & Governance
The system uses a **Two-Key Activation Model** for World Shims to ensure security and ease of management:

### 1. Global System Override
In [.env](/.env) (or via environment variables), you can set `GLOBAL_ENABLED_SHIMS`:
- **Default**: `git,api,database,terminal,cloud,slack,email,jira,social,support,crm,erp,stripe,calendar,browser,vector,kb,cicd,iot,security`
- **Restricted**: `git,api` (Only these two can ever be used).
- This allows you to disable heavy or risky shims system-wide without updating a single scenario.
- **Wildcard**: Use `*` to enable all registered shims (including those from plugins).

### 2. Per-Scenario Configuration
Each scenario can further restrict its environment using the `enabled_shims` property:
- This only has an effect if the shim is also allowed by the Global Override.
- If missing, it defaults to `*` (respecting the Global limit).

## Adding a New Shim (Zero-Touch Plugin Method)
The preferred way to add a shim is via a **Plugin**. This keeps the core harness immutable.

### 1. Define the Simulator
Create your simulator class anywhere (e.g., in your plugin package). It must implement [execute(action, params)](/eval_runner/simulators.py#124-132).

```python
class MyCustomSimulator:
    def execute(self, action: str, params: dict) -> dict:
        return {"status": "success", "result": "Action executed!"}
```

### 2. Register via Plugin Hook
In your [BaseEvalPlugin](/eval_runner/plugins.py#27-34) subclass, override the [on_register_simulators](/tests/test_world_shims_hotswap.py#11-13) hook:

```python
from eval_runner.plugins import BaseEvalPlugin

class MyEcoPlugin(BaseEvalPlugin):
    def on_register_simulators(self, registry: dict):
        # Register your shim instance in the provided registry dict
        registry["custom"] = MyCustomSimulator()
```

### 3. Verify on Dashboard
Restart the console or run `multiagent-eval console`. Your shim will be automatically discovered and reflected in the "World Shims" count.

## Using the Shim in Scenarios
You can now reference this shim in your scenario's `tasks`:

```json
"tasks": [
  {
    "task_id": "db_check",
    "description": "Query the user table for high scorers",
    "tools": ["database.query"],
    "expected_outcome": "Score returned for Alice"
  }
]
```
