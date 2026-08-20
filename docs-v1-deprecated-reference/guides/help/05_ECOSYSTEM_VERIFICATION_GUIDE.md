# Ecosystem Verification Guide (Comprehensive)

This guide provides step-by-step instructions to manually verify all third-party integrations, including adapters and plugins, to ensure "Partner Production-Ready" status.

---

## 🚦 1. Prerequisites & Global Setup

> [!IMPORTANT]
> **Python Version**: Use **Python 3.14 (Stable)**.
> While 3.14 is the current stable baseline (released Oct 2025), some downstream dependencies (like `jiter` for `openai`) may still require a local **Rust** compiler to build on certain Windows configurations if pre-built wheels are not detected.

### Troubleshooting: Build Failures (Rust & C++)
If you see `error: subprocess-exited-with-error` mentioning `Cargo/Rust` or `cl.exe`:

#### 1. Rust Build Failure (e.g., `jiter`)
1. **Install Rust**: Download and run `rustup-init.exe` from [rustup.rs](https://rustup.rs/).
2. **Select Default**: Use the default installation (`x86_64-pc-windows-msvc`).
3. **Restart Terminal**: Ensure `cargo` is in your PATH.

#### 2. C++ Extension Build Failure (e.g., `regex`)
This occurs when a package lacks a pre-built wheel for Python 3.14 and requires local C compilation.
1. **Install MSVC Build Tools**: Download [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/).
2. **Select Workload**: In the installer, check **"Desktop development with C++"**.
3. **Verify Kits**: Ensure **"Windows 10/11 SDK"** and **"MSVC v14x - VS 2022 C++ x64/x86 build tools"** are selected in the side panel.
4. **Restart Terminal** and retry: `pip install -e .`

Before verifying individual integrations, ensure the harness is installed in editable mode:

```bash
cd ai-agent-eval-harness
pip install -e .
```

### Configure Environment Variables
Create or update your `.env` file with the following keys:

```bash
# Proprietary Models
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=ant-api-...
GEMINI_API_KEY=...
XAI_API_KEY=...

# Ecosystem Defaults
OLLAMA_HOST=http://localhost:11434
AG2_API_URL=http://localhost:5002/query
```

---

## 🧠 2. Local LLM Verification (Ollama)

**Goal**: Verify that the harness can communicate with local models and use them for evaluation/judging.

1. **Install Ollama**: Download from [ollama.com](https://ollama.com).
2. **Pull Model**:
   ```bash
   ollama pull llama4
   ```
3. **Verify Adapter**:
   ```bash
   agentv run --scenario scenarios/luna_demo.json --protocol ollama --agent ollama://llama4
   ```
4. **Verify Luna-Judge (Ollama fallback)**:
   - Ensure `JUDGE_PROVIDER=ollama` in `.env`.
   - Run: `agentv evaluate --run-id <id>`

---

## 🛠 3. Framework Integrations (Adapters)

### A. Microsoft AG2
**Goal**: Verify the `AG2://` protocol and multi-agent interaction.

1. **Install Dependencies**:
   ```bash
   pip install pyAG2
   ```
2. **Run Sample AG2 Agent**: (Requires a separate server script or the `quickstart` mock).
3. **Run Evaluation**:
   ```bash
   agentv evaluate --run-id <id> --protocol AG2 --agent AG2://localhost:5002
   ```

### B. LangChain / LangGraph
**Goal**: Verify RemoteRunnable and state-aware graph adapters.

1. **Install Dependencies**:
   ```bash
   pip install langchain langchain-openai langgraph
   ```
2. **Verify LangChain Adapter**:
   ```bash
   agentv evaluate --run-id <id> --protocol langchain --agent langchain://localhost:8000/my-agent
   ```
3. **Verify LangGraph (Structural)**:
   - Since the LangGraph adapter is currently an **Architectural Mock**, verification confirms the engine's ability to route requests through the plugin hook without hardcoding.
   - Run: `agentv evaluate --run-id <id> --protocol langgraph`

### C. CrewAI
**Goal**: Verify task-based multi-agent orchestration.

1. **Install Dependencies**:
   ```bash
   pip install crewai
   ```
2. **Verify Adapter (Structural Mock)**:
   - Verification confirms the lifecycle hook `on_discover_adapters` correctly registers the `crewai://` protocol.
   - Run: `agentv evaluate --run-id <id> --protocol crewai`

---

## 💎 4. Proprietary Models (Production Verification)

Verify that the `openai`, `claude`, `gemini`, and `grok` adapters are production-ready using live API keys.

| Provider | Protocol | Verification Command |
| :--- | :--- | :--- |
| **OpenAI** | `openai://` | `agentv run --protocol openai --agent openai://gpt-5.4-mini` |
| **Anthropic**| `claude://` | `agentv run --protocol claude --agent claude://Claude-4.6-Sonnet` |
| **Google** | `gemini://` | `agentv run --protocol gemini --agent gemini://gemini-2.5-flash` |
| **xAI** | `grok://` | `agentv run --protocol grok --agent grok://grok-4.20-multi-agent` |

---

## 🔌 5. Plugin Verification

### A. RemoteBridgePlugin (Live Debugger)
1. Launch the console: `agentv console`.
2. Run an evaluation.
3. Observe real-time state updates in the **Visual Debugger** tab. This verifies the `on_agent_turn_start` and `on_turn_end` hooks.

### C. CoveragePlugin (Grounding Heatmaps)
1. Run: `agentv evaluate --run-id <id>`.
2. Check `reports/coverage/`: Verify that `telecom_coverage.html` is generated. This ensures the `on_tool_result` hook is correctly capturing grounding events.

---

## ⚖️ 6. Judge Layer & Calibration Verification

**Goal**: Confirm specialized rubric routing and judge-to-human alignment checking.

1. **Verify Rubric Selection**:
   - Run a scenario with a specialized rubric:
     ```bash
     agentv evaluate --run-id <id>
     ```
   - Check the `run.jsonl` trace to ensure the correct rubric prompt was injected (requires inspecting the event payload).

2. **Verify Calibration Command**:
   - Ensure you have a `run.jsonl` with both `luna_judge_score` and `human_score` field.
   - Run:
     ```bash
     agentv calibrate --run-id <id>
     ```
   - Verify the ASCII "JUDGE CALIBRATION REPORT" is displayed with MAE and Pearson Correlation.

---

## ✅ 7. Final "Production-Ready" Checklist

- [ ] `agentv doctor` returns all GREEN status.
- [ ] No `ImportError` when running any ecosystem adapter.
- [ ] API keys are correctly masked in log outputs.
- [ ] Timeouts are respected (verified by setting `DEFAULT_ADAPTER_TIMEOUT=1`).
- [ ] Results generated in `reports/` include detailed framework metadata.
