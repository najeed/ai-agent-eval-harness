# Writing Tests

## Test File Templates

### Basic Test File Structure

```python
"""
Test module for [module_name].

This module contains unit tests for the [module_name] functionality.
"""

import pytest
from unittest.mock import Mock, patch
from eval_runner import [module_name]


class Test[ClassName]:
    """Test cases for [ClassName]."""
    
    def setup_method(self):
        """Set up test fixtures before each test method."""
        pass
    
    def teardown_method(self):
        """Clean up after each test method."""
        pass
    
    def test_[functionality]_[condition](self):
        """Test [specific behavior] when [condition]."""
        # Arrange
        # Act
        # Assert
        pass


def test_[function_name]_[condition]():
    """Test [function_name] when [condition]."""
    # Arrange
    # Act
    # Assert
    pass
```

### Test File Template for Evaluation Components

```python
"""
Test module for evaluation engine components.

This module contains tests for the evaluation engine, including scenario loading,
metric calculation, and result generation.
"""

import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from eval_runner import engine, loader, metrics, reporter


class TestEvaluationEngine:
    """Test cases for the evaluation engine."""
    
    @pytest.fixture
    def sample_scenario(self):
        """Provide a sample scenario for testing."""
        return {
            "scenario_id": "test_001",
            "title": "Test Scenario",
            "tasks": [
                {
                    "task_id": "task_1",
                    "description": "Test task",
                    "required_tools": ["search"],
                    "success_criteria": [
                        {
                            "metric": "tool_call_correctness",
                            "threshold": 1.0
                        }
                    ]
                }
            ]
        }
    
    def test_run_evaluation_with_valid_scenario(self, sample_scenario):
        """Test evaluation engine with a valid scenario."""
        # Arrange
        expected_tasks = 1
        
        # Act
        results = engine.run_evaluation(sample_scenario)
        
        # Assert
        assert len(results) == expected_tasks
        assert results[0]["task_id"] == "task_1"
        assert "metrics" in results[0]


class TestScenarioLoading:
    """Test cases for scenario loading functionality."""
    
    def test_load_valid_scenario(self, tmp_path):
        """Test loading a valid scenario file."""
        # Arrange
        scenario_data = {"scenario_id": "test", "title": "Test"}
        scenario_file = tmp_path / "test_scenario.json"
        scenario_file.write_text(json.dumps(scenario_data))
        
        # Act
        result = loader.load_scenario(scenario_file)
        
        # Assert
        assert result["scenario_id"] == "test"
        assert result["title"] == "Test"
    
    def test_load_nonexistent_scenario(self):
        """Test loading a scenario file that doesn't exist."""
        # Arrange
        nonexistent_file = Path("nonexistent.json")
        
        # Act & Assert
        with pytest.raises(FileNotFoundError):
            loader.load_scenario(nonexistent_file)


class TestMetrics:
    """Test cases for metric calculations."""
    
    def test_tool_call_correctness_perfect_match(self):
        """Test tool call correctness with perfect match."""
        # Arrange
        expected = ["search", "lookup"]
        actual = ["search", "lookup"]
        
        # Act
        result = metrics.calculate_tool_call_correctness(expected, actual)
        
        # Assert
        assert result == 1.0
    
    def test_tool_call_correctness_no_match(self):
        """Test tool call correctness with no match."""
        # Arrange
        expected = ["search"]
        actual = ["lookup"]
        
        # Act
        result = metrics.calculate_tool_call_correctness(expected, actual)
        
        # Assert
        assert result == 0.0
```

## Naming Conventions

### Test Function Names

Use descriptive names that follow the pattern: `test_[functionality]_[condition]`

```python
# Good examples
def test_load_scenario_with_valid_file():
def test_calculate_metrics_with_empty_input():
def test_evaluation_engine_with_invalid_scenario():
def test_report_generation_with_multiple_tasks():

# Bad examples
def test_loader():
def test_metrics():
def test_engine():
```

### Test Class Names

Use descriptive class names that indicate what is being tested:

```python
# Good examples
class TestEvaluationEngine:
class TestScenarioLoading:
class TestMetricCalculation:
class TestReportGeneration:

# Bad examples
class TestEngine:
class TestLoader:
class TestMetrics:
```

