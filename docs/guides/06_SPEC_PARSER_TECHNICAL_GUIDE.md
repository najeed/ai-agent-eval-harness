# Technical Guide: Spec-to-Eval Hybrid Parsing Strategy

The `multiagent-eval spec-to-eval` command transforms raw Markdown PRDs (Product Requirement Documents) into executable JSON/AES scenarios. It employs a **Hybrid Parsing Strategy** to balance deterministic precision with LLM flexibility.

---

## 🏗️ 1. The "Gold Standard" Structural Parser
This is a high-speed, zero-cost deterministic parser that uses regular expressions to extract structured data. It recognizes a specific Markdown pattern designed for enterprise-grade benchmarks.

### Expected Markdown Structure:
*   **H1 Title**: `# PRD: [Scenario Name]` (or `# [Scenario Name]`)
*   **Metadata Block**: Key-value pairs using bold keys, e.g., `**Industry:** Finance`.
*   **Overview Section**: `## Overview` or `## Scenario Overview`.
*   **Tools Section**: `## Tools` (Collects global tools like `loan_api` for all tasks).
*   **Tasks Section**: `## Tasks` or `## Test Cases`.
    *   **H3 Task Headers**: `### 1. [Task Title]`
    *   **Bullet Task Fallback**: Supports `- **[Title]**: [Description]` for rapid authoring.
    *   **Task Metadata**: Bullets within the task section for `Expected Outcome`, `Tools`, and `Criteria`.
*   **Topology Section**: `## Agent Topology` (Namespace permissions).
*   **Policies Section**: `## Policies` (Governance constraints).

### Benefits:
*   **Deterministic**: 100% predictable output.
*   **Zero-Latency**: Runs instantly without external API calls.
*   **High Precision**: Avoids LLM hallucinations for critical tool names and success thresholds.

---

## 🤖 2. LLM Synthesis Fallback
If the structural parser finds **no tasks** (indicating a non-standard or highly creative PRD format), the system automatically triggers an LLM-based synthesis.

### How it Works:
1.  The CLI prints: `[SpecParser] No tasks found via structural parsing. Synthesizing from rules...`
2.  The entire Markdown text is sent to the configured provider (Gemini 2.5 Flash recommended).
3.  The LLM interprets the business logic and generates 3-5 representative tasks (Positive, Negative, and Adversarial).
4.  The system attempts to parse the LLM's JSON response and backfills defaults.

---

## 🛡️ 3. Robustness Features
*   **Synonym Recognition**: Headers like "Test Cases" are automatically treated as "Tasks".
*   **Global Tool Injection**: Tools defined in a global `## Tools` section are automatically added to the `required_tools` of every task if not specifically overridden.
*   **Force Overwrite**: Use `--force` to skip the overwrite confirmation prompt for rapid iteration.

---

## 📖 4. Workflow Example
To convert a PRD and fill in missing schema defaults in one go:
```bash
multiagent-eval spec-to-eval --input docs/specs/my_prd.md --output scenarios/my_scenario.json --fill-defaults --force
```
