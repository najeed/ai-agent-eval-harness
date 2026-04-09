---
title: Interactive Visual Suite
description: Unified React dashboard for trajectory analysis, live DNA debugging, and visual scenario construction.
---

The **Interactive Visual Suite** (launched via `multiagent-eval console`) is a high-density forensic interface for managing the entire agent evaluation lifecycle.

## 🔍 Visual Debugger & Trajectory Maps

The core of the suite is the **Visual Debugger**, which provides a frame-by-frame reconstruction of agent reasoning.
- **Node-Based Trajectory**: Visualize agent turns as an interactive React Flow graph.
- **State Inspection**: Real-time diffing of the [Virtual File System (VFS)](/ai-agent-eval-harness/extender/triage-engine/) at any point in the timeline.
- **Live DNA Streaming**: When using the `RemoteBridgePlugin`, evaluations stream events directly to the console in real-time.

---

## 🎯 Forensic Root Cause Isolation

One of the suite's most powerful features is the **"Isolate Root Cause"** engine. 
- It scans the [Failure Taxonomy](/ai-agent-eval-harness/evaluator/taxonomy/) markers and behavioral telemetry.
- One-click focus scrolls the trajectory to **"Patient Zero"**—the exact step where the first logic, security, or state divergence occurred.

---

## 🏗️ Visual AES Builder

For rapid scenario design, the suite includes a drag-and-drop editor for the **Agent Evaluation Specification (AES)**.
- **Node Library**: Add task nodes, tool constraints, and success criteria via a GUI.
- **Instant Validation**: The editor lints the scenario against the latest industrial schema in real-time.
- **Persistence**: Scenarios saved in the builder are persisted directly to the authoritative [`industries/`](/ai-agent-eval-harness/evaluator/industries/) directory.

---

## 📊 Industrial Performance Dashboards

The suite aggregates batch results into interactive leaderboards:
- **Head-to-Head Stats**: Comparative pass rates, latency, and cost per agent.
- **Robustness Radar**: Visualization of success consistency across diverse sectors.
- **Drift Analytics**: Identification of behavioral shifts between model versions or prompts.

---

## 🔌 Extensibility

Developers can extend the Visual Suite using the [Plugin System](/ai-agent-eval-harness/builder/developer-guide/).
- **Custom Views**: Inject React components into the dashboard using JIT-Babel hydration.
- **Custom Routes**: Use the `on_register_console_routes` hook to add proprietary monitoring or administration endpoints.
