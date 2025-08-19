"""
Test suite for evaluation result export functionality.

This module contains comprehensive tests for the EvaluationResult class
and its export methods (CSV, JSON, HTML). The tests ensure proper 
functionality of data export in various formats and error handling.

The test suite covers:
- EvaluationResult class instantiation
- CSV export functionality and data integrity
- JSON export functionality and structure validation  
- HTML export functionality with and without charts
- Error handling for invalid data and file paths
- CLI export integration testing

Example:
    To run these tests specifically:
    pytest tests/test_export.py -v
"""

import pytest
import sys
import json
import csv
import tempfile
import os
from pathlib import Path

# Add the eval-runner directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "eval-runner"))

from result import EvaluationResult


@pytest.fixture
def sample_scenario():
    """
    Fixture providing a sample scenario for testing.
    
    Returns:
        dict: A sample scenario dictionary with all required fields
    """
    return {
        "scenario_id": "test-scenario-001",
        "title": "Test Scenario",
        "industry": "testing",
        "description": "A test scenario for export functionality",
        "use_case": "Testing",
        "core_function": "Export Testing"
    }


@pytest.fixture
def sample_task_results():
    """
    Fixture providing sample task results for testing.
    
    Returns:
        list: A list of task result dictionaries with metrics
    """
    return [
        {
            "task_id": "task-1",
            "metrics": [
                {
                    "metric": "tool_call_correctness",
                    "score": 1.0,
                    "threshold": 1.0,
                    "success": True
                },
                {
                    "metric": "information_retrieval_accuracy",
                    "score": 0.8,
                    "threshold": 0.7,
                    "success": True
                }
            ]
        },
        {
            "task_id": "task-2", 
            "metrics": [
                {
                    "metric": "communication_clarity",
                    "score": 0.6,
                    "threshold": 0.8,
                    "success": False
                }
            ]
        }
    ]


@pytest.fixture
def evaluation_result(sample_scenario, sample_task_results):
    """
    Fixture providing an EvaluationResult instance for testing.
    
    Args:
        sample_scenario: Sample scenario fixture
        sample_task_results: Sample task results fixture
        
    Returns:
        EvaluationResult: An instance with sample data
    """
    return EvaluationResult(sample_scenario, sample_task_results)


class TestEvaluationResult:
    """Test cases for EvaluationResult class functionality."""
    
    def test_initialization(self, sample_scenario, sample_task_results):
        """
        Test EvaluationResult initialization.
        
        Verifies that the class is properly initialized with scenario
        and task results data, and that timestamp is set.
        """
        result = EvaluationResult(sample_scenario, sample_task_results)
        
        assert result.scenario == sample_scenario
        assert result.task_results == sample_task_results
        assert result.timestamp is not None
        assert len(result.timestamp) > 0
    
    def test_get_summary_stats(self, evaluation_result):
        """
        Test summary statistics calculation.
        
        Verifies that summary statistics are correctly calculated
        from the task results data.
        """
        summary = evaluation_result.get_summary_stats()
        
        assert summary["total_tasks"] == 2
        assert summary["successful_tasks"] == 1  # Only task-1 has all metrics passing
        assert summary["failed_tasks"] == 1
        assert summary["success_rate"] == 50.0
    
    def test_backward_compatibility(self, evaluation_result):
        """
        Test backward compatibility with list interface.
        
        Verifies that EvaluationResult can be used like the original
        list of task results for backward compatibility.
        """
        # Test iteration
        task_ids = [task["task_id"] for task in evaluation_result]
        assert task_ids == ["task-1", "task-2"]
        
        # Test indexing
        assert evaluation_result[0]["task_id"] == "task-1"
        assert evaluation_result[1]["task_id"] == "task-2"
        
        # Test length
        assert len(evaluation_result) == 2


