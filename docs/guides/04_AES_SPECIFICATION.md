# Guide: Agent Eval Specification (AES) v1.2

AES is the foundational standard for shareable, deterministic agent benchmarks.

## 1. Design Philosophy
- **Human Readable**: YAML-based for easy editing.
- **Framework Agnostic**: Works with LangGraph, CrewAI, or custom agents.
- **CI Ready**: Validatable via JSON Schema.
- **Deterministic DAGs**: Support for non-linear workflow execution with dependency gating.

## 2. Core Components (v1.2)

### DAG-Based Execution (workflow)
Scenarios define a directed acyclic graph (DAG) of `nodes` and `edges`, enabling complex multi-stage evaluations with dependency tracking.

```yaml
workflow:
  nodes:
    - id: "task-1"
      task_description: "Initial credit check"
    - id: "task-2"
      task_description: "Policy enforcement audit"
  edges:
    - from: "task-1"
      to: "task-2"
```

### Typed Outcomes
Mandates adherence to industrial gold standards using typed result schemas.

### Pluralistic Judging (IJA)
Implements Inter-Judge Agreement metrics. Critical evaluations require a "Judge Panel" consensus.

### Externalized Mock Datasets
High-fidelity sector labs (e.g., Bank, EHR/HL7) load mock data dynamically from the `industries/` directory.

## 3. Infrastructure Hooks
- `pre_eval`: Command run before evaluation starts.
- `post_eval`: Command run after completion.

## 4. World Shim Configuration (`enabled_shims`)
Scenarios can declare which World Shims (environment simulators) they require.

- If `enabled_shims` is **omitted**, all 20 built-in shims are available by default.
- Shim keys correspond to the registry keys defined in `eval_runner/simulators.py`.

**Available built-in shim keys:** `git`, `api`, `database`, `slack`, `crm`, `email`, `calendar`, `jira`, `cloud`, `terminal`, `stripe`, `erp`, `browser`, `kb`, `support`, `social`, `vector`, `cicd`, `iot`, `security`

📖 See the full shim reference with per-shim actions and failure modes: [`docs/guides/help/07_WORLD_SHIMS_REFERENCE.md`](./help/07_WORLD_SHIMS_REFERENCE.md)

---

## 5. Path Decoupling & Portability
AES benchmarks are now fully portable. 
- **Relative Datasets**: `dataset.path` can now be relative to the scenario file (e.g., `./records.csv`), allowing you to share scenario bundles easily.
- **Auto-Industry**: If `industry` is omitted from metadata, the harness will attempt to infer it from the parent directory or tag it as `local`.

---

## 6. Replaying Execution (`run.jsonl`)
Every AES evaluation produces a `run.jsonl` flight recorder log. You can replay this log to debug specific "crashes" or "wrong turns":
```bash
multiagent-eval replay --path runs/run.jsonl
```

---

## 7. Complete Example (Loan Approval)

Below is a production-grade AES v1.2 scenario demonstrating a multi-stage loan approval process with tool requirements and policy constraints.

```json
{
  "scenario_id": "loan_approval_01",
  "metadata": {
    "name": "High-Density Loan Credit Audit",
    "industry": "finance",
    "compliance_level": "Standard",
    "agent_topology": {
      "loan_agent": {
        "reads": ["user.credit_score", "bank.policies"],
        "writes": ["loan.status"]
      }
    }
  },
  "description": "Evaluate an agent's ability to process a loan while adhering to strict internal credit policies.",
  "workflow": {
    "nodes": [
      {
        "id": "task-1",
        "task_description": "Approve the loan for Alice at the standard rate.",
        "required_tools": ["check_credit_score", "approve_loan"],
        "success_criteria": [
          {"metric": "tool_call_correctness", "threshold": 1.0},
          {"metric": "policy_compliance", "threshold": 1.0}
        ]
      },
      {
        "id": "task-2",
        "task_description": "Explain the decision and provide the next steps for disbursement.",
        "success_criteria": [
          {"metric": "path_parsimony", "threshold": 0.5}
        ]
      }
    },
    "edges": [
      { "from": "task-1", "to": "task-2" }
    ]
  }
}
```
> [!TIP]
> Use the **Visual AES Builder** (available via `multiagent-eval console`) to construct these workflows using a drag-and-drop interface instead of manual JSON editing.
