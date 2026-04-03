# MultiAgentEval Walkthrough Syllabus

Welcome to the guided learning path for the **MultiAgentEval (v1.2.3)** platform. This curriculum is designed to move you from foundational exploration through industrial-grade governance.

---

## ⚙️ Key Setup Instructions

Before starting the walkthroughs, ensure your environment is correctly configured:

### 1. System Requirements
- **Python**: 3.9 or higher.
- **Dependencies**: Install the required libraries via pip:
  ```bash
  pip install -r requirements.txt
  ```

### 2. Environment Configuration (Provider-Agnostic)
The harness is agnostic by design, supporting any provider (Local, OpenAI, Anthropic, Gemini, etc.) and loading your keys via `python-dotenv`.
- Create a `.env` file in the project root.
- Set your required provider keys:
  - `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, etc.
  - Set `JUDGE_PROVIDER` (e.g., `openai`, `ollama`) to define your default evaluator.
- For high-stakes security, set your `AES_PRIVATE_KEY` (ED25519) to anchor your results.

### 3. Verification
Verify that the Scenario Catalog is accessible:
  ```bash
  python -m eval_runner.cli list
  ```
If you see a list of industrial benchmarks, you are ready to begin.

---

## 🎓 The Four-Phase Learning Path

### 🟢 [Phase 1 - Foundations - Beginner](./Phase%201%20-%20Foundations%20-%20Beginner)
**Focus**: Core loops, connectivity, and safety.
- **[Exploration](./Phase%201%20-%20Foundations%20-%20Beginner/discovery/README.md)**: Search and filter the industrial scenario catalog.
- **[Native Adapters](./Phase%201%20-%20Foundations%20-%20Beginner/adapters/README.md)**: Coordinate model communication via the unified adapter layer.
- **[Sandboxing](./Phase%201%20-%20Foundations%20-%20Beginner/sandboxing_and_shims/README.md)**: Witness "Zero-Touch" isolation and proxy interception.

### 🟡 [Phase 2 - Scale & Robustness - Intermediate](./Phase%202%20-%20Scale%20%26%20Robustness%20-%20Intermediate)
**Focus**: Industrial throughput and adversarial stress-testing.
- **[Batch Eval](./Phase%202%20-%20Scale%20%26%20Robustness%20-%20Intermediate/batch_evaluation/README.md)**: Manage multi-protocol concurrent fleets.
- **[Pack Install](./Phase%202%20-%20Scale%20%26%20Robustness%20-%20Intermediate/pack_installation/README.md)**: Deploy and archive industrial benchmark packs.
- **[Scenario Mutation](./Phase%202%20-%20Scale%20%26%20Robustness%20-%20Intermediate/scenario_mutation/README.md)**: Perform adversarial drift analysis through automated mutations.

### 🔴 [Phase 3 - Intelligence & Complexity - Advanced](./Phase%203%20-%20Intelligence%20%26%20Complexity%20-%20Advanced)
**Focus**: Complex workflows and rapid bootstrapping.
- **[Auto-Translate](./Phase%203%20-%20Intelligence%20%26%20Complexity%20-%20Advanced/auto_translation/README.md)**: Bootstrap AES scenarios from raw industrial PRDs.
- **[Multi-Agent Interactions](./Phase%203%20-%20Intelligence%20%26%20Complexity%20-%20Advanced/multi_agent/README.md)**: Orchestrate team-based agentic evaluations.
- **[DAG Loops & Flow Control](./Phase%203%20-%20Intelligence%20%26%20Complexity%20-%20Advanced/dag_loops/README.md)**: Master recursion and state-flow visualization.

### 🟣 [Phase 4 - Production & Governance - Expert](./Phase%204%20-%20Production%20%26%20Governance%20-%20Expert)
**Focus**: Scientific precision and zero-trust security pipelines.
- **[Trace Importer](./Phase%204%20-%20Production%20%26%20Governance%20-%20Expert/trace_importer/README.md)**: Capture and replay production failures as benchmarks.
- **[Root Cause Taxonomy](./Phase%204%20-%20Production%20%26%20Governance%20-%20Expert/root_cause_taxonomy/README.md)**: Generate diagnostic failure heatmaps.
- **[Calibration](./Phase%204%20-%20Production%20%26%20Governance%20-%20Expert/calibration/README.md)**: Achieve Judge-Human agreement (Spearman's Rho).
- **[State Parity](./Phase%204%20-%20Production%20%26%20Governance%20-%20Expert/state_parity/README.md)**: Detect architectural drift across evaluation mirrors.
- **[Cryptographic Verification](./Phase%204%20-%20Production%20%26%20Governance%20-%20Expert/cryptographic_verification/README.md)**: Anchor truth with ED25519 signatures.
- **[Industrial CI/CD Gate](./Phase%204%20-%20Production%20%26%20Governance%20-%20Expert/cicd_gate/README.md)**: Enforce automated release compliance thresholds.
- **[Luna-Judge & IJA Protocol](./Phase%204%20-%20Production%20%26%20Governance%20-%20Expert/luna_ija/README.md)**: Orchestrate multi-judge consensus (IJA).
- **[Human-In-The-Loop (HITL)](./Phase%204%20-%20Production%20%26%20Governance%20-%20Expert/hitl/README.md)**: Master shared governance with the Human Governor override.

---
*Ready to become an evaluation lead? Start with [Phase 1: Discovery](./Phase%201%20-%20Foundations%20-%20Beginner/discovery/README.md) next.*