### Fixture Names

Use descriptive fixture names that indicate what they provide:

```python
# Good examples
@pytest.fixture
def sample_scenario():
@pytest.fixture
def mock_agent_api():
@pytest.fixture
def valid_scenario_file():
@pytest.fixture
def test_metrics_data():

# Bad examples
@pytest.fixture
def scenario():
@pytest.fixture
def api():
@pytest.fixture
def file():
```

## Mock Usage Patterns

### Mocking External APIs

```python
@patch('eval_runner.engine.requests.post')
def test_agent_api_integration(mock_post):
    """Test integration with agent API."""
    # Arrange
    mock_response = Mock()
    mock_response.json.return_value = {"tool_name": "search"}
    mock_response.raise_for_status.return_value = None
    mock_post.return_value = mock_response
    
    scenario = {"tasks": [{"description": "test"}]}
    
    # Act
    results = engine.run_evaluation(scenario)
    
    # Assert
    mock_post.assert_called_once()
    assert len(results) > 0
```

### Mocking File Operations

```python
@patch('builtins.open', mock_open(read_data='{"test": "data"}'))
def test_file_loading_with_mock():
    """Test file loading with mocked file operations."""
    # Arrange
    file_path = Path("test.json")
    
    # Act
    result = loader.load_scenario(file_path)
    
    # Assert
    assert result["test"] == "data"
```

### Mocking Environment Variables

```python
@patch.dict(os.environ, {'AGENT_API_URL': 'http://test.com'})
def test_environment_variable_usage():
    """Test that environment variables are used correctly."""
    # Arrange
    # Act
    # Assert
    pass
```

## Agent Testing Best Practices

### Testing Agent Integration

```python
class TestAgentIntegration:
    """Test cases for agent integration."""
    
    @pytest.fixture
    def mock_agent_response(self):
        """Provide a mock agent response."""
        return {
            "tool_name": "search",
            "result": "test result",
            "confidence": 0.95
        }
    
    def test_agent_correct_tool_usage(self, mock_agent_response):
        """Test that agent uses the correct tools."""
        # Arrange
        expected_tools = ["search"]
        
        # Act
        actual_tools = [mock_agent_response["tool_name"]]
        
        # Assert
        assert actual_tools == expected_tools
    
    def test_agent_response_validation(self, mock_agent_response):
        """Test that agent responses are properly validated."""
        # Arrange
        required_fields = ["tool_name", "result"]
        
        # Act & Assert
        for field in required_fields:
            assert field in mock_agent_response
```

### Testing Error Conditions

```python
class TestErrorHandling:
    """Test cases for error handling."""
    
    def test_agent_api_timeout(self):
        """Test handling of agent API timeout."""
        # Arrange
        with patch('eval_runner.engine.requests.post') as mock_post:
            mock_post.side_effect = requests.exceptions.Timeout()
            
            scenario = {"tasks": [{"description": "test"}]}
            
            # Act
            results = engine.run_evaluation(scenario)
            
            # Assert
            assert len(results) > 0
            # Verify that timeout was handled gracefully
    
    def test_invalid_json_response(self):
        """Test handling of invalid JSON response from agent."""
        # Arrange
        with patch('eval_runner.engine.requests.post') as mock_post:
            mock_response = Mock()
            mock_response.json.side_effect = json.JSONDecodeError("", "", 0)
            mock_post.return_value = mock_response
            
            scenario = {"tasks": [{"description": "test"}]}
            
            # Act
            results = engine.run_evaluation(scenario)
            
            # Assert
            assert len(results) > 0
            # Verify that JSON decode error was handled gracefully
```

## Scenario Validation Testing

### Testing Schema Validation

```python
class TestScenarioValidation:
    """Test cases for scenario validation."""
    
    @pytest.fixture
    def valid_scenario(self):
        """Provide a valid scenario for testing."""
        return {
            "scenario_id": "test_001",
            "title": "Test Scenario",
            "industry": "test",
            "description": "A test scenario",
            "tasks": [
                {
                    "task_id": "task_1",
                    "description": "Test task",
                    "required_tools": ["search"],
                    "success_criteria": [
                        {
                            "metric": "tool_call_correctness",
                            "threshold": 1.0
                        }
                    ]
                }
            ]
        }
    
    def test_valid_scenario_passes_validation(self, valid_scenario):
        """Test that valid scenarios pass validation."""
        # Arrange
        # Act
        # Assert
        # This would typically use the schema validation function
        pass
    
    def test_invalid_scenario_fails_validation(self):
        """Test that invalid scenarios fail validation."""
        # Arrange
        invalid_scenario = {"invalid": "data"}
        
        # Act & Assert
        # This would typically use the schema validation function
        # and expect it to raise a validation error
        pass
```

