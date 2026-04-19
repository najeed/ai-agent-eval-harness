# Standardized Benchmark Ecosystem

AgentV provides native, zero-munge support for the world's most rigorous AI agent benchmarks.

---

## 1. Supported Ecosystems

| Benchmark | URI Scheme | Focus Area |
| :--- | :--- | :--- |
| **GAIA** | `gaia://` | Multi-hop reasoning & real-world tool use. |
| **AssistantBench** | `assistantbench://` | Enterprise and industrial task accuracy. |
| **OSWorld** | `osworld://` (Coming Soon)| Cross-OS agentic workflows. |

---

## 2. The Unified Benchmark URI

Researchers can execute benchmarks directly from the CLI without manual data preparation:

```bash
agentv evaluate --path gaia://2023_validation
```

### Forensic Mapping
When a benchmark is loaded via the URI schema, the engine automatically:
1. **Normalizes Schema**: Maps benchmark fields to high-fidelity [AES Specification](/guides/04_AES_SPECIFICATION.md) criteria.
2. **Version Pinning**: Ensures reproducibility by targeting specific dataset snapshots.
3. **Forensic Integration**: Signs the results using the [Trust Protocol](/spec/trust_protocol_spec_v1.md).

---

## 3. Comparative Studies

AgentV's **Model Wars** suite allows researchers to compare multiple agents (GPT-4 vs. Claude-3.5 vs. Llama-3) against the same benchmark snapshot, producing a unified [Comparative Leaderboard].
