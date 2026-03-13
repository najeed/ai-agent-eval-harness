# Test Patterns

## Common Testing Patterns for Evaluation Frameworks

This document outlines common testing patterns and strategies specifically designed for evaluation frameworks like the AI Agent Evaluation Harness.

## Evaluation Engine Testing Patterns

### Scenario-Based Testing

```python
class TestScenarioEvaluation:
    """Test patterns for scenario-based evaluation."""
    
    @pytest.fixture
    def simple_scenario(self):
        """A simple scenario for basic testing."""
        return {
            "scenario_id": "simple_test",
            "title": "Simple Test Scenario",
            "tasks": [
                {
                    "task_id": "task_1",
                    "description": "Perform a simple search",
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
    
    def test_scenario_evaluation_happy_path(self, simple_scenario):
        """Test successful scenario evaluation."""
        # Arrange
        expected_metrics = ["tool_call_correctness"]
        
        # Act
        results = engine.run_evaluation(simple_scenario)
        
        # Assert
        assert len(results) == 1
        assert results[0]["task_id"] == "task_1"
        assert len(results[0]["metrics"]) == 1
        assert results[0]["metrics"][0]["metric"] in expected_metrics
    
    def test_scenario_evaluation_with_multiple_tasks(self):
        """Test scenario with multiple tasks."""
        # Arrange
        scenario = {
            "scenario_id": "multi_task_test",
            "tasks": [
                {"task_id": "task_1", "description": "Task 1", "required_tools": ["search"]},
                {"task_id": "task_2", "description": "Task 2", "required_tools": ["lookup"]}
            ]
        }
        
        # Act
        results = engine.run_evaluation(scenario)
        
        # Assert
        assert len(results) == 2
        assert results[0]["task_id"] == "task_1"
        assert results[1]["task_id"] == "task_2"
```

### Metric Calculation Testing

```python
class TestMetricCalculation:
    """Test patterns for metric calculation."""
    
    def test_tool_call_correctness_various_scenarios(self):
        """Test tool call correctness with various scenarios."""
        test_cases = [
            (["search"], ["search"], 1.0, "Perfect match"),
            (["search"], ["lookup"], 0.0, "No match"),
            (["search", "lookup"], ["lookup", "search"], 1.0, "Order doesn't matter"),
            ([], [], 1.0, "Empty lists match"),
            (["search"], [], 0.0, "Expected tools but none used"),
            ([], ["search"], 0.0, "Unexpected tools used")
        ]
        
        for expected, actual, expected_score, description in test_cases:
            with self.subTest(description):
                result = metrics.calculate_tool_call_correctness(expected, actual)
                assert result == expected_score, f"Failed: {description}"
    
    def test_metric_threshold_evaluation(self):
        """Test metric threshold evaluation logic."""
        # Arrange
        metric_score = 0.8
        thresholds = [0.5, 0.9, 1.0]
        expected_results = [True, False, False]  # Should pass, fail, fail
        
        # Act & Assert
        for threshold, expected in zip(thresholds, expected_results):
            with self.subTest(f"threshold_{threshold}"):
                is_success = metric_score >= threshold
                assert is_success == expected
```

## Error Condition Testing Patterns

### Network and API Error Testing

```python
class TestNetworkErrorHandling:
    """Test patterns for network and API error handling."""
    
    @pytest.mark.parametrize("exception_class", [
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.HTTPError,
        requests.exceptions.RequestException
    ])
    def test_agent_api_error_handling(self, exception_class):
        """Test handling of various API errors."""
        # Arrange
        with patch('eval_runner.engine.requests.post') as mock_post:
            mock_post.side_effect = exception_class("Test error")
            
            scenario = {
                "scenario_id": "error_test",
                "tasks": [{"task_id": "task_1", "description": "Test task"}]
            }
            
            # Act
            results = engine.run_evaluation(scenario)
            
            # Assert
            assert len(results) == 1
            # Verify that the error was handled gracefully
            # and the evaluation continued with default values
    
    def test_agent_api_timeout_specific_handling(self):
        """Test specific timeout error handling."""
        # Arrange
        with patch('eval_runner.engine.requests.post') as mock_post:
            mock_post.side_effect = requests.exceptions.Timeout("Request timed out")
            
            scenario = {
                "scenario_id": "timeout_test",
                "tasks": [{"task_id": "task_1", "description": "Test task"}]
            }
            
            # Act
            results = engine.run_evaluation(scenario)
            
            # Assert
            assert len(results) == 1
            # Verify timeout-specific handling if any
```

