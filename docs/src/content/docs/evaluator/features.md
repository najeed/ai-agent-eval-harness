---
title: Feature Inventory
description: Comprehensive overview of AgentV capabilities, tools, and technical features.
---

This inventory provides a comprehensive overview of the capabilities, tools, and technical features of the Zero-Touch AgentV platform.

## 1. Zero-Touch Core (Evaluation Engine)

The foundation of the harness, designed for framework-agnostic execution and high-fidelity measurement.
- **Modular Plugin Bus**: Lifecycle hooks (`before_evaluation`, `on_turn_start`, `after_evaluation`) that allow extending the harness without modifying the core.
- **Dynamic Adapter Discovery**: Automatically recognizes and registers agent protocols (`http`, `sse`, `local`, `openai`, `gemini`, `claude`, `grok`, `ollama`) via the `AgentAdapterRegistry`.
- **Modern Streaming Support (SSE)**: Built-in support for `text/event-stream` agents, with automated chunk accumulation and JSON normalization.
- **Flight Recorder (`run.jsonl`)**: Captures every state transition, tool call, and agent response in a deterministic, append-only log.
- **Virtual File System (VFS)**: State-aware sandboxing for tool execution with automated rollback and isolation.
- **Asymmetric Trust Protocol (ED25519)**: Integrated `Verifier` for signatures, providing non-repudiable audit trails.
- **NIST AI-100-1 Trustworthiness Alignment**: Standardized scoring based on the Weighted Severity Model (WSM) across 7 critical AI dimensions, aligned with **NIST AI RMF principles**.

## 2. Security & Compliance (Hardened)

Enterprise-grade protection and regulatory audit tools.
- **Hardened Sandbox (Docker)**: Isolated execution for agent tools using Docker containers to prevent host contamination.
- **Shell Metacharacter Filtering**: Multi-layered defense against command injection in tool parameters.
- **Credential Stripping**: Automated logic to strip sensitive keys from metadata before trace signing.
- **WORM Audit Logs**: Write-Once-Read-Many event streaming for immutable regulatory compliance.
- **Enterprise Identity & PBAC**: Extender-ready provider pattern with support for SSO and granular permission nodes.

## 3. Semantic Bridge & Drift Management

Closing the loop between production behavior and evaluation rigor.
- **Import Drift**: CLI utility to convert production JSONL traces into actionable evaluation scenarios.
- **AES (Agent Eval Specification)**: A portable, YAML-based benchmark format for sharing and versioning complex agentic tasks.
- **Adversarial Mutator**: Injects typos, ambiguity, and prompt-injection variants into scenarios to test mission-critical robustness.

## 4. Ecosystem & Framework Adapters

First-class, zero-touch support for leading AI agent frameworks.
- **LangGraph v2 & AutoGen**: Seamless integration for chain-of-thought and graph-based agents.
- **Google GenAI (April 2026)**: Official support for Gemini 2.5 Flash via the `google-genai` SDK.
- **OpenTelemetry v1.40.0**: High-fidelity observability baseline for all internal signals and events.
- **Claude Code & xAI Grok**: Optimized adapters for the latest frontier models.
- **Ollama**: Local-first evaluation for private or air-gapped environments.

## 5. Research & Performance Metrics

Scientific-grade measurement of agent capabilities.
- **Robust Semantic Judging (Luna-Judge)**: Industrial LLM-as-Judge layer with automated regex-based score extraction, reasoning-aware parsing, and fallback Jaccard similarity heuristics.
- **Wilson Score Confidence Intervals**: Provides 95% statistical confidence bounds for all reported pass rates.
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
