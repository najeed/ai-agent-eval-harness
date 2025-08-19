# Testing Quick Reference

## Overview

This document provides a quick reference for testing the AI Agent Evaluation Harness. For detailed information, see the comprehensive guides in [`docs/guides/testing/`](docs/guides/testing/).

## Quick Start

### Install Dependencies
```bash
pip install pytest pytest-cov pytest-mock jsonschema
```

### Run All Tests
```bash
pytest
```

### Run with Coverage
```bash
pytest --cov=eval-runner --cov-report=html
```

## Test Categories

| Category | Command | Description |
|----------|---------|-------------|
| **All Tests** | `pytest` | Run complete test suite |
| **Unit Tests** | `pytest tests/test_eval_runner.py` | Core functionality tests |
| **Schema Validation** | `pytest tests/test_schema_validation.py` | Validate all scenario files |
| **Coverage Report** | `pytest --cov=eval-runner` | Generate coverage analysis |
| **Performance** | `pytest --benchmark-only` | Run performance benchmarks |

## Test Structure

```
tests/
├── __init__.py                 # Python package marker
├── test_eval_runner.py        # Core evaluation engine tests
└── test_schema_validation.py  # Schema validation tests
```

## Key Testing Areas

### 1. Evaluation Engine
- **File**: `tests/test_eval_runner.py`
- **Purpose**: Test core evaluation functionality
- **Coverage**: Scenario loading, metric calculation, result generation

### 2. Schema Validation
- **File**: `tests/test_schema_validation.py`
- **Purpose**: Validate all scenario JSON files
- **Coverage**: All industries and scenarios

### 3. Integration Testing
- **Purpose**: Test component interactions
- **Coverage**: End-to-end workflows, API integration

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
pytest tests/test_eval_runner.py

# Run specific test function
pytest tests/test_eval_runner.py::test_scenario_loading
```

### Coverage Analysis
```bash
# Generate coverage report
pytest --cov=eval-runner --cov-report=html

# Show missing lines
pytest --cov=eval-runner --cov-report=term-missing

# Fail if coverage is low
pytest --cov=eval-runner --cov-fail-under=80
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

### Mocking External Dependencies
```python
@patch('eval_runner.engine.requests.post')
def test_api_integration(mock_post):
    """Test API integration with mock."""
    mock_post.return_value = Mock(json=lambda: {"result": "success"})
    # Test implementation
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
   pytest tests/test_schema_validation.py -v
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
    - uses: actions/checkout@v2
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: 3.9
    - name: Install dependencies
      run: pip install pytest pytest-cov pytest-mock jsonschema
    - name: Run tests
      run: pytest --cov=eval-runner --cov-report=xml
```

## Documentation Links

For detailed information, see:

- **[Test Architecture Overview](docs/guides/testing/overview.md)** - Test organization and principles
- **[Running Tests](docs/guides/testing/running-tests.md)** - Detailed test execution guide
- **[Writing Tests](docs/guides/testing/writing-tests.md)** - Test development guidelines
- **[Test Patterns](docs/guides/testing/test-patterns.md)** - Common testing patterns and strategies

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
pytest --cov=eval-runner --cov-fail-under=80

# Run schema validation
pytest tests/test_schema_validation.py
```

## Support

For testing-related questions or issues:

1. Check the detailed guides in `docs/guides/testing/`
2. Review existing test examples in the `tests/` directory
3. Follow the patterns and conventions established in the codebase
4. Ensure all tests pass before submitting pull requests 