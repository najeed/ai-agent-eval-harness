# Guide: Agent Eval Specification (AES) v1.2

AES is the foundational standard for shareable, deterministic agent benchmarks.

## 1. Design Philosophy
- **Human Readable**: YAML-based for easy editing.
- **Framework Agnostic**: Works with LangGraph, CrewAI, or custom agents.
- **CI Ready**: Validatable via JSON Schema.
- **Deterministic DAGs**: Support for non-linear workflow execution with dependency gating.

## 2. Core Components (v1.2)

### DAG-Based Execution
Scenarios define a directed acyclic graph of `nodes` and `edges`, enabling complex branching and state-dependent transitions.

```yaml
workflow:
  nodes:
    - id: "start"
      task: "Initial inquiry"
    - id: "branch_a"
      task: "Processing for A"
      requires: ["start"]
  gating:
    - node: "branch_a"
      condition: "status == 'approved'"
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
