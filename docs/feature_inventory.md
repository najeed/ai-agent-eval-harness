# Feature Inventory - MultiAgentEval

This document provides a comprehensive inventory of the capabilities, tools, and technical features of the Zero-Touch MultiAgentEval.

## 1. Zero-Touch Core (Evaluation Engine)
The foundation of the harness, designed for framework-agnostic execution and high-fidelity measurement.
- **Modular Plugin Bus**: Lifecycle hooks (`before_evaluation`, `on_turn_start`, `after_evaluation`) that allow extending the harness without modifying the core.
- **Dynamic Adapter Discovery**: Automatically recognizes and registers agent protocols (`http`, `local`, `openai`, `gemini`, `claude`, `grok`, `ollama`) via the `AgentAdapterRegistry`.
- **Flight Recorder (`run.jsonl`)**: Captures every state transition, tool call, and agent response in a deterministic, append-only log.
- **Virtual File System (VFS)**: State-aware sandboxing for tool execution with automated rollback and isolation.
- **Deterministic Trace Signing**: Integrated `Verifier` for SHA-256 signed run traces to ensure data integrity for benchmarks.

## 2. Security & Compliance (Hardened)
Enterprise-grade protection and regulatory audit tools.
- **Hardened Sandbox (Docker)**: (Enterprise) Isolated execution for agent tools using Docker containers to prevent host contamination.
- **Shell Metacharacter Filtering**: Multi-layered defense against command injection in tool parameters.
- **Credential Stripping**: Automated logic to strip sensitive keys (API keys, tokens) from metadata before trace signing.
- **WORM Audit Logs**: Write-Once-Read-Many event streaming for immutable regulatory compliance.
- **Audit Manifests**: Professional JSON manifests generation for every evaluation batch.
- **Enterprise Identity & PBAC**: Extensible `AuthManager` provider pattern with support for SSO (OIDC/SAML) and granular permission nodes (e.g., `scenarios:read`, `eval:trigger`).
- **Session-Based Governance**: Secure, server-side session management with HttpOnly cookies, replacing legacy plaintext storage.

## 3. Semantic Bridge & Drift Management
Closing the loop between production behavior and evaluation rigor.
- **Import Drift**: CLI utility to convert production JSONL traces into actionable evaluation scenarios.
- **AES (Agent Eval Specification)**: A portable, YAML-based benchmark format for sharing and versioning complex agentic tasks.
- **Scenario Linter**: Automated quality scoring with Gold/Silver/Bronze badges for AES files.
- **Adversarial Mutator**: Injects typos, ambiguity, and prompt-injection variants into scenarios to test mission-critical robustness.

## 4. Ecosystem & Framework Adapters
First-class, zero-touch support for the leading AI agent frameworks.
- **LangChain & LangGraph**: Seamless integration for chain-of-thought and graph-based agents.
- **AutoGen & CrewAI**: Direct support for multi-agent orchestrators.
- **Claude Code & xAI Grok**: Optimized adapters for the latest frontier models.
- **Ollama**: Local-first evaluation for private or air-gapped environments.

## 5. Research & Performance Metrics
Scientific-grade measurement of agent capabilities.
- **pass@k Scoring**: Measures robustness by calculating success probability over multiple stochastic attempts.
- **Judge Guarding**: Strict failure enforcement for required metrics, preventing "soft passes" on safety-critical tasks.
- **Wilson Score Confidence Intervals**: Provides 95% statistical confidence bounds for all reported pass rates.
- **Grounding Coverage**: Heatmaps visualizing tool and knowledge-base utilization within scenarios.
- **Cost/Latency Analytics**: P95 latency monitoring and precise token-based costing mapped to configurable pricing tiers.

## 6. Visual Suite & Standalone Reporting
Professional-grade dashboards and debugging tools.
- **Standalone HTML Reports**: Single-file, CSS-embedded reports that can be shared via email or Slack without external dependencies.
- **HuggingFace Mirroring**: One-click dataset export (`--push-hf`) for community benchmark sharing.
- **Failure Taxonomy**: Automated classification of failures into `hallucination`, `timeout`, `sandbox_breach`, etc.
- **Interactive Trajectory Map**: Interactive Mermaid graphs visualizing agent decision paths and environment loops.

## 7. Developer Experience (`multiagent-eval`)
Diagnostics and maintenance utilities for the engineer.
- **Quickstart Demo**: 60-second "Instant Gratification" flow including agent spawn and premium report generation.
- **Interactive Contributor Wizard**: Step-by-step CLI (`contribute`) for building and submitting scenarios to the library.
- **Harness Doctor**: Self-diagnostic tool to verify environment health, dependency versions, and plugin status.
- **Scenario Scaffold**: Markdown-to-AES conversion (`spec-to-eval`) using local LLMs.
- **Trace Replay**: Step-by-step terminal playback of previous runs for rapid debugging.
