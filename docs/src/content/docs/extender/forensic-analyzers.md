---
title: Custom Forensic Analyzers
description: Extend the diagnostic depth of AgentV by building custom forensic analyzers.
---

Forensic Analyzers are the intelligence layer of the [Triage Engine](/spec/taxonomy/). While AgentV Core provides baseline heuristic checks, you can implement custom analyzers to detect domain-specific logic errors, protocol violations, or security anomalies.

## 1. The `BaseForensicAnalyzer` Interface

All analyzers must inherit from the `BaseForensicAnalyzer` abstract base class.

```python
from eval_runner.taxonomy import BaseForensicAnalyzer, FailureCategory

class DatabaseIntegrityAnalyzer(BaseForensicAnalyzer):
    def analyze(self, history, task_result=None):
        # Your diagnostic logic here
        return FailureCategory.LOGIC_STATE_MISMATCH
```

### Participation in the Weighted Model
In AES v1.4, the triage engine uses a **Weighted Evidence Model**. When your analyzer returns a `FailureCategory`, it is automatically registered as a forensic trigger in the [Causal Chain](/spec/forensic-ledger-schema/). Enterprise-tier analyzers can return enriched metadata objects (containing confidence and severity) for superior ranking.

### `analyze(history, task_result=None)`
- **history**: A list of turn dictionaries. Each turn contains an `identity` (e.g., `agent_id`, `system_id`) and a `role` (`user`, `agent`).
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

> [!NOTE]
> Analyzers are executed in the order they are registered. Core analyzers run first, followed by plugin-registered analyzers.

---

## 3. Advanced Examples (Enterprise Patterns)

The follow examples demonstrate how heavy or domain-specific logic (e.g., NLP clustering or telemetry trending) can be integrated as custom analyzers. 

### Example A: Building a State-Action Validator
This example detects if an agent claims to have "deleted" a file, but the state snapshots show the file system remains unchanged.

```python
import hashlib
from eval_runner.taxonomy import BaseForensicAnalyzer, FailureCategory

class StateActionAnalyzer(BaseForensicAnalyzer):
    def analyze(self, history, task_result=None):
        if not task_result: return None
        
        snapshots = task_result.get("state_snapshots", [])
        # Anchoring logic: Prioritize 'identity' over legacy 'role'
        agent_msgs = [m for m in history if m.get("identity") == "agent_id"]
        
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
