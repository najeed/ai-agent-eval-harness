# MultiAgentEval Guide

> This document is the single authoritative reference for using, extending, and developing the MultiAgentEval framework.
> It is organized into three levels: **Quick Start**, **User Manual**, and **Developer Guide**.

---

## 1) Quick Start (Get Running in 60 Seconds)

### 1.1 Install and Run

1. Clone and install MultiAgentEval:
```bash
git clone https://github.com/najeed/ai-agent-eval-harness.git
cd ai-agent-eval-harness
pip install -e .
```

2. Run the Quickstart Demo:
```bash
multiagent-eval quickstart
```

**What it does:** Spawns a mock sample agent, runs a troubleshooting evaluation, and generates a **Premium HTML report** in `reports/`. 

> [!TIP]
> **Integrated Visual Suite**: Launch the premium web dashboard via `multiagent-eval console`. It now features a Live Debugger that streams real-time state from your evaluations using the Zero-Touch `RemoteBridgePlugin`.

### 1.2 Useful CLI Commands
- `multiagent-eval console`: Launch the React Visual Debugger GUI for visual management.
- `multiagent-eval doctor`: Check your environment health.
- `multiagent-eval list --search <query>`: Search the scenario catalog (supports faceted filtering).
- `multiagent-eval lint --path <path>`: Verify scenario quality and AES specification compliance.
- `multiagent-eval spec-to-eval --fill-defaults`: Convert rough specs into valid, lint-passable scenarios.
- `multiagent-eval auto-translate --input <doc>`: Convert PDFs/Docs into JSON scenarios using Ollama.
- `multiagent-eval run --scenario <benchmark-uri>`: Zero-config execution for community benchmarks (GAIA, AssistantBench).
- `multiagent-eval report --path <path>`: Generate a standalone Premium HTML report (reconstructed from any `.jsonl` trace).
- `multiagent-eval replay --path <path>`: View the step-by-step history of a run in terminal.
- Advanced Utilities: `install`, `analyze`, `ci generate`, `failures search`, and `explain`.

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
- **Visual Scenario Editor**: A visual React UI for constructing AES logic and saving it directly to the catalog, accessible via the `console` command.

---

## 3) Developer Guide (Zero-Touch Core Architecture)

### 3.1 Architecture Overview
The harness uses a **Zero-Touch Core** design, where all major capabilities are hot-swappable via the **Modular Plugin Bus**:
1. **Runner**: Orchestrates high-level loop (e.g., pass@k).
2. **Session**: Manages multi-turn conversation and context.
3. **EventEmitter**: Broadcasts state changes through a central bus.
4. **Discovery Engine**: Centrally manages dynamic discovery of plugins and adapters via `eval_runner/discovery.py`.
5. **AgentAdapterRegistry**: Dynamically registers agent protocols at runtime using discovery.
6. **Plugins**: Standard lifecycle listeners and interceptors, discovered automatically.

### 3.2 Extensibility
- **Interception**: Use `on_tool_request` to block or proxy tool calls.
- **Observability**: Subscribe to `CoreEvents` via the `EventEmitter` for non-blocking logging.
- **Advanced Evaluation**: Standard support for dot-notation in state verification, High-Fidelity Calculation Accuracy, and Judge Guarding (strict failure for required metrics).
- **Secure Namespaces**: Legacy `extend_cli` is removed. Use `on_register_commands` to register commands under the `multiagent-eval plugin <name>` sub-command.
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
multiagent-eval run --scenario industries/<ind>/scenarios/<file>.json
```

---

For deep-dives into specific topics, see the specialized guides in `docs/guides/help/`:
- [State-Level Triage & VFS Guide](06_TRIAGE_ENGINE_AND_VFS.md) — how root cause isolation works
- [Adding World Shims](08_ADDING_WORLD_SHIMS.md) — extending the simulator suite
- [Plugin Development](../../plugins.md) — zero-touch extensibility
