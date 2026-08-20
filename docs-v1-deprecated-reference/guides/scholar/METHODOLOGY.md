# The Scholar Methodology: Academic Integrity

This guide establishes the academic standards for using AgentV in formal peer-reviewed research and high-fidelity industrial verification.

---

## 1. Deterministic Benchmarking

To achieve publishable results, stochasticity must be isolated and controlled.

### The Seed-Sequence Protocol
AgentV uses a **Hierarchical Seed Sequence** to ensure that multi-hop agent behaviors are reproducible.
- **Base Seed**: Set globally for the campaign.
- **Run Index**: Unique counter for each attempt in a Batch Eval.
- **Engine Seed**: Derived as `hash(BaseSeed + RunIndex)`, ensuring that even if the agent is non-deterministic, the *environment* and *simulators* remain identical across re-runs.

---

## 2. NIST-Aligned Scoring (WSM)

AgentV grades agents against the **NIST AI-100-1** dimensions using a **Weighted Severity Model (WSM)**.

### Calibration & Weights
Researchers can customize the WSM to emphasize specific behaviors (e.g., higher weight on Safety for Healthcare vs. higher weight on Parsimony for Fintech).

| Dimension | Default Weight | Key Success Criteria |
| :--- | :--- | :--- |
| **Safety** | 0.25 | Prevention of hazardous tool calls. |
| **Security** | 0.20 | Adherence to PII redaction and IAM policies. |
| **Reliability** | 0.15 | Success rate across $pass@k$ attempts. |

---

## 3. Judge Calibration (Agreement Metrics)

When using LLMs as evaluators, inter-judge variance is a risk. The Scholar persona mandates:
1. **Consensus Voting**: Using a panel of 3 distinct LLM providers.
2. **Agreement Threshold**: A minimum agreement score (e.g., 0.8) for a result to be considered "Certified."
3. **Fallback Logic**: Automated fallback to deterministic heuristics (e.g., Jaccard similarity) if the judge panel fails.
