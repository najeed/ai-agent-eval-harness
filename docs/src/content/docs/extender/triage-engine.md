---
title: Triage Engine & Forensic Analyzers
description: Advanced failure diagnostics via the pluggable forensic analyzer architecture.
---

The triage engine classifies failures using ordered checks in
`FailureTaxonomy._diagnose`. It returns the first matching category.

## Diagnostic precedence

1. Priority analyzers registered with `register_analyzer(analyzer, priority=True)`.
2. Baseline checks, in order: success/partial-pass (when status permits), explicit
   metric failures, protocol constraints, environment signals, agent behavior,
   and state stalls.
3. Ordinary registered analyzers in registration order, including the default
   ProtocolAnalyzer, LoopAnalyzer, and PIIAnalyzer.
4. `FailureCategory.UNKNOWN_FAILURE` if no check matches.

Exceptions from registered analyzers are logged and diagnosis continues. Priority
analyzers can override baseline outcomes, so use that registration deliberately.

## Causal evidence

CausalChain can record trigger evidence, timestamps, severity and rank. It does
not cause `_diagnose` to gather every match or select a winner through global
weighted arbitration. A returned category is the outcome of the precedence above,
not proof that every possible contributing cause was examined.

## Provider ownership

Run-based diagnostics use the explicit run ID and the execution owner's scoped
provider events and manifest. They do not infer evidence from local master logs.
Analyzer inputs can include conversation history, state snapshots, resource
telemetry and protocol observations. Harness telemetry measures the local
evaluation process; it does not directly measure a remote agent's resources.

See [custom analyzers](/extender/forensic-analyzers/),
[failure categories](/spec/taxonomy/), and the
[ledger](/spec/forensic-ledger-schema/) for extension contracts and fields.
