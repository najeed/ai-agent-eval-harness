# Running Tests

## Prerequisites

### Installing Test Dependencies

Before running tests, ensure you have the required dependencies installed:

```bash
# Install pytest and testing dependencies
pip install pytest pytest-cov pytest-mock jsonschema

# For development with additional testing tools
pip install pytest-xdist pytest-benchmark pytest-html
```

### Environment Setup

1. **Clone the repository** and navigate to the project root
2. **Install dependencies** as shown above
3. **Set up test environment variables** (if needed):
   ```bash
   export AGENT_API_URL=http://localhost:5001/execute_task
   ```

## Running the Full Test Suite

### Basic Test Execution

Run all tests in the project:

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with more detailed output
pytest -vv
```

### Test Discovery

Pytest automatically discovers tests based on naming conventions:
- Files named `test_*.py` or `*_test.py`
- Functions named `test_*`
- Classes named `Test*`

## Running Specific Test Categories

### Unit Tests

Run only unit tests (fast execution):

```bash
# Run specific test file
pytest tests/test_eval_runner.py

# Run specific test function
pytest tests/test_eval_runner.py::test_scenario_loading

# Run tests matching a pattern
pytest -k "scenario"
```

### Schema Validation Tests

Run schema validation tests (validates all scenario files):

```bash
# Run schema validation tests
pytest tests/test_schema_validation.py

# Run with detailed output
pytest tests/test_schema_validation.py -v
```

### Integration Tests

Run integration tests (may require external services):

```bash
# Run integration tests (if marked with @pytest.mark.integration)
pytest -m integration

# Run tests that require external services
pytest -m "not slow"
```

## Coverage Reporting

### Basic Coverage

Generate coverage reports:

```bash
# Run tests with coverage
pytest --cov=eval-runner

# Generate HTML coverage report
pytest --cov=eval-runner --cov-report=html

# Generate XML coverage report (for CI/CD)
pytest --cov=eval-runner --cov-report=xml
```

### Coverage Configuration

Create a `.coveragerc` file for custom coverage settings:

```ini
[run]
source = eval-runner
omit = 
    */tests/*
    */__pycache__/*
    setup.py

[report]
exclude_lines =
    pragma: no cover
    def __repr__
    raise AssertionError
    raise NotImplementedError
```

### Coverage Analysis

Analyze coverage results:

```bash
# Show coverage summary
pytest --cov=eval-runner --cov-report=term-missing

# Generate detailed HTML report
pytest --cov=eval-runner --cov-report=html
# Open htmlcov/index.html in your browser
```

## Performance Testing

### Basic Performance Testing

Run performance benchmarks:

```bash
# Install pytest-benchmark
pip install pytest-benchmark

# Run performance tests
pytest --benchmark-only

# Run with performance comparison
pytest --benchmark-compare
```

### Performance Test Examples

```python
# Example performance test
def test_evaluation_performance(benchmark):
    def run_evaluation():
        # Your evaluation code here
        pass
    
    result = benchmark(run_evaluation)
    assert result.stats.mean < 1.0  # Should complete in under 1 second
```

## Test Output and Reporting

### Console Output

Different output formats for different needs:

```bash
# Minimal output
pytest -q

# Verbose output
pytest -v

# Very verbose output
pytest -vv

# Show local variables on failures
pytest -l
```

### HTML Reports

Generate HTML test reports:

```bash
# Install pytest-html
pip install pytest-html

# Generate HTML report
pytest --html=report.html --self-contained-html
```

### JUnit XML Reports

Generate XML reports for CI/CD integration:

```bash
# Generate JUnit XML report
pytest --junitxml=test-results.xml
```

## Continuous Integration

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
      run: |
        pip install pytest pytest-cov pytest-mock jsonschema
    - name: Run tests
      run: |
        pytest --cov=eval-runner --cov-report=xml
    - name: Upload coverage
      uses: codecov/codecov-action@v1
```

### Local CI Simulation

Simulate CI environment locally:

```bash
# Run tests in isolated environment
python -m pytest --strict-markers

# Run with coverage and fail if coverage is low
pytest --cov=eval-runner --cov-fail-under=80
```

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure you're running from the project root
2. **Missing Dependencies**: Install all required packages
3. **Schema Validation Failures**: Check scenario file formats
4. **Slow Tests**: Use `pytest -m "not slow"` to skip slow tests

### Debug Mode

Run tests in debug mode:

```bash
# Run with debug output
pytest --tb=long

# Run with pdb on failures
pytest --pdb

# Run with pdb on all tests
pytest --pdbcls=IPython.terminal.debugger:Pdb
```

### Test Isolation

Ensure tests don't interfere with each other:

```bash
# Run tests in random order
pytest --random-order

# Run tests in parallel (if supported)
pytest -n auto
```

## Best Practices

### Running Tests Efficiently

1. **Use markers** to categorize tests: `@pytest.mark.unit`, `@pytest.mark.integration`
2. **Run specific test categories** during development
3. **Use coverage reports** to identify untested code
4. **Run full suite** before committing changes

### Test Environment

1. **Use virtual environments** to isolate dependencies
2. **Mock external services** to avoid dependencies
3. **Use test databases** for integration tests
4. **Clean up resources** after tests complete 