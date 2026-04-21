# Forensics Specification Masterclass: Artifact Retention & Pattern Gauging

This guide provides an exhaustive inventory of the **AgentV Forensic Specification** (v1.0.0). It details how artifacts are filtered into the session vault based on file extensions and cryptographic patterns.

---

## 🏗️ The Forensic Gauge Philosophy

In industrial AI evaluation, the session vault must be both **Exhaustive** and **Pruned**. You need every significant artifact, but you must exclude noise and sensitive data.
1.  **Selective Retention**: Only files with approved extensions (e.g., `.log`, `.db`) are captured.
2.  **Mandatory Capture**: Specific patterns (e.g., `audit_.*`) ensure critical forensic logs are never missed.
3.  **Risk Pruning**: Identifying and excluding dangerous or irrelevant patterns (e.g., `.cache`, `.pyc`).

---

## Lesson 1: The Policy Structure

Forensic behavior is governed by `policy.json` located in `.aes/config/forensics/`. It conforms to `spec/forensics/forensics.schema.json`.

### 1. Extension Filtering (`extensions`)
The engine performs a suffix-check on every file produced during the run. Only files matching the approved list are vaulted.

### 2. Pattern Engines
- **`mandatory_patterns`**: Regex-based list of files that bypass extension checks and file max size checks. Used for system logs or specific JSON tracers.
- **`exclusion_patterns`**: Regex-based blacklist. If a file matches any pattern here, it is PURGED, even if it has a permitted extension.

### 3. Triage Sizing (`max_artifact_size`)
Prevents vault bloating by setting a byte-limit on individual files.
> **Note**: Files exceeding this limit may be truncated or omitted depending on the engine's `strict_sizing` configuration.

---

## Reference Walkthrough: Fintech Forensic Policy

```json
{
  "forensics": {
    "extensions": [
      ".jsonl", ".log", ".sqlite", ".png", ".pdf"
    ],
    "mandatory_patterns": [
      "audit_.*\\.json",
      "trace_final\\.log"
    ],
    "exclusion_patterns": [
      ".*\\.node$",
      ".*\\.cache$",
      "secrets\\.env"
    ],
    "max_artifact_size": 5242880
  }
}
```