### Data Validation Error Testing

```python
class TestDataValidationErrors:
    """Test patterns for data validation error handling."""
    
    def test_invalid_scenario_structure(self):
        """Test handling of invalid scenario structure."""
        # Arrange
        invalid_scenarios = [
            {},  # Empty scenario
            {"scenario_id": "test"},  # Missing required fields
            {"scenario_id": "test", "tasks": "not_a_list"},  # Wrong data type
            {"scenario_id": "test", "tasks": [{"invalid": "task"}]}  # Invalid task
        ]
        
        for scenario in invalid_scenarios:
            with self.subTest(f"scenario_{scenario}"):
                # Act & Assert
                # This would typically test how the system handles invalid scenarios
                # and whether appropriate errors are raised or handled
                pass
    
    def test_malformed_json_handling(self):
        """Test handling of malformed JSON files."""
        # Arrange
        with patch('builtins.open', mock_open(read_data='{"invalid": json}')):
            file_path = Path("malformed.json")
            
            # Act & Assert
            with pytest.raises(json.JSONDecodeError):
                loader.load_scenario(file_path)
```

### Resource Error Testing

```python
class TestResourceErrorHandling:
    """Test patterns for resource-related error handling."""
    
    def test_file_permission_errors(self):
        """Test handling of file permission errors."""
        # Arrange
        with patch('builtins.open') as mock_open:
            mock_open.side_effect = PermissionError("Permission denied")
            file_path = Path("protected.json")
            
            # Act & Assert
            with pytest.raises(PermissionError):
                loader.load_scenario(file_path)
    
    def test_disk_space_errors(self):
        """Test handling of disk space errors."""
        # Arrange
        with patch('builtins.open') as mock_open:
            mock_open.side_effect = OSError("No space left on device")
            file_path = Path("large_file.json")
            
            # Act & Assert
            with pytest.raises(OSError):
                loader.load_scenario(file_path)
```

## Performance Testing Patterns

### Load Testing Patterns

```python
class TestPerformancePatterns:
    """Test patterns for performance testing."""
    
    def test_evaluation_engine_load_performance(self, benchmark):
        """Test evaluation engine under load."""
        # Arrange
        large_scenario = {
            "scenario_id": "load_test",
            "tasks": [
                {
                    "task_id": f"task_{i}",
                    "description": f"Task {i}",
                    "required_tools": ["search"],
                    "success_criteria": [
                        {
                            "metric": "tool_call_correctness",
                            "threshold": 1.0
                        }
                    ]
                }
                for i in range(100)  # 100 tasks
            ]
        }
        
        # Act
        def run_large_evaluation():
            return engine.run_evaluation(large_scenario)
        
        result = benchmark(run_large_evaluation)
        
        # Assert
        assert result.stats.mean < 10.0  # Should complete in under 10 seconds
        assert result.stats.max < 15.0   # Max time should be reasonable
    
    def test_concurrent_evaluation_performance(self):
        """Test concurrent evaluation performance."""
        # Arrange
        scenarios = [
            {
                "scenario_id": f"concurrent_{i}",
                "tasks": [{"task_id": "task_1", "description": "Test"}]
            }
            for i in range(10)
        ]
        
        # Act
        import concurrent.futures
        import time
        
        start_time = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(engine.run_evaluation, scenario) for scenario in scenarios]
            results = [future.result() for future in futures]
        end_time = time.time()
        
        # Assert
        assert len(results) == 10
        assert end_time - start_time < 5.0  # Should complete in under 5 seconds
```

### Memory Usage Testing

