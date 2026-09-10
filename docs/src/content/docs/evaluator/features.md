---
title: Feature Inventory
description: Comprehensive overview of AgentV capabilities, tools, and technical features.
---

This inventory provides a comprehensive overview of the capabilities, tools, and technical features of the Zero-Touch AgentV platform.

## 1. Zero-Touch Core (Evaluation Engine)

The foundation of the harness, designed for framework-agnostic execution and high-fidelity measurement.
- **Modular Plugin Bus**: Lifecycle hooks (`before_evaluation`, `on_turn_start`, `after_evaluation`) that allow extending the harness without modifying the core.
- **Dynamic Adapter Discovery**: Automatically recognizes and registers agent protocols (`http`, `sse`, `local`, `openai`, `gemini`, `claude`, `grok`, `ollama`) via the `AgentAdapterRegistry` with lazy dynamic imports.
- **Modern Streaming Support (SSE)**: Built-in support for `text/event-stream` agents, with automated chunk accumulation and JSON normalization.
- **Flight Recorder (`run.jsonl`)**: Captures every state transition, tool call, and agent response in a deterministic, append-only log with intrinsically fail-closed persistence in certification mode.
- **Centralized LLM Resilience & Error Classifier**: Domain-specific error classification (`LLMRateLimitError`, `LLMQuotaExceededError`, `LLMTransientError`) and full-jitter exponential backoff retry harness (`execute_with_resilience`).
- **Dedicated Acceptance Testing Layer**: Comprehensive schema-driven acceptance suite (`tests/acceptance/`) paired with the zero-tolerance CI release gate (`tools/ci/acceptance_gate.py`).
- **Virtual File System (VFS)**: State-aware sandboxing for tool execution with automated rollback and isolation.
- **Asymmetric Trust Protocol (ED25519 & Hybrid PQC)**: Integrated cryptographic verification for detached envelopes, pure RFC 8785 JSON Canonicalization Scheme (JCS), and mandatory external trust roots.
- **NIST AI-100-1 Trustworthiness Alignment**: Standardized scoring based on the Weighted Severity Model (WSM) across 7 critical AI dimensions, aligned with **NIST AI RMF principles**.

## 2. Security & Compliance (Hardened)

Enterprise-grade protection and regulatory audit tools.
- **Three-Pillar Authentication Architecture**: Persistent zero-config bootstrap key onboarding (`.aes/keys/bootstrap.key`), non-blocking read-only Viewer role fallback, sliding-window IP rate limiting (10 attempts/min on `/api/auth/login`), secure session cookie flags (`HttpOnly`, `SameSite=Lax`), and production fail-fast enforcement.
- **Hardened Sandbox (VFS / Jails)**: Isolated execution for agent tools using local process jails and virtualized file systems to prevent host contamination.
- **Shell Metacharacter Filtering**: Multi-layered defense against command injection in tool parameters.
- **Credential Stripping**: Automated logic to strip sensitive keys from metadata before trace signing.
- **In-Archive Direct ZIP Verification**: Verifies internal bundle byte streams directly without disk extraction, enforcing strict path traversal guards (`..`, absolute paths, drive prefixes).
- **WORM Audit Logs**: Write-Once-Read-Many event streaming for immutable regulatory compliance.
- **Enterprise Identity & PBAC**: Extender-ready provider pattern with support for SSO and granular permission nodes.

## 3. Semantic Bridge & Drift Management

Closing the loop between production behavior and evaluation rigor.
- **Import Drift**: CLI utility to convert production JSONL traces into actionable evaluation scenarios.
- **AES (Agent Eval Specification)**: A portable, YAML/JSON-based benchmark format for sharing and versioning complex agentic tasks.
- **3D Runtime Mutation Engine**: Generates deterministic adversarial variants across a 3D coordinate space ($V \times O \times T$) of 13 vectors (Syntactic, Behavioral, Adversarial, Context Bleed, Protocol, Timing, Chaos, State, Retrieval, Authorization, Schema Drift, Replay, Latency), 13 operations, and 6 risk tiers.
- **Algebraic Mutation Combinators**: Compose complex mutation pipelines using functional primitives (`sequence`, `repeat`, `probability`, `after_event`, `before_commit`, `between_steps`, `concurrent`) with deterministic seed chaining.

## 4. Ecosystem & Framework Adapters

First-class, zero-touch support for leading AI agent frameworks and LLM transports.
- **4-Tier Packaging Architecture**: Clean separation between core runtime (`agentv`), direct provider SDKs (`provider-gemini`), framework substrates (`framework-langchain`, `framework-langgraph`, `framework-ag2`, `framework-crewai`), and LangChain provider integrations (`langchain-*`).
- **Lazy Adapter Imports**: Adapter modules dynamic load framework dependencies at execution time, ensuring zero startup penalty or top-level import conflicts.
- **Direct Zero-SDK REST Transports**: Native high-throughput `aiohttp` HTTP transports for OpenAI, Anthropic, Grok, and Ollama endpoints without external client dependencies.
- **Google GenAI Direct SDK**: Official support for Gemini 2.5 and Gemini 3.7 Flash via the `google-genai` SDK and `gemini://` URI handler.
- **LangGraph v2 & AG2 / AutoGen**: Seamless integration for chain-of-thought, state-graph, and multi-agent systems.
- **OpenTelemetry v1.40.0**: High-fidelity observability baseline for all internal signals and events.
- **Ollama**: Local-first evaluation for private or air-gapped environments.

## 5. Research & Performance Metrics

Scientific-grade measurement of agent capabilities.
- **Robust Semantic Judging (Luna-Judge)**: Industrial LLM-as-Judge layer with automated regex-based score extraction, reasoning-aware parsing, and fallback Jaccard similarity heuristics.
- **Scientific Pass Rate Metrics (Pass@k)**: Provides high-fidelity success measurement across multiple evaluation attempts.
- **Pass-Rate Regression Trend Analysis** (`trend`): OLS linear regression over a trailing window of sequential runs to detect performance degradation over time. Integrates with CI via `--exit-on-regression`.
- **Grounding Coverage**: Heatmaps visualizing tool and knowledge-base utilization within scenarios.
- **Cost/Latency Analytics**: P95 latency monitoring and precise token-based costing.

## 6. Visual Suite & Standalone Reporting

Professional-grade dashboards and debugging tools.
- **Standalone HTML Reports**: Single-file, CSS-embedded reports designed for sharing via email or Slack without external dependencies.
- **HuggingFace Mirroring**: One-click dataset export (`--push-hf`) for community benchmark sharing.
- **Failure Taxonomy**: Automated classification of failures into a stratified, NIST-aligned failure hierarchy.
- **Interactive Trajectory Map**: Visual timeline in the Visual Debugger visualizing agent decision paths.

## 7. Developer Experience (`agentv`)

Diagnostics and maintenance utilities for the engineer.
- **Quickstart Demo**: 60-second "Instant Gratification" flow including agent spawn and premium report generation.
- **Interactive Contributor Wizard**: CLI (`contribute`) for building and submitting scenarios.
- **Harness Doctor**: Self-diagnostic tool to verify environment health and dependency status.
- **Scenario Scaffold**: Markdown-to-AES conversion (`spec-to-eval`) using local LLMs.
- **Trace Replay**: Step-by-step terminal playback of previous runs.
