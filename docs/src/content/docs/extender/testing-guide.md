---
title: Test Architecture & Best Practices
description: Guide for testing the AgentV harness and its extensions.
---

AgentV uses a comprehensive testing strategy to ensure the reliability and correctness of the evaluation core. This guide is for developers extending the harness or contributing to the core.

## 🏗️ Test Directory Structure

```text
tests/
├── test_cli.py                 # Unified CLI integration tests
├── test_engine.py              # Core evaluation engine tests
├── test_metrics.py              # Scoring and Judge provider tests
├── test_loader.py              # AES scenario loading tests
├── test_core_infrastructure.py # Plugin and architecture tests
├── test_tool_sandbox.py        # Sandbox and policy enforcement
└── test_trace_recorder.py      # Telemetry and forensic logging
```

---

## 🧪 Test Categories

### 1. Unit Tests
- **Focus**: Isolation of individual components (e.g., metric calculations).
- **Execution**: Should be fast (< 1s per test).

### 2. Integration Tests
- **Focus**: Multi-component workflows (e.g., full evaluation loop).
- **Dependencies**: May require mock HTTP services or local agent instances.

### 3. Compliance Tests (`test_doctor.py`)
- **Focus**: Environment verification and AES schema validity.
- **Usage**: Run `agentv doctor` to trigger these diagnostics.

---

## 🛠️ Writing Tests: Patterns & Practices

### Arrange-Act-Assert (AAA)
Always structure your tests with clear setup, execution, and verification phases.

```python
def test_metric_calculation():
    # Arrange
    metric = AccuracyMetric(threshold=0.8)
    data = {"result": "pass"}

    # Act
    score = metric.calculate(data)

    # Assert
    assert score >= 0.8
```

### Mocking Guidelines
- Use **`pytest` fixtures** for shared resources (scenarios, sample agents).
- Mock external APIs (Anthropic, OpenAI, etc.) unless performing E2E provider testing.
- Use the **`IsolatedEnvironment`** context manager for tests that modify the file system or environment variables.

---

## 🚀 Coverage & CI/CD

All contributions must maintain the following coverage thresholds:
- **Core Engine**: 80%+
- **Schema Validation**: 100%
- **Error Handlers**: 100% (Every `except` block must be tested).

### Running Tests
```bash
# Run all tests
pytest tests/

# Run with coverage report
pytest --cov=eval_runner tests/

# Run a specific module
pytest tests/test_engine.py
```

### Security Hardening Tests
Tests involving `AEH_STRICT_JAIL` or path traversal payloads must be run in a clean environment to prevent false positives. The `test_tool_sandbox.py` suite includes specific adversarial payloads for this purpose.
