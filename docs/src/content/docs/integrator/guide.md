---
title: Agent Integration Guide
description: Step-by-step instructions for connecting your AI agents to the AgentV harness.
---

Integrating an agent with AgentV follows a "Zero-Touch" philosophy, supporting everything from local Python scripts to enterprise-grade HTTP services.

## 🚀 Quick Start (HTTP)

The fastest way to integrate is via a standard HTTP POST endpoint.

### 1. The Agent Interface
Your agent should expose a POST endpoint (e.g., `/execute`) that accepts and returns JSON.

**Request Protocol:**
```json
{
  "task": "Help me with my bill.",
  "history": [],
  "metadata": {}
}
```

**Completion Protocol:**
```json
{
  "response": "I can help with that. What is your account number?",
  "done": false
}
```

### 2. Configuration
Point the harness to your agent's URL in your `.env` file:

```ini
AGENT_API_URL=http://localhost:5001/execute
```

### 3. Execution
Run a benchmark using the default HTTP protocol:

```bash
agentv evaluate --run-id <id>
```

---

## 🛠 Supported Agent Protocols

AgentV supports a wide range of communication patterns. Use the `--protocol` and `--agent` flags to select your target.

| Protocol | Description | CLI Example |
| :--- | :--- | :--- |
| **HTTP** | Standard web API interaction. | `--protocol http --agent http://localhost:5001/execute` |
| **Local** | Spawns a local process (stdin/stdout). | `--protocol local --agent-cmd "python my_agent.py"` |
| **Socket** | TCP or Unix socket communication. | `--protocol socket --agent-socket tcp:127.0.0.1:9000` |
| **OpenAI** | Official OpenAI API / Assistants. | `--protocol openai --agent openai://gpt-5.4-mini` |
| **Claude** | Anthropic Claude API. | `--protocol claude --agent claude://claude-4-6-sonnet` |
| **Gemini** | Google Gemini API (includes Vertex AI). | `--protocol gemini --agent gemini://gemini-2.5-flash` |
| **Ollama** | Local model execution. | `--protocol ollama --agent ollama://llama4` |

---

## 🏗 Framework Adapters

AgentV includes native adapters for the leading agentic frameworks.

### AG2 (formerly AutoGen)
```bash
pip install ag2
agentv evaluate --run-id <id> --protocol ag2 --agent ag2://localhost:8000
```

### LangChain / LangGraph
```bash
pip install langchain langgraph
agentv evaluate --run-id <id> --protocol langgraph --agent langgraph://localhost:8000/graph
```

### CrewAI
```bash
pip install crewai
agentv evaluate --run-id <id> --protocol crewai
```

---

## 🧪 Verification & Debugging

### Trace Replay
If your agent makes a "wrong turn," use the `replay` command to step through the interaction logs.
```bash
agentv replay --run-id <id>
```

### Visual Debugger
Launch the `console` to see real-time Mermaid trajectories of your agent's decision-making process.
```bash
agentv console
```
:::tip
In the Visual Debugger, use the **"Isolate Root Cause"** feature to jump directly to the turn where your agent diverged from the ground truth.
:::
