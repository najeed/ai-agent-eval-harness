# Testing Quick Reference: AgentV Evaluation Harness

## Overview

This document provides a quick reference for testing the AgentV. For detailed information, see the comprehensive guides in [`docs-old/guides/testing/`](docs-old/guides/testing/).

## Quick Start

### Install Dependencies
```bash
pip install -r requirements-dev.txt
```

### Run All Tests
```bash
pytest
```

### Run with Coverage
```bash
pytest --cov=eval_runner --cov-report=html
```

## Test Categories

| Category | Command | Description |
|----------|---------|-------------|
| **All Tests** | `pytest` | Run complete test suite (200+) |
| **Unit Tests** | `pytest tests/unit/` | Core unit tests for engine logic |
| **Linter Check** | `ruff check .` | Verify code quality and industrial syntax |
| **Compliance** | `pytest tests/test_telemetry_compliance.py` | AES schema and protocol verification |
| **Coverage Report** | `pytest --cov=eval_runner` | Generate coverage analysis |
| **Performance** | `pytest --benchmark-only` | Run performance benchmarks |

## Test Structure

```
tests/
├── unit/                       # Unit tests for individual modules
├── integration/                # Multi-component and adapter integration tests
├── functional/                 # E20E and CLI functional verification
├── security/                   # Guardrail and forensic audit tests
├── ui/                         # Streamlit and portal frontend tests
├── conftest.py                 # Global fixtures and test configuration
└── test_telemetry_compliance.py # Industrial telemetry verification
```

## Key Testing Areas

### 1. Core Engine & Metrics
- **Files**: `tests/test_engine.py`, `tests/test_metrics.py`
- **Purpose**: Test the multi-turn loop, pass@k, and multi-model judge logic.
- **Coverage**: Evaluator states, consistency scores, and OpenAI/Gemini/Ollama judge providers.

### 2. Infrastructure & Compliance
- **Files**: `tests/test_core_infrastructure.py`, `tests/test_scenario_compliance.py`
- **Purpose**: Verify system integrity and scenario adherence to the AES spec.
- **Coverage**: Plugin gateway, EventEmitter bus, and schema enforcement.

### 3. CLI & Adapters
- **Files**: `tests/test_cli.py`, `tests/test_adapters_extended.py`
- **Purpose**: Test the modular CLI suite and third-party integrations (LangGraph, CrewAI).
- **Coverage**: `run`, `list`, `lint`, and `analyze` commands.

### 3. Integration Testing
- **Purpose**: Test component interactions
- **Coverage**: End-to-end workflows, API integration

### 4. Trust Protocol & Hard Gating
- **Files**: `tests/test_verifier_asymmetric.py`, `tests/test_gate_cli.py`
- **Purpose**: Verify non-repudiation and CI/CD gatekeeping logic.
- **Coverage**: ED25519 key generation, trace signing, and binary integrity enforcement.

### 5. Industrial Hardening (Fintech)
- **File**: `tests/test_fintech_pack.py`
- **Purpose**: Ensure 100% schema compliance for high-risk industrial scenarios.
- **Coverage**: Series 11198-11207 scenario quality and complex recovery logic.

## Coverage Requirements

| Component | Minimum Coverage |
|-----------|------------------|
| Core Modules | 90%+ |
| Utility Functions | 85%+ |
| Schema Validation | 100% |
| Error Handling | 100% |

## Common Commands

### Basic Testing
```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_engine.py

# Run specific test function
pytest tests/test_loader.py::test_load_scenario
```

### Coverage Analysis
```bash
# Generate coverage report
pytest --cov=eval_runner --cov-report=html

# Show missing lines
pytest --cov=eval_runner --cov-report=term-missing

# Fail if coverage is low
pytest --cov=eval_runner --cov-fail-under=80
```

### Performance Testing
```bash
# Install benchmark tool
pip install pytest-benchmark

# Run performance tests
pytest --benchmark-only

# Compare with previous runs
pytest --benchmark-compare
```

## Test Patterns

### Writing New Tests
```python
def test_functionality_condition():
    """Test [functionality] when [condition]."""
    # Arrange
    # Act
    # Assert
    pass
```

### Using Fixtures
```python
@pytest.fixture
def sample_data():
    """Provide test data."""
    return {"test": "data"}

def test_with_fixture(sample_data):
    """Test using fixture data."""
    assert sample_data["test"] == "data"
```

### High-Fidelity Infrastructure (Zero-Mock Pattern)
The project has migrated away from fragile `unittest.mock.patch` for core infrastructure. Use the centralized `adapter_stub` fixture or direct filesystem interaction.

```python
def test_agent_interaction(adapter_stub, tmp_path):
    """Test using high-fidelity stubs instead of MagicMock."""
    # Use real aiohttp server provided by adapter_stub
    # Use real files in tmp_path
    pass
```

## Troubleshooting

### Common Issues

1. **Import Errors**
   ```bash
   # Ensure you're in the project root
   cd /path/to/ai-agent-eval-harness
   pytest
   ```

2. **Missing Dependencies**
   ```bash
   pip install pytest pytest-cov pytest-mock jsonschema
   ```

3. **Schema Validation Failures**
   ```bash
   # Check specific scenario files
   pytest tests/test_scenario_compliance.py -v
   ```

### Debug Mode
```bash
# Run with debug output
pytest --tb=long

# Run with pdb on failures
pytest --pdb

# Show local variables
pytest -l
```

## CI/CD Integration

### GitHub Actions Example
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.11'
    - name: Install dependencies
      run: pip install -r requirements-dev.txt
    - name: Run linter
      run: ruff check .
    - name: Run tests
      run: pytest --cov=eval_runner --cov-report=xml
```

## Documentation Links

For detailed information, see:

- **[Test Architecture Overview](docs-old/guides/testing/overview.md)** - Test organization and principles
- **[Running Tests](docs-old/guides/testing/running-tests.md)** - Detailed test execution guide
- **[Writing Tests](docs-old/guides/testing/writing-tests.md)** - Test development guidelines
- **[Test Patterns](docs-old/guides/testing/test-patterns.md)** - Common testing patterns and strategies

## Best Practices

### Quick Checklist
- [ ] Write descriptive test names
- [ ] Use AAA pattern (Arrange-Act-Assert)
- [ ] Mock external dependencies
- [ ] Test error conditions
- [ ] Keep tests fast and independent
- [ ] Maintain good coverage

### Before Committing
```bash
# Run full test suite
pytest

# Check coverage
pytest --cov=eval_runner --cov-fail-under=80

# Run scenario compliance
pytest tests/test_scenario_compliance.py
```

## Support

For testing-related questions or issues:

1. Check the detailed guides in `docs-old/guides/testing/`
2. Review existing test examples in the `tests/` directory
3. Follow the patterns and conventions established in the codebase
4. Ensure all tests pass before submitting pull requests 