class TestCSVExport:
    """Test cases for CSV export functionality."""
    
    def test_csv_export_success(self, evaluation_result):
        """
        Test successful CSV export.
        
        Verifies that CSV export creates a valid file with correct
        structure and data content.
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as temp_file:
            temp_path = temp_file.name
        
        try:
            evaluation_result.export_csv(temp_path)
            
            # Verify file exists
            assert os.path.exists(temp_path)
            
            # Verify CSV content
            with open(temp_path, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                rows = list(reader)
                
                # Should have 3 rows (2 metrics for task-1, 1 metric for task-2)
                assert len(rows) == 3
                
                # Verify required columns exist
                required_columns = [
                    'scenario_id', 'scenario_title', 'industry', 
                    'task_id', 'metric_name', 'score', 'threshold', 
                    'success', 'timestamp'
                ]
                for column in required_columns:
                    assert column in rows[0].keys()
                
                # Verify data content
                assert rows[0]['scenario_id'] == 'test-scenario-001'
                assert rows[0]['task_id'] == 'task-1'
                assert rows[0]['metric_name'] == 'tool_call_correctness'
                assert float(rows[0]['score']) == 1.0
                assert rows[0]['success'] == 'True'
                
        finally:
            # Clean up
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_csv_export_empty_data(self):
        """
        Test CSV export with empty data.
        
        Verifies that appropriate error is raised when trying to
        export empty evaluation results.
        """
        empty_result = EvaluationResult({}, [])
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as temp_file:
            temp_path = temp_file.name
        
        try:
            with pytest.raises(ValueError, match="No data to export"):
                empty_result.export_csv(temp_path)
        finally:
            # Clean up
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_csv_directory_creation(self, evaluation_result):
        """
        Test CSV export with non-existent directory.
        
        Verifies that missing directories are created automatically
        when exporting CSV files.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            nested_path = os.path.join(temp_dir, "exports", "csv", "results.csv")
            
            evaluation_result.export_csv(nested_path)
            
            assert os.path.exists(nested_path)
            assert os.path.isfile(nested_path)


class TestJSONExport:
    """Test cases for JSON export functionality."""
    
    def test_json_export_success(self, evaluation_result):
        """
        Test successful JSON export.
        
        Verifies that JSON export creates a valid file with correct
        structure and complete data.
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
            temp_path = temp_file.name
        
        try:
            evaluation_result.export_json(temp_path)
            
            # Verify file exists
            assert os.path.exists(temp_path)
            
            # Verify JSON content
            with open(temp_path, 'r', encoding='utf-8') as jsonfile:
                data = json.load(jsonfile)
                
                # Verify structure
                assert 'metadata' in data
                assert 'summary' in data
                assert 'scenario' in data
                assert 'task_results' in data
                
                # Verify metadata
                metadata = data['metadata']
                assert metadata['scenario_id'] == 'test-scenario-001'
                assert metadata['scenario_title'] == 'Test Scenario'
                assert metadata['industry'] == 'testing'
                
                # Verify summary
                summary = data['summary']
                assert summary['total_tasks'] == 2
                assert summary['successful_tasks'] == 1
                assert summary['success_rate'] == 50.0
                
                # Verify scenario data is preserved
                assert data['scenario']['scenario_id'] == 'test-scenario-001'
                
                # Verify task results are preserved
                assert len(data['task_results']) == 2
                assert data['task_results'][0]['task_id'] == 'task-1'
                
        finally:
            # Clean up
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_json_directory_creation(self, evaluation_result):
        """
        Test JSON export with non-existent directory.
        
        Verifies that missing directories are created automatically
        when exporting JSON files.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            nested_path = os.path.join(temp_dir, "exports", "json", "results.json")
            
            evaluation_result.export_json(nested_path)
            
            assert os.path.exists(nested_path)
            assert os.path.isfile(nested_path)


