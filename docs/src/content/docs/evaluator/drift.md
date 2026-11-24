---
title: Drift Management & Edge-Case Triage
description: Ingest real-world behavior and analyze agent failures using the Triage Engine.
---

Import production JSON/JSONL histories as editable AES scenario scaffolds:

```bash
agentv import-drift --input logs/production.jsonl --industry telecom
```

The CLI writes `scenarios/drift-<random UUID prefix>.json` by default. It does not
select `industries/<industry>/scenarios` automatically and the filename is not a
content hash. The source must contain nonempty role-based history.

Imported history is retained in `metadata.ground_truth_history`; the root includes
numeric aes_version, metadata, workflow and evaluation. This is an editable
baseline, not proof that the original production behavior was replayed. Replace
the generic task and add explicit expected outputs, tools/state assertions and
independent evidence before treating it as a meaningful regression suite.

```bash
agentv aes validate --path scenarios/YOUR_IMPORTED_SCENARIO.json
agentv lint --path scenarios/YOUR_IMPORTED_SCENARIO.json
```

After running a scenario, use `agentv explain --run-id RUN_ID` or the Console to
inspect actual failure evidence. Triage diagnoses provider-owned events and
declared assertions; it does not infer correctness from a nonempty response.
See [failure taxonomy](/evaluator/taxonomy/) and
[state triage](/evaluator/triage-vfs/).
