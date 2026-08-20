---
title: Test Architecture & Best Practices
description: Guide for testing the AgentV harness and its extensions.
---

AgentV uses a comprehensive testing strategy to ensure the reliability and correctness of the evaluation core. This guide is for developers extending the harness, writing new adapters/plugins, or contributing to the core.

---

## 🏗️ Test Directory Structure

The repository organizes tests strictly by scope and target module to avoid sprawling:

```text
tests/
├── conftest.py                 # Global test configuration and cleanup hooks
├── contracts/                  # Public contract stability and SemVer invariants
├── golden/                     # Immutable regression verification corpus
├── unit/                       # Component-level isolated tests
│   ├── core/                   # Sandbox, loader, and engine unit tests
│   └── console/                # API and system route verification
├── integration/                # Multi-component evaluation loop workflows
├── functional/                 # Specific capability and boundary tests
├── security/                   # Jailbreaks, path traversals, and PBAC policies
├── adapters/                   # LLM/framework adapter verification
├── property/                   # Hypothesis property-based fuzzing and invariant testing
└── contracts/                  # Public contract invariants and wiring tests
```

---

## 🧪 Test Categories

### 1. Contract Tests (`tests/contracts/`)
*   **Focus**: Public contract invariants that must not break without a SemVer MAJOR version bump.
*   **Coverage**:
    *   `test_aes_schema_contract.py`: AES v1.4 scenario schema and required metadata fields.
    *   `test_config_hash_contract.py`: Deterministic SHA3-256 `config_hash` computation and precedence hierarchy.
    *   `test_execution_lifecycle_contract.py`: `ExecutionBackend` 4-method lifecycle (`submit`, `status`, `cancel`, `resume`).
    *   `test_plugin_discovery_contract.py`: `BaseEvalPlugin` 7 lifecycle hooks and `agentv_runtime` namespace stability.
    *   `test_verification_contract.py`: VC v3.0.0 schema, NIST 7-dimension WSM weights, and safety floor enforcement.
*   **Command**: `pytest tests/contracts/ -v`

### 2. Golden Verification Corpus (`tests/golden/`)
*   **Focus**: Immutable regression test suites validating closed defects and zero-regression behavioral baselines.
*   **Command**: `pytest tests/golden/ -v`

### 3. Unit Tests (`tests/unit/`)
*   **Focus**: Isolation of individual components (e.g., metric calculations, signal normalization, taxonomy classification).
*   **Speed**: Fast execution (< 100ms per test).
*   **Isolation**: Do not perform external network calls. Use mocks/fixtures.

### 4. Integration Tests (`tests/integration/`)
*   **Focus**: Multi-component workflows (e.g., full evaluation loops, dynamic provider discovery, database pipelines).
*   **Dependencies**: Rely on mocked HTTP services, temporary files, and local shim environments.

### 5. AST Mutation Testing Sentinel (`tools/ci/run_mutation_tests.py`)
*   **Focus**: Verifies test suite efficacy by mutating abstract syntax trees in core verification modules (`verifier.py`, `tool_sandbox.py`, `base.py`).
*   **Threshold**: Enforces a minimum **90% mutation kill rate** (100% achieved).
*   **Command**: `python tools/ci/run_mutation_tests.py`

### 6. Compliance Tests (`test_doctor.py`)
*   **Focus**: Active environment verification, virtual file system verification, and AES schema validity.
*   **Usage**: Triggered by running `agentv doctor`.

---

## 🛠️ Writing Tests: Patterns & Practices

### Arrange-Act-Assert (AAA)
Always structure your tests with clear setup, execution, and verification phases:

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
*   Use **`pytest` fixtures** for shared resources (scenarios, sample agents, configuration objects).
*   Mock external APIs (Anthropic, OpenAI, Grok, etc.) unless performing E2E provider testing.
*   Mock specialized third-party dependencies dynamically to test fallback paths.

---

## 🚀 Advanced Architectural Testing Patterns

To maintain robust and deterministic execution across different operating systems and environments, adhere to these advanced patterns:

### 1. Loop Hygiene (Python 3.12+)
Integration tests that run async event loops can pollute the global loop state. Always explicitly close and reset the `asyncio` event loop policy between test executions to prevent stale forensic collector references and memory leaks:

```python
import asyncio
import pytest


@pytest.fixture(autouse=True)
def clean_event_loop():
    yield
    # Force reset loop policy
    asyncio.set_event_loop_policy(None)
```

### 2. Registry Reset Hardening
Global registries (such as `AgentAdapterRegistry`) must be fully cleared between test contexts to prevent side-effects during monkeypatching:

```python
def test_custom_adapter_discovery(monkeypatch):
    # Ensure clean start state
    AgentAdapterRegistry.reset()
    assert not AgentAdapterRegistry._plugins_discovered
    
    # Act / patch registry state...
```

### 3. Windows Forensic Isolation
In Windows environments, pending file handles from loggers, databases, or subprocesses can prevent the deletion of temporary test directories. Force a garbage collection cycle during teardown to physically purge stale file handles:

```python
# conftest.py
import gc
import shutil


@pytest.fixture
def temp_run_dir(tmp_path):
    yield tmp_path
    # Teardown: force collection of file handles before directory deletion
    gc.collect()
    shutil.rmtree(tmp_path, ignore_errors=True)
```

### 4. Deterministic Seeding Protocol
For multi-attempt or stochastic evaluations, implement a deterministic seeding formula:
$$\text{Final Seed} = \text{Base Seed} + \text{Run Index}$$
This guarantees that while each run index is unique, the entire evaluation suite remains 100% reproducible.

### 5. Metric Context Hydration
When implementing seed-aware metrics, propagate the current run's seed via `session_metadata` so that the `LLM Judge` or stochastic validation components can access it.

---

## 🔒 Security & Sandbox Isolation

### Terminology Synchronization
Avoid using Docker-specific terms unless referencing a Docker-specific backend. Standardize on **"Sandbox"**, **"Jails"**, or **"VFS"** (Virtual File System) to describe tool execution bounds. This keeps documentation aligned with pluggable backend implementations.

### PQC Client Import Mocking
When testing fallback paths for missing third-party dependencies (like `cyclecore-pq` or `rapidfuzz`), standard module deletion via `sys.modules.pop` is insufficient if the dependency was globally imported. Mock `builtins.__import__` to simulate import errors cleanly:

```python
import builtins
from unittest.mock import patch


def test_fallback_when_dependency_missing():
    orig_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if "cyclecore-pq" in name:
            raise ImportError("Dependency not installed")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        # Trigger code path relying on cyclecore-pq fallback
        ...
```

---

## 🧹 Linter & Testing Constraints (Ruff/B017/F401)

To pass automated quality gates, all test files must strictly comply with the following:

### 1. Explicit Exception Scoping (Ruff B017)
Never assert generic exceptions. Always target specific exceptions to prevent swallowing unexpected bugs:

```python
# ❌ INCOMPLIANT
with pytest.raises(Exception):
    parse_pem_key(corrupt_data)

#  COMPLIANT
with pytest.raises(ValueError):
    parse_pem_key(corrupt_data)
```

### 2. Unused Import Pruning (Ruff F401)
When refactoring or deleting tests, prune any associated imports (e.g. `MagicMock`, `patch`, `mock_open`) that are no longer used in the rest of the file.

### 3. Unique Test Registry Namespaces
Pytest registry warnings can arise if test names overlap across different modules. Ensure all test function names are distinct by including module-specific or behavioral suffixes (e.g., `test_correlator_file_discovery_load_exception` vs `test_finance_edgar_fetch_failure`).