```python
class TestMemoryUsage:
    """Test patterns for memory usage testing."""
    
    def test_memory_usage_with_large_scenarios(self):
        """Test memory usage with large scenarios."""
        import psutil
        import os
        
        # Arrange
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        large_scenario = {
            "scenario_id": "memory_test",
            "tasks": [
                {
                    "task_id": f"task_{i}",
                    "description": "x" * 1000,  # Large description
                    "required_tools": ["search"] * 10,  # Many tools
                    "success_criteria": [
                        {
                            "metric": "tool_call_correctness",
                            "threshold": 1.0
                        }
                    ]
                }
                for i in range(1000)  # 1000 tasks
            ]
        }
        
        # Act
        results = engine.run_evaluation(large_scenario)
        final_memory = process.memory_info().rss
        
        # Assert
        memory_increase = final_memory - initial_memory
        assert memory_increase < 100 * 1024 * 1024  # Less than 100MB increase
        assert len(results) == 1000
```

## Integration Testing Patterns

### End-to-End Testing

```python
class TestEndToEndIntegration:
    """Test patterns for end-to-end integration testing."""
    
    @pytest.fixture
    def mock_agent_service(self):
        """Mock agent service for integration testing."""
        with patch('eval_runner.engine.requests.post') as mock_post:
            mock_response = Mock()
            mock_response.json.return_value = {"tool_name": "search"}
            mock_response.raise_for_status.return_value = None
            mock_post.return_value = mock_response
            yield mock_post
    
    def test_full_evaluation_workflow(self, mock_agent_service, tmp_path):
        """Test complete evaluation workflow from file to report."""
        # Arrange
        scenario_data = {
            "scenario_id": "e2e_test",
            "title": "End-to-End Test",
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
        
        scenario_file = tmp_path / "e2e_test.json"
        scenario_file.write_text(json.dumps(scenario_data))
        
        # Act
        # 1. Load scenario
        scenario = loader.load_scenario(scenario_file)
        
        # 2. Run evaluation
        results = engine.run_evaluation(scenario)
        
        # 3. Generate report
        reporter.generate_report(scenario, results)
        
        # Assert
        assert scenario["scenario_id"] == "e2e_test"
        assert len(results) == 1
        assert results[0]["task_id"] == "task_1"
        mock_agent_service.assert_called_once()
```

### Cross-Module Integration Testing

```python
class TestCrossModuleIntegration:
    """Test patterns for cross-module integration."""
    
    def test_metrics_integration_with_engine(self):
        """Test integration between metrics and engine modules."""
        # Arrange
        scenario = {
            "scenario_id": "integration_test",
            "tasks": [
                {
                    "task_id": "task_1",
                    "description": "Test task",
                    "required_tools": ["search", "lookup"],
                    "success_criteria": [
                        {
                            "metric": "tool_call_correctness",
                            "threshold": 1.0
                        }
                    ]
                }
            ]
        }
        
        # Act
        results = engine.run_evaluation(scenario)
        
        # Assert
        assert len(results) == 1
        metrics_result = results[0]["metrics"][0]
        assert metrics_result["metric"] == "tool_call_correctness"
        assert isinstance(metrics_result["score"], float)
        assert isinstance(metrics_result["success"], bool)
    
    def test_loader_engine_reporter_integration(self):
        """Test integration between loader, engine, and reporter."""
        # Arrange
        scenario_data = {
            "scenario_id": "integration_test",
            "title": "Integration Test",
            "tasks": [{"task_id": "task_1", "description": "Test"}]
        }
        
        # Act
        # Test that all modules work together
        results = engine.run_evaluation(scenario_data)
        reporter.generate_report(scenario_data, results)
        
        # Assert
        assert len(results) == 1
        # Verify that reporter can handle engine results
```

## Data-Driven Testing Patterns

### Parameterized Testing

