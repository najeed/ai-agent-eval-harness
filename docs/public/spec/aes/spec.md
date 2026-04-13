# Agent Eval Specification (AES) v1.4

AES is a standardized format for defining portable and robust AI agent benchmarks. v1.4 introduces **Ref-Based Modular Definitions**, **Capability-Based Routing**, and **Quantitative Success Criteria** for industrial-grade forensic auditing.

## Core Principles
1. **Determinism**: Scenarios should be reproducible and verifiable across diverse environments.
2. **Portability**: The format is framework-agnostic (LangGraph, CrewAI, AutoGen, etc.).
3. **Structured Metrics**: Success is measured via standardized metrics, thresholds, and weights.
4. **Target Abstraction**: Scenarios define *what* capabilities are needed; infrastructure defines *where* they are resolved.
5. **Forensic Provenance**: Every run captures an immutable Environmental DNA snapshot, ensuring result integrity.
6. **Decoupled Architecture**: Technical specifications are separated into modular definitions (`metadata`, `workflow`, `evaluation`).

## Key Sections

### 1. Metadata
Details about the benchmark suite (name, industry, tags).
- `capabilities`: [v1.4] List of required infrastructure components (e.g., `fintech_loan_api`).
- `standards_registry`: Alignment with global standards (ISO 42001, NIST AI RMF, etc.).

### 2. World Shim Configuration
Declare which environment simulators to mount for this benchmark.
- `enabled_shims`: List of shim keys (e.g., `["database", "stripe", "security"]`).
- Valid keys: `git`, `api`, `database`, `slack`, `crm`, `email`, `calendar`, `jira`, `cloud`, `terminal`, `stripe`, `erp`, `browser`, `kb`, `support`, `social`, `vector`, `cicd`, `iot`, `security`.

### 3. Workflow DAG (State-Machine)
The state-machine defining the agentic interaction.
- `id`: Unique node identifier.
- `task_description`: The instructions for the agent at this state.
- `required_tools`: [v1.4] List of shims/tools explicitly allowed for this node.
- `success_criteria`: [v1.4] Declarative checks for task completion.

### 4. Success Criteria [v1.4]
Specific, measurable predicates for validating a node's output.
- `tool_called`: Verify a specific tool was used.
- `output_matches`: Regex or exact match validation.
- `factual_reference`: Verification against a golden dataset.

### 5. Capability-Based Routing [v1.4] ⭐
Infrastructure targets are resolved dynamically via the `routing/manifest.json`.
- Scenarios remain immutable across Dev/Staging/Prod.
- Environments map `capabilities` to physical endpoints.

### 6. Environmental DNA Snapshot
Every trace captures a sanitized snapshot of the host's `shim_resources.json`.
- Ensures forensic reproducibility without exposing production secrets.

## Validation
```bash
agentv aes validate --path my_benchmark.aes.json
```

## Configuration Layout (.aes/config/)
All infrastructure configuration is now consolidated for security:
- `routing/`: Dynamic endpoint mappings.
- `shims.d/`: Environmental tool definitions.
- `plugins.json`: Lifecycle extension manifest.

## Changelog
| Version | Changes |
|---|---|
| v1.4 | **Capability-Based Routing**, **Quantitative Success Criteria**, Ref-Based Schemas. |
| v1.3 | Environmental DNA, Provisioning Snapshots, Redaction. |
| v1.2 | Standardized Workflow DAG, Consensual Judges. |
