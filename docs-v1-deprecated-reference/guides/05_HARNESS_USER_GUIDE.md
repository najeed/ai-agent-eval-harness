# AgentV Evaluation Harness: User Guide (v1.6.0)

This guide covers the **Execution Engine**, CLI commands, and Forensic infrastructure. For the scenario JSON schema, see the [AES Specification](./04_AES_SPECIFICATION.md).

---

## 1. Executing Evaluations

### Single Scenario
```bash
agentv run --scenario scenarios/my_test.json
```

### Batch Evaluation
```bash
agentv evaluate --path scenarios/finance/ --format json
```

---

## 2. Replaying Execution (`agentv replay`)
Every evaluation produces a `run.jsonl` flight recorder log. You can replay this log to reconstruct the agent's interaction history:

```bash
agentv replay --run-id <id>
```

---

## 3. Trust Protocol & Behavioral Fingerprinting
To ensure high-stakes industrial reliability, AgentV implements the **Forensic Evidence Ledger**.

### Forensic Environmental DNA
The harness captures a "baseline" of the physical world state during the evaluation, including:
- **Identity Consistency**: Cross-referencing IDs across simulators.
- **Connectivity Trace**: API keys and endpoint sanitization.
- **Simulator Configuration**: Snapshot of all world-shim parameters.

### Behavioral Fingerprinting (Enterprise)
The engine generates a non-repudiable fingerprint of the agent's trajectory. If the agent's logic deviates from the certified path, the harness triggers a **Behavioral Drift** alert.

---

## 4. Regulatory Compliance Gating (`agentv gate`)
The `gate` command is used in CI/CD pipelines to enforce compliance standards:

```bash
agentv gate --run-id <id> --verify-ledger
```

**Verification Criteria:**
1. **Integrity**: Validates the ED25519 signature of the trace.
2. **Provenance**: Matches the `git_hash` and `harness_version` against sanctioned baselines.
3. **Ledger Match**: Ensures all forensic sidecars (screenshots, logs) match the signed manifest.

---

## 5. Industrial Standards Registry (`agentv init`)
The harness includes a centralized registry for bootstrapping standardized evaluation environments.

```bash
agentv init --standard ISO_20022
```

- **Supported Sectors**: Finance (ISO 20022), Healthcare (HL7 FHIR), Manufacturing (Digital Twins).
- **Auto-Alignment**: Scaffolding via the registry ensures that `compliance_level` and `industry` metadata are correctly populated for regulatory audits.

---

## 6. Forensic Trace Logging (`run.jsonl`)
The `run.jsonl` file is the machine-readable "Flight Recorder" for every evaluation. It contains:
- **Prompts & Responses**: Full text of all agent interactions.
- **Tool Calls**: Every shim interaction, including latency and status.
- **State Diffs**: (Forensic Mode) Delta snapshots of simulator states.
