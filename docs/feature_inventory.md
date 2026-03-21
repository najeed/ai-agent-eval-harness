# Feature Inventory - MultiAgentEval

This document provides a comprehensive inventory of the capabilities, tools, and technical features of the Zero-Touch MultiAgentEval.

## 1. Zero-Touch Core (Evaluation Engine)
The foundation of the harness, designed for framework-agnostic execution.
- **Dynamic Adapter Discovery**: Automatically recognizes agent protocols (`http`, `local`, `socket`, `openai`, `gemini`, `grok`, `autogen`, `langgraph`, `crewai`, etc.) via plugin hooks.
- **Flight Recorder (`run.jsonl`)**: Captures every state transition, tool call, and agent response in a deterministic, append-only log.
- **Stateful Tool Sandbox**: A secure environment for tool execution with VFS (Virtual File System) and policy guardrails.
- **Multi-turn Conversation Loop**: Robust handling of complex, long-running agentic tasks.
- **Human-In-The-Loop (HITL)**: Native support for pausing evaluations to request human intervention.

## 2. Semantic Bridge & Drift Management
Closing the loop between production behavior and evaluation rigor.
- **Import Drift**: CLI utility to convert real-world production traces into actionable evaluation scenarios.
- **AES (Agent Eval Specification)**: A portable, YAML-based benchmark format for sharing and versioning evaluative tasks.
- **Scenario Linter**: Automated quality scoring for AES files, ensuring balance and metadata completeness.
- **Adversarial Mutator**: Injects typos, ambiguity, and prompt-injection variants into scenarios to test agent robustness.

## 3. Research & Performance Metrics
Scientific-grade measurement of agent capabilities.
- **pass@k Scoring**: Measures robustness by calculating success probability over multiple attempts.
- **Success Consistency**: Analyzes the variance in agent outcomes across identical runs.
- **Wilson Score Confidence Intervals**: Provides 95% confidence bounds for all reported pass rates.
- **Grounding Coverage**: Visualizes tool and knowledge-base utilization via HTML heatmaps.
- **Latency & Cost Tracking**: P95 latency monitoring and precise token-based costing mapped to configurable pricing models.

## 4. Compliance & Assurance (New)
Enterprise-grade audit and regulatory tools, integrated directly into the core.
- **Source of Truth Bundling**: Core `ArtifactPlugin` for packaging results into signed, immutable zip files.
- **SHA-256 Integrity Verification**: Automated manifest generation and verification to prevent result tampering.
- **Audit Manifests**: Professional JSON audit logs for every evaluation batch.
- **Regulatory Exports**: CLI-ready commands for generating "compliance-ready" submission packages.

## 5. Visual Suite & Reporting
Professional-grade dashboards and debugging tools.
- **Interactive Leaderboards**: Stunning HTML reports with sortable metrics and failure distribution charts.
- **Failure Taxonomy**: Automated classification of failures into `hallucination`, `timeout`, `sandbox_breach`, etc.
- **Visual Trajectory Reconstruction**: Reconstructs agent conversation paths as interactive nodes.
- **Pilot vs. Standard Modes**: Intelligent reporting that distinguish between rapid iteration (watermarked previews) and verified benchmarks.

## 6. Developer Tools (The "Doctor" Suite)
Diagnostics and maintenance utilities.
- **Harness Doctor**: Self-diagnostic tool to verify environment, dependencies, and plugin health.
- **Scenario Scaffold**: Interactive CLI for generating new evaluation benchmarks via simple PRDs.
- **Trace Explainer**: High-fidelity root cause diagnostics with confidence scoring and forensic reasoning (e.g., policy violations vs. induced errors).
- **Judge Calibration**: Measures AI judge agreement against human ground truth.
