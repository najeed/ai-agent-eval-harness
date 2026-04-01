# MultiAgentEval Diagnostics & Log Locations (v1.2.3)

This document provides an authoritative guide for locating system logs, execution traces, and evaluation reports.

## Execution Trace Logs (.jsonl)
Detailed step-by-step agent interactions are recorded as `.jsonl` files.
- **Location**: `runs/` (Project Root)
- **Format**: Each line is a JSON event containing timestamps, event types (prompt, agent_response, tool_call), and status.
- **Verification**: Use `multiagent-eval verify --path <trace_file>` to check integrity.

## Visual Trajectories (HTML/JSON Reports)
Formatted reports and visual trace exports.
- **Location**: `reports/trajectories/`
- **Purpose**: High-fidelity visualization of agent reasoning chains and failure points.

## Scenario Index Cache
The system maintains a fast-lookup index of all discoverable scenarios.
- **Location**: `scenarios/index.json`
- **Sync**: Automatically managed, but can be forced via the Dashboard or `multiagent-eval catalog-refresh`.

## System Metadata
Configuration and environment status can be viewed via the Visual Suite Dashboard under the **Industrial System Paths** section.

---
*For industrial support, contact the AgentEval Enterprise team.*