## Performance Testing Guidelines

### Basic Performance Tests

```python
class TestPerformance:
    """Test cases for performance benchmarks."""
    
    def test_evaluation_engine_performance(self, benchmark):
        """Test evaluation engine performance."""
        # Arrange
        scenario = {
            "scenario_id": "perf_test",
            "tasks": [{"task_id": "task_1", "description": "test"}]
        }
        
        # Act
        def run_evaluation():
            return engine.run_evaluation(scenario)
        
        result = benchmark(run_evaluation)
        
        # Assert
        assert result.stats.mean < 1.0  # Should complete in under 1 second
    
    def test_scenario_loading_performance(self, benchmark, tmp_path):
        """Test scenario loading performance."""
        # Arrange
        scenario_data = {"scenario_id": "test", "title": "Test"}
        scenario_file = tmp_path / "perf_test.json"
        scenario_file.write_text(json.dumps(scenario_data))
        
        # Act
        def load_scenario():
            return loader.load_scenario(scenario_file)
        
        result = benchmark(load_scenario)
        
        # Assert
        assert result.stats.mean < 0.1  # Should load in under 100ms
```

## Test Data Management

### Using Fixtures for Test Data

```python
@pytest.fixture(scope="module")
def sample_scenarios():
    """Provide a collection of sample scenarios for testing."""
    return [
        {
            "scenario_id": "scenario_1",
            "title": "Scenario 1",
            "tasks": [{"task_id": "task_1", "description": "Task 1"}]
        },
        {
            "scenario_id": "scenario_2",
            "title": "Scenario 2",
            "tasks": [{"task_id": "task_2", "description": "Task 2"}]
        }
    ]

@pytest.fixture
def mock_agent_responses():
    """Provide mock agent responses for testing."""
    return {
        "search": {"tool_name": "search", "result": "search result"},
        "lookup": {"tool_name": "lookup", "result": "lookup result"}
    }
```

### Test Data Factories

```python
def create_test_scenario(scenario_id="test_001", num_tasks=1):
    """Create a test scenario with specified parameters."""
    return {
        "scenario_id": scenario_id,
        "title": f"Test Scenario {scenario_id}",
        "tasks": [
            {
                "task_id": f"task_{i}",
                "description": f"Test task {i}",
                "required_tools": ["search"],
                "success_criteria": [
                    {
                        "metric": "tool_call_correctness",
                        "threshold": 1.0
                    }
                ]
            }
            for i in range(num_tasks)
        ]
    }

def create_test_agent_response(tool_name="search", result="test result"):
    """Create a test agent response."""
    return {
        "tool_name": tool_name,
        "result": result,
        "confidence": 0.95
    }
```

## Best Practices Summary

### Writing Effective Tests

1. **Test One Thing**: Each test should verify one specific behavior
2. **Use Descriptive Names**: Test names should clearly describe what is being tested
3. **Follow AAA Pattern**: Arrange, Act, Assert structure
4. **Use Fixtures**: Reuse test data and setup code
5. **Mock External Dependencies**: Avoid external service calls in unit tests
6. **Test Edge Cases**: Include tests for error conditions and boundary values
7. **Keep Tests Fast**: Unit tests should run quickly
8. **Maintain Test Independence**: Tests should not depend on each other

### Common Anti-patterns to Avoid

1. **Testing Implementation Details**: Focus on behavior, not implementation
2. **Over-mocking**: Only mock what's necessary
3. **Testing Multiple Behaviors**: Each test should verify one thing
4. **Hard-coded Test Data**: Use factories and fixtures for test data
5. **Slow Tests**: Avoid unnecessary setup or external calls
6. **Fragile Tests**: Don't make tests dependent on specific implementation details 