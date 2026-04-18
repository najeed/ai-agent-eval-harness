---
title: Integrator API Reference
description: High-fidelity REST protocol for the AgentV Roadmap (v1.5.0+).
---

The Integrator API provides programmatic access to the AgentV engine, enabling seamless integration with CI/CD pipelines, custom dashboards, and automated forensic workflows.

## 🔐 Authentication

All Integrator API requests must include the `X-Api-Key` header.

```bash
X-Api-Key: {SERVICE_API_KEY}
```

---

## 🚀 Priority Roadmap Endpoints (/api/v1)

### `POST /api/v1/mutate`
**Priority: P0**
Programmatic scenario mutation for variance and robustness testing.

- **Body**:
  - `type` (string): Mutation type (e.g., `typo`, `jumble`, `synonym`).
  - `path` (string): Path to a scenario JSON file.
  - `raw_json` (object, optional): Raw scenario JSON to mutate directly.
- **Support**: Accepts **Raw Content** for cloud-native integration.

### `GET /api/v1/metrics`
**Priority: P0**
Lists all registered evaluation metrics available for dynamic hydration.

### `GET /api/v1/taxonomy`
**Priority: P0**
Returns the failure taxonomy (AEH v1.5) for categorical diagnostics.

### `POST /api/v1/spec-to-eval`
**Priority: P1**
Converts structured Markdown PRDs into validated scenario JSON stubs.

- **Body**:
  - `markdown` (string): Raw Markdown content.
  - `input_path` (string): Path to a Markdown file.
- **Support**: Accepts **Raw Content**.

### `GET /api/v1/doctor`
**Priority: P1**
Environmental health audit. Checks project readiness, plugin loading, and catalog integrity.

### `GET /api/v1/explain/<run_id>`
**Priority: P2**
Forensic Root Cause Analysis (RCA). Returns the primary failure trigger and causal chain.

---

## 🛠️ Troubleshooting: Spec-to-Eval

The `spec-to-eval` service uses a combination of hierarchical section splitting and LLM tasks synthesis. If parsing fails, verify the following Markdown requirements:

### 1. Structure Requirements
- **Title**: Must start with an H1 header (`# PRD: ...`).
- **Sections**: Use H2 headers (`## Tasks`) to demarcate logic blocks.

### 2. Common Parsing Pitfalls
- **Missing Tasks**: If no `## Tasks` or `## Test Cases` section is found, the engine will attempt LLM synthesis. Ensure this section contains either a bulleted list or H3 sub-headers.
- **Malformed Metadata**: Ensure `**Industry:**` and `**Use Case:**` segments are correctly labeled in the Overview.
- **Topology Failures**: Agent topology requires the pattern `**AgentName:** writes to [X], reads from [Y]`.

### 3. LLM Fallback Triggers
If the heuristic parser cannot identify structured nodes, it triggers **Gemini-powered Synthesis**. Ensure `GOOGLE_API_KEY` is configured in your environment for high-fidelity fallback.

---

## 📂 Core Management APIs

### `GET /api/scenarios`
Faceted search across the global scenario catalog.

### `GET /api/info`
Consolidated system health, engine versioning, and telemetry.

### `GET /v1/verify/<run_id>` (Public)
Public integrity audit for signed traces.