```python
class TestParameterizedPatterns:
    """Test patterns using parameterized testing."""
    
    @pytest.mark.parametrize("scenario_id,expected_tasks", [
        ("test_1", 1),
        ("test_2", 2),
        ("test_3", 3),
    ])
    def test_scenario_task_count(self, scenario_id, expected_tasks):
        """Test scenarios with different task counts."""
        # Arrange
        scenario = {
            "scenario_id": scenario_id,
            "tasks": [
                {
                    "task_id": f"task_{i}",
                    "description": f"Task {i}",
                    "required_tools": ["search"],
                    "success_criteria": [
                        {
                            "metric": "tool_call_correctness",
                            "threshold": 1.0
                        }
                    ]
                }
                for i in range(expected_tasks)
            ]
        }
        
        # Act
        results = engine.run_evaluation(scenario)
        
        # Assert
        assert len(results) == expected_tasks
    
    @pytest.mark.parametrize("metric_name,expected_score", [
        ("tool_call_correctness", 1.0),
        ("information_retrieval_accuracy", 1.0),
        ("communication_clarity", 1.0),
    ])
    def test_different_metrics(self, metric_name, expected_score):
        """Test different metric types."""
        # Arrange
        scenario = {
            "scenario_id": "metric_test",
            "tasks": [
                {
                    "task_id": "task_1",
                    "description": "Test task",
                    "required_tools": ["search"],
                    "success_criteria": [
                        {
                            "metric": metric_name,
                            "threshold": 1.0
                        }
                    ]
                }
            ]
        }
        
        # Act
        results = engine.run_evaluation(scenario)
        
        # Assert
        assert len(results) == 1
        metric_result = results[0]["metrics"][0]
        assert metric_result["metric"] == metric_name
        assert metric_result["score"] == expected_score
```

## Mock and Stub Patterns

### Advanced Mocking Patterns

```python
class TestAdvancedMocking:
    """Test patterns using advanced mocking techniques."""
    
    def test_mock_with_side_effects(self):
        """Test mocking with side effects."""
        # Arrange
        call_count = 0
        
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return Mock(json=lambda: {"tool_name": "search"})
            else:
                raise requests.exceptions.Timeout("Timeout on retry")
        
        with patch('eval_runner.engine.requests.post', side_effect=side_effect):
            scenario = {
                "scenario_id": "mock_test",
                "tasks": [{"task_id": "task_1", "description": "Test"}]
            }
            
            # Act
            results = engine.run_evaluation(scenario)
            
            # Assert
            assert len(results) == 1
            assert call_count == 2  # Should have been called twice
    
    def test_mock_with_context_manager(self):
        """Test mocking using context managers."""
        # Arrange
        scenario = {
            "scenario_id": "context_test",
            "tasks": [{"task_id": "task_1", "description": "Test"}]
        }
        
        # Act & Assert
        with patch('eval_runner.engine.requests.post') as mock_post:
            mock_response = Mock()
            mock_response.json.return_value = {"tool_name": "search"}
            mock_post.return_value = mock_response
            
            results = engine.run_evaluation(scenario)
            
            assert len(results) == 1
            mock_post.assert_called_once()
```

## Best Practices Summary

### Pattern Selection Guidelines

1. **Use Scenario-Based Testing** for evaluation engine tests
2. **Use Parameterized Testing** for testing multiple similar cases
3. **Use Mocking Patterns** for external dependencies
4. **Use Performance Testing** for critical paths
5. **Use Integration Testing** for end-to-end workflows

### Pattern Implementation Tips

1. **Keep Tests Focused**: Each test should verify one specific behavior
2. **Use Descriptive Names**: Test names should clearly describe the pattern being tested
3. **Maintain Test Independence**: Tests should not depend on each other
4. **Use Appropriate Assertions**: Choose assertions that clearly express intent
5. **Document Complex Patterns**: Add comments for complex test patterns

### Common Anti-patterns to Avoid

1. **Over-mocking**: Don't mock everything; only mock external dependencies
2. **Testing Implementation Details**: Focus on behavior, not implementation
3. **Hard-coded Test Data**: Use factories and fixtures for test data
4. **Slow Tests**: Avoid unnecessary setup or external calls
5. **Fragile Tests**: Don't make tests dependent on specific implementation details 