class TestHTMLExport:
    """Test cases for HTML export functionality."""
    
    def test_html_export_success(self, evaluation_result):
        """
        Test successful HTML export without charts.
        
        Verifies that HTML export creates a valid file with proper
        HTML structure and content.
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as temp_file:
            temp_path = temp_file.name
        
        try:
            evaluation_result.export_html(temp_path, include_charts=False)
            
            # Verify file exists
            assert os.path.exists(temp_path)
            
            # Verify HTML content
            with open(temp_path, 'r', encoding='utf-8') as htmlfile:
                content = htmlfile.read()
                
                # Verify basic HTML structure
                assert '<!DOCTYPE html>' in content
                assert '<html lang="en">' in content
                assert '<head>' in content
                assert '<body>' in content
                assert '</html>' in content
                
                # Verify CSS is included
                assert '<style>' in content
                assert '</style>' in content
                
                # Verify content sections
                assert 'Evaluation Report' in content
                assert 'Test Scenario' in content
                assert 'testing' in content  # industry
                assert 'Summary' in content
                assert 'Task Details' in content
                
                # Verify task information
                assert 'task-1' in content
                assert 'task-2' in content
                assert 'tool_call_correctness' in content
                
                # Charts should not be included
                assert 'canvas' not in content
                assert 'successChart' not in content
                
        finally:
            # Clean up
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_html_export_with_charts(self, evaluation_result):
        """
        Test successful HTML export with charts.
        
        Verifies that HTML export includes chart functionality
        when requested.
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as temp_file:
            temp_path = temp_file.name
        
        try:
            evaluation_result.export_html(temp_path, include_charts=True)
            
            # Verify file exists
            assert os.path.exists(temp_path)
            
            # Verify HTML content includes charts
            with open(temp_path, 'r', encoding='utf-8') as htmlfile:
                content = htmlfile.read()
                
                # Verify chart elements are included
                assert 'canvas' in content
                assert 'successChart' in content
                assert '<script>' in content
                assert 'getContext' in content
                
        finally:
            # Clean up
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_html_directory_creation(self, evaluation_result):
        """
        Test HTML export with non-existent directory.
        
        Verifies that missing directories are created automatically
        when exporting HTML files.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            nested_path = os.path.join(temp_dir, "exports", "html", "report.html")
            
            evaluation_result.export_html(nested_path, include_charts=True)
            
            assert os.path.exists(nested_path)
            assert os.path.isfile(nested_path)


class TestErrorHandling:
    """Test cases for error handling in export functionality."""
    
    def test_invalid_csv_path(self, evaluation_result):
        """
        Test CSV export with invalid file path.
        
        Verifies proper error handling when CSV export fails
        due to invalid file path or permissions.
        """
        # Use a path with invalid characters on Windows
        import platform
        if platform.system() == "Windows":
            invalid_path = "C:\\invalid<>|:path\\results.csv"
        else:
            invalid_path = "/proc/invalid/path/results.csv"  # Typically read-only on Linux
        
        with pytest.raises((OSError, IOError, PermissionError, ValueError)):
            evaluation_result.export_csv(invalid_path)
    
    def test_invalid_json_path(self, evaluation_result):
        """
        Test JSON export with invalid file path.
        
        Verifies proper error handling when JSON export fails
        due to invalid file path or permissions.
        """
        # Use a path with invalid characters on Windows
        import platform
        if platform.system() == "Windows":
            invalid_path = "C:\\invalid<>|:path\\results.json"
        else:
            invalid_path = "/proc/invalid/path/results.json"  # Typically read-only on Linux
        
        with pytest.raises((OSError, IOError, PermissionError, ValueError)):
            evaluation_result.export_json(invalid_path)
    
    def test_invalid_html_path(self, evaluation_result):
        """
        Test HTML export with invalid file path.
        
        Verifies proper error handling when HTML export fails
        due to invalid file path or permissions.
        """
        # Use a path with invalid characters on Windows
        import platform
        if platform.system() == "Windows":
            invalid_path = "C:\\invalid<>|:path\\report.html"
        else:
            invalid_path = "/proc/invalid/path/report.html"  # Typically read-only on Linux
        
        with pytest.raises((OSError, IOError, PermissionError, ValueError)):
            evaluation_result.export_html(invalid_path)


class TestDataIntegrity:
    """Test cases for data integrity in exports."""
    
    def test_special_characters_handling(self):
        """
        Test export handling of special characters and unicode.
        
        Verifies that special characters in scenario and result data
        are properly handled in all export formats.
        """
        scenario_with_special_chars = {
            "scenario_id": "test-special-chars",
            "title": "Test with Special Characters: <>&\"'",
            "industry": "testing",
            "description": "Test scenario with émojis 🚀 and unicode characters"
        }
        
        task_results_with_special_chars = [
            {
                "task_id": "task-special",
                "metrics": [
                    {
                        "metric": "special_metric_test",
                        "score": 1.0,
                        "threshold": 1.0,
                        "success": True
                    }
                ]
            }
        ]
        
        result = EvaluationResult(scenario_with_special_chars, task_results_with_special_chars)
        
        # Test CSV export
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as temp_file:
            temp_path = temp_file.name
        
        try:
            result.export_csv(temp_path)
            assert os.path.exists(temp_path)
            
            # Verify special characters are preserved
            with open(temp_path, 'r', encoding='utf-8') as csvfile:
                content = csvfile.read()
                assert "🚀" in content
                assert "émojis" in content
                
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        
        # Test JSON export  
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
            temp_path = temp_file.name
        
        try:
            result.export_json(temp_path)
            assert os.path.exists(temp_path)
            
            with open(temp_path, 'r', encoding='utf-8') as jsonfile:
                data = json.load(jsonfile)
                assert "🚀" in data['scenario']['description']
                
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        
        # Test HTML export
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as temp_file:
            temp_path = temp_file.name
        
        try:
            result.export_html(temp_path)
            assert os.path.exists(temp_path)
            
            with open(temp_path, 'r', encoding='utf-8') as htmlfile:
                content = htmlfile.read()
                # Special characters should be properly escaped in HTML
                assert "émojis" in content
                
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
