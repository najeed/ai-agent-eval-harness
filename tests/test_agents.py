"""
Test suite for AI agent API functionality and integration.

This module contains comprehensive tests for the AI agent's Flask-based API,
including health checks, task execution, error handling, and response validation.
The tests ensure the agent can properly handle various types of task requests
and return appropriate responses in the expected format.

The test suite covers:
- Agent health and basic functionality
- Task execution with valid descriptions
- Error handling for missing or invalid parameters
- Multiple tool execution scenarios
- Response format validation

Example:
    To run these tests specifically:
    pytest tests/test_agents.py -v
"""

import pytest
from sample_agent import agent_app

app = agent_app.app


def test_agent_health_check():
    """
    Test basic agent health and task execution functionality.
    
    This test verifies that the agent API is functioning correctly by
    sending a valid task description and checking that the response
    contains the expected fields. The test ensures the agent can
    process requests and return a structured response with either
    tool_name, tool_names, or instructions fields.
    
    Args:
        None
        
    Returns:
        None
        
    Raises:
        AssertionError: If the response status is not 200 or missing expected fields
        
    Example:
        Sends task: "identify the customer speed tier"
        Expected response: {"tool_name": "..."} or {"tool_names": [...]} or {"instructions": "..."}
    """
    # Flask test client can check if the app loads
    client = app.test_client()
    response = client.post('/execute_task', json={"task_description": "identify the customer speed tier"})
    assert response.status_code == 200
    data = response.get_json()
    assert "tool_name" in data or "tool_names" in data or "instructions" in data


def test_agent_missing_task_description():
    """
    Test error handling when task description is missing from request.
    
    This test verifies that the agent API properly handles requests
    that are missing the required 'task_description' parameter. The
    test ensures that the API returns an appropriate error response
    (HTTP 400) with an error message rather than crashing or
    processing an invalid request.
    
    Args:
        None
        
    Returns:
        None
        
    Raises:
        AssertionError: If the response status is not 400 or missing error field
        
    Example:
        Sends request: {}
        Expected response: {"error": "..."} with status 400
    """
    client = app.test_client()
    response = client.post('/execute_task', json={})
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data


def test_agent_multiple_tools():
    """
    Test agent's ability to handle requests requiring multiple tools.
    
    This test verifies that the agent can properly process complex
    task descriptions that require the use of multiple tools. The
    test sends a task description that implies multiple tool usage
    and checks that the response contains the appropriate tool
    information in the expected format.
    
    Args:
        None
        
    Returns:
        None
        
    Raises:
        AssertionError: If the response doesn't contain tool information
        
    Example:
        Sends task: "run a remote line test and speed test"
        Expected response: Contains "tool_names" or "tool_name" field
    """
    client = app.test_client()
    response = client.post('/execute_task', json={"task_description": "run a remote line test and speed test"})
    assert response.status_code == 200
    data = response.get_json()
    assert "tool_names" in data or "tool_name" in data 