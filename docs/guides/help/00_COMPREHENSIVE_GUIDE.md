# AI Agent Evaluation Harness — Comprehensive Guide

> This document is the single authoritative reference for using, extending, and developing the AI Agent Evaluation Harness.
> It is organized into three levels: **Quick Start**, **User Manual**, and **Developer Guide**.

---

## 1) Quick Start (Get Running in 60 Seconds)

### 1.1 Install and Run

1. Clone and install the harness:
```bash
git clone https://github.com/najeed/ai-agent-eval-harness.git
cd ai-agent-eval-harness
pip install -e .
```

2. Run the Quickstart Demo:
```bash
eval-harness quickstart
```

**What it does:** Spawns a mock sample agent, runs a troubleshooting evaluation, and generates a **Premium HTML report** in `reports/`. 

> [!TIP]
> **Integrated Visual Suite**: Launch the premium web dashboard via `eval-harness console`. It now features a **Live Debugger** that streams real-time state from your evaluations using the Zero-Touch `RemoteBridgePlugin`.

### 1.2 Useful CLI Commands
- `eval-harness console`: Launch the React Native (Expo) Admin Console GUI for visual management.
- `eval-harness doctor`: Check your environment health.
- `eval-harness list --search <query>`: Search the scenario catalog (supports faceted filtering).
- `eval-harness lint <path>`: Verify scenario quality and AES specification compliance.
- `eval-harness spec-to-eval --fill-defaults`: Convert rough specs into valid, lint-passable scenarios.
- `eval-harness auto-translate --input <doc>`: Convert PDFs/Docs into JSON scenarios using Ollama.
- `eval-harness report <path>`: Generate a standalone **Premium HTML report** (reconstructed from any `.jsonl` trace).
- `eval-harness replay --path <path>`: View the step-by-step history of a run in terminal.
- **Advanced Utilities**: `install`, `analyze`, `ci generate`, `failures search`, and `explain`.

> [!NOTE]
> **Path Decoupling**: Evaluations can now be run from any directory. The harness automatically resolves relative dataset paths and tags ad-hoc scenarios as `local`.

---

## 2) User Manual (Scenario & Execution Guide)

### 2.1 Core Concepts
- **AES (Agent Eval Specification)**: A standardized JSON/YAML format for defining portable benchmarks.
- **Scenario**: A JSON file containing tasks, tools, and success criteria.
- **Task**: An individual instruction sent to the agent within a scenario.
- **Tool Sandbox**: A state-aware execution environment for agent tool calls.
- **Synthetic Datasets**: Auto-generated industry-specific CSV tabular data used to ground scenarios in reality.
- **Plugin System**: Lifecycle hooks to extend the harness without modifying the core.

### 2.2 Advanced CLI
- `evaluate --path <dir> --attempts 3`: Run batch evaluations with pass@k scoring.
- `import-drift --input <pord.jsonl>`: Convert production traces into regression tests.
- `mutate --input <file> --type injection`: Generate adversarial test variants for red-teaming.
- **Advanced Utilities**: `install`, `analyze`, `ci generate`, `failures search`, and `explain` ([Reference](../../cli_reference.md)).
- **Visual Scenario Editor**: A visual React Native UI for constructing AES logic and saving it directly to the catalog, accessible via the `console` command.

---

## 3) Developer Guide (Zero-Touch Core Architecture)

### 3.1 Architecture Overview
The harness uses a **Zero-Touch Core** design, where all major capabilities are hot-swappable via the **Modular Plugin Bus**:
1. **Runner**: Orchestrates high-level loop (e.g., pass@k).
2. **Session**: Manages multi-turn conversation and context.
3. **EventEmitter**: Broadcasts state changes through a central bus.
4. **AgentAdapterRegistry**: Dynamically discovers and registers agent protocols at runtime.
5. **Plugins**: Standard lifecycle listeners and interceptors.

### 3.2 Extensibility
- **Interception**: Use `on_tool_request` to block or proxy tool calls.
- **Observability**: Subscribe to `CoreEvents` via the `EventEmitter` for non-blocking logging.
- **Advanced Evaluation**: Standard support for **dot-notation** in state verification and **Judge Guarding** (strict failure for required metrics).
- **Secure Namespaces**: Legacy `extend_cli` is removed. Use `on_register_commands` to register commands under the `eval-harness plugin <name>` sub-command.
- **Ecosystem Adapters**: Official, zero-touch support for **LangChain**, **Ollama**, **OpenAI**, **Gemini**, **Claude**, **AutoGen**, and **xAI Grok**.
- **Immutability**: TurnContext and EvaluationContext are frozen to prevent accidental side-effects.

---

## 🧪 Testing & Verification
Run the full suite:
```bash
pytest tests/
```

For industry-specific scenarios:
```bash
eval-harness run industries/<ind>/scenarios/<file>.json
```

---

For deep-dives into specific topics like **Grounding Heatmaps** or **Adversarial Red-Teaming**, see the specialized guides in `docs/guides/`.
