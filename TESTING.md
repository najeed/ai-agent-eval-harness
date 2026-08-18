# Testing Quick Reference: AgentV Evaluation Harness

## Overview

This document provides an authoritative reference for running and extending the AgentV test suite.

## Quick Start

### Install Dependencies
```bash
pip install -r requirements-dev.txt
```

### Run All Tests
```bash
pytest
```

### Run with Mandatory Coverage Gate (85%)
```bash
pytest --cov=eval_runner --cov-fail-under=85
```

## Test Categories

| Category | Command | Description |
|----------|---------|-------------|
| **All Tests** | `pytest` | Run complete test suite |
| **Unit Core** | `pytest tests/unit/core/` | Core verifier, sandbox, and engine unit tests |
| **Unit Adapters** | `pytest tests/unit/adapters/` | Unit tests for framework adapters |
| **Contract Matrix** | `pytest tests/contracts/` | Framework adapter protocol & retry contracts |
| **Performance SLAs** | `pytest tests/performance/` | Latency SLA and multi-session concurrency benchmarks |
| **Security & Sandbox** | `pytest tests/security/` | Adversarial bypass, jail escape, and audit tests |
| **Property Invariants** | `pytest tests/property/` | Hypothesis property-based invariant testing |
| **Scenario Corpus Compliance** | `pytest tests/functional/test_scenario_compliance.py` | Full 5,040+ scenario file schema validation under `industries/` |
| **Mutation Sentinel (Sampled)** | `python tools/ci/run_mutation_tests.py` | AST mutation testing on PR / feature branches |
| **Mutation Sentinel (Full)** | `python tools/ci/run_mutation_tests.py --full` | 100% full population AST mutation sentinel evaluation (Target: >=90%) |
| **Code Formatting & Linting** | `ruff check .` | Verify code quality and static syntax integrity |

## Active Test Taxonomy Structure

```
tests/
├── unit/
│   ├── core/                       # Core engine, verifier, and sandbox unit tests
│   ├── adapters/                   # Unit tests for framework integration wrappers
│   ├── console/                    # Console API route tests
│   └── handlers/                   # CLI command handler tests
├── contracts/                      # Protocol contracts, schema invariant & retry tests
├── performance/                    # Synchronous interception latency SLAs & load tests
├── property/                       # Hypothesis property-based invariant tests
├── security/                       # Adversarial bypass, jail escape, and audit tests
├── functional/                     # Industry corpus compliance & CLI functional tests
└── conftest.py                     # Global fixtures, event bus resets, & teardowns
```

## Key Testing Domains

### 1. Core Verifier & Ground Truth
- **Files**: `tests/unit/core/test_core_verifier.py`, `tests/unit/core/test_golden_verifier_matrix.py`
- **Purpose**: Test deterministic replay, Ed25519 key generation, forensic signing, and WSM scoring safety floors.

### 2. Scenario Corpus Compliance
- **Files**: `tests/functional/test_scenario_compliance.py`
- **Purpose**: Systematically validate 100% of scenario JSON files under `industries/` against AES v1.4 schema specs with loud failure reporting.

### 3. Interception Engine & Security
- **Files**: `tests/security/test_sandbox_adversarial_bypass.py`, `tests/security/test_path_jail_enforcement.py`
- **Purpose**: Adversarial testing of `eval_runner/tool_sandbox.py` against path traversal, prompt injection, TOCTOU state races, and deep payload nesting.

### 4. Adapter Contracts & Infrastructure
- **Files**: `tests/contracts/test_adapter_contracts.py`
- **Purpose**: Test `SessionManager` connection pooling, exponential backoff retries, and `AESCallbackHandler` telemetry.

### 5. Performance SLAs & Concurrency Scaling
- **Files**: `tests/performance/test_interception_benchmarks.py`
- **Purpose**: Benchmark synchronous interception latency SLAs (<5ms) and 100+ concurrent evaluation session stability.

### 6. AST Mutation Testing Sentinel
- **Files**: `tools/ci/run_mutation_tests.py`
- **Purpose**: Real AST-based surgical mutation engine testing the verifier (`eval_runner/verifier.py`), tool sandbox (`eval_runner/tool_sandbox.py`), and core utilities (`eval_runner/utils/base.py`). Enforces a 90%+ kill rate gate (100% achieved) with `.mutation_testing.lock` mutex protection.

## Common Commands

### Basic Execution
```bash
# Run full test suite
pytest

# Run with verbose output
pytest -v

# Run specific test domain
pytest tests/unit/core/

# Run specific test module
pytest tests/unit/core/test_golden_verifier_matrix.py
```

### Coverage Analysis
```bash
# Generate HTML coverage report
pytest --cov=eval_runner --cov-report=html

# Terminal coverage with missing lines
pytest --cov=eval_runner --cov-report=term-missing

# Enforce mandatory 85% coverage threshold
pytest --cov=eval_runner --cov-fail-under=85
```

### Performance & Benchmark Runs
```bash
# Run latency and concurrency benchmarks
pytest tests/performance/ --benchmark-only
```

## Best Practices & Pre-Commit Check

Before submitting changes:
```bash
# 1. Format and lint code
ruff check --fix .
ruff format .

# 2. Run full test suite with coverage gate
pytest --cov=eval_runner --cov-fail-under=85

# 3. Verify scenario corpus compliance
pytest tests/functional/test_scenario_compliance.py
```
