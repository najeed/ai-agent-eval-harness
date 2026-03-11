# Guide: Agent Eval Specification (AES) v0.1

AES is the foundational standard for shareable, deterministic agent benchmarks.

## 1. Design Philosophy
- **Human Readable**: YAML-based for easy editing.
- **Framework Agnostic**: Works with LangGraph, CrewAI, or custom agents.
- **CI Ready**: Validatable via JSON Schema.

## 2. CLI Usage

### Validating an AES file
```bash
eval-harness aes validate path/to/benchmark.aes.yaml
```

## 3. Core Components

### Metadata
Defines the benchmark identity.
```yaml
metadata:
  name: billing_support_rigor
  difficulty: high
  tags: ["fintech", "compliance"]
```

### Dataset Linkage
Attach static datasets (like mock CRM records) to scenarios.
```yaml
dataset:
  path: ../datasets/records.csv
  format: csv
```

### Infrastructure Hooks
Manage environment setup/teardown.
- `pre_eval`: Command run before evaluation starts.
- `post_eval`: Command run after completion.

### Strongly Typed Tools
Define the interface the agent interacts with.
```yaml
agent:
  tools:
    - name: get_usage
      description: Fetches GB data for a user.
      parameters:
        type: object
        properties:
          user_id: { type: string }
```

### Evaluation Success Criteria
Define heuristics for "Success".
- `tool_called`: Specified tool was executed.
- `output_contains`: Specific text present in final answer.
- `factual_reference`: Verification against a source.

---

## 4. Replaying Execution (`run.jsonl`)
Every AES evaluation produces a `run.jsonl` flight recorder log. You can replay this log to debug specific "crashes" or "wrong turns":
```bash
eval-harness replay runs/run.jsonl
```
