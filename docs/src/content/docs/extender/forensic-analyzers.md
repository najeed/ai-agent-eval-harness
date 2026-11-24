---
title: Custom Forensic Analyzers
description: Extend the diagnostic depth of AgentV by building custom forensic analyzers.
---

Forensic Analyzers are the intelligence layer of the [Triage Engine](/spec/taxonomy/). While AgentV OS Runtime provides baseline heuristic checks, you can implement custom analyzers to detect domain-specific logic errors, protocol violations, or security anomalies.

## 1. The `BaseForensicAnalyzer` Interface

All analyzers must inherit from the `BaseForensicAnalyzer` abstract base class.

```python
from eval_runner.taxonomy import BaseForensicAnalyzer, FailureCategory


class DatabaseIntegrityAnalyzer(BaseForensicAnalyzer):
    def analyze(self, history, task_result=None):
        # Your diagnostic logic here
        return FailureCategory.LOGIC_STATE_MISMATCH
```

### Participation in ordered diagnosis
Return a FailureCategory or `None`. Priority analyzers run before baseline checks;
ordinary analyzers run afterward in registration order. The first match returns
immediately. CausalChain can record the matched analyzer's evidence, but the
engine does not globally rank all matches or accept arbitrary enriched metadata
as a replacement for FailureCategory. See [triage](/extender/triage-engine/).

### `analyze(history, task_result=None)`
- **history**: Turn dictionaries with `role` and `content`; core roles include `user`, `agent` and `environment`. `identity` is optional attribution and is not present on every core history entry.
- **task_result**: A dictionary containing the [Forensic Ledger](/spec/forensic-ledger-schema/) (snapshots, telemetry, registries).
- **Return**: A `FailureCategory` if a match is found, otherwise `None`.

---

## 2. Registration via Plugins

To activate your analyzer, register it via the `on_diagnose_failure` hook in an AgentV Plugin.

```python
from eval_runner.plugins import BaseEvalPlugin


class MyForensicPlugin(BaseEvalPlugin):
    def on_diagnose_failure(self, taxonomy):
        from .analyzers import DatabaseIntegrityAnalyzer

        taxonomy.register_analyzer(DatabaseIntegrityAnalyzer())
```

:::note
Ordinary analyzers run in registration order after baseline checks. Use `taxonomy.register_analyzer(analyzer, priority=True)` to run before those checks; the first matching category wins.
:::

---

## 3. Advanced Examples (Enterprise Patterns)

The following examples illustrate how heavy or domain-specific logic (e.g., NLP clustering or telemetry trending) can be integrated as custom analyzers.

### Example A: Building a State-Action Validator
This example detects if an agent claims to have "deleted" a file, but the state snapshots show the file system remains unchanged.

```python
import hashlib
from eval_runner.taxonomy import BaseForensicAnalyzer, FailureCategory


class StateActionAnalyzer(BaseForensicAnalyzer):
    def analyze(self, history, task_result=None):
        if not task_result:
            return None

        snapshots = task_result.get("state_snapshots", [])
        # Core histories do not require an identity field.
        agent_msgs = [m for m in history if m.get("role") == "agent"]

        for msg in agent_msgs:
            if "deleted" in str(msg.get("content", "")).lower():
                # If everything remained identical across all turns
                if len(set(snapshots)) == 1:
                    return FailureCategory.LOGIC_STATE_MISMATCH

        return None
```

---

## 4. Best Practices

- **Avoid Side Effects**: Analyzers should be read-only. They analyze the ledger, they do not modify it.
- **Fail Gracefully**: Wrap complex logic in `try/except` blocks to prevent an analyzer failure from crashing the entire diagnostic pipeline.
- **Leverage Telemetry**: Use the `resource_telemetry` gradient to detect non-functional failures like resource leaks. (Note: High-fidelity gradient analysis is an Enterprise-tier plugin feature).
