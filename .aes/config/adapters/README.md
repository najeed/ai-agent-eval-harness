# Adapters Multi-Layer Governance

This directory contains the authoritative activation policies for all agent communication adapters.

## 🏛️ Tripartite Activation Model

AgentV distinguishes between three categories of connectivity:

1.  **Protocols**: Basic infrastructure transport.
    - **`http`**: Standard REST bridge.
    - **`local`**: Local subprocess execution (Secure bypass).
    - **`socket`**: Raw IPC/TCP pipe.
2.  **Providers**: Model-specific payload handlers.
    - **`openai`**, **`claude`**, **`gemini`**, **`grok`**, **`ollama`**.
3.  **Frameworks**: High-level orchestration SDKs.
    - **`ag2`** (formerly AG2), **`crewai`**, **`langgraph`**, **`langchain`**.

## 🔒 Security & Mandatory Protocols

According to the [Adapters Specification](/spec/adapters/adapters.schema.json), the `active_protocols` list is **MANDATORY**. If this list is missing, the engine will fail to initialize.

## 🛡️ Zero-Trust Baseline (Security-by-Default)

If no administrative policy is detected, AgentV defaults to a **Zero-Trust Baseline**:
- Only `http` and `openapi` protocols are enabled.
- All Providers and Frameworks are **DISABLED**.
- This prevents unauthorized lateral movement or subprocess execution in misconfigured environments.
