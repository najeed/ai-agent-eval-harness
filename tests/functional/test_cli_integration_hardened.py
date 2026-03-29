"""
test_cli_integration_hardened.py

End-to-End CLI integration tests that use the REAL parser.
This replaces the fragile 'Mock Namespace' pattern and prevents 
argument-stripping regressions.
"""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from eval_runner import cli

def test_evaluate_protocol_propagation():
    """Verifies that 'evaluate' correctly parses and propagates protocols."""
    # We use a real parser flow by calling cli.main() but patching the handler
    test_args = [
        "multiagent-eval", "evaluate", 
        "--path", "scenarios/test.json", 
        "--protocol", "local", 
        "--agent-cmd", "python agent.py"
    ]
    
    with patch("sys.argv", test_args), \
         patch("eval_runner.handlers.evaluation.handle_evaluate") as mock_handler:
        cli.main()
        
        # Verify the handler received an object with the expected attributes
        args_passed = mock_handler.call_args[0][0]
        assert args_passed.protocol == "local"
        assert args_passed.agent_cmd == "python agent.py"

def test_run_protocol_propagation():
    """Verifies that 'run' correctly parses and propagates protocols."""
    test_args = [
        "multiagent-eval", "run", 
        "--scenario", "scenarios/test.json", 
        "--protocol", "local", 
        "--agent", "python agent.py"
    ]
    
    with patch("sys.argv", test_args), \
         patch("eval_runner.handlers.evaluation.handle_run") as mock_handler:
        cli.main()
        
        args_passed = mock_handler.call_args[0][0]
        assert args_passed.protocol == "local"
        assert args_passed.agent == "python agent.py"

def test_record_protocol_propagation():
    """Verifies that 'record' correctly parses and propagates protocols."""
    test_args = [
        "multiagent-eval", "record", 
        "--protocol", "local", 
        "--agent", "python debug_agent.py"
    ]
    
    with patch("sys.argv", test_args), \
         patch("eval_runner.handlers.evaluation.handle_record") as mock_handler:
        cli.main()
        
        args_passed = mock_handler.call_args[0][0]
        assert args_passed.protocol == "local"
        assert args_passed.agent == "python debug_agent.py"

def test_playground_protocol_propagation():
    """Verifies that 'playground' correctly parses and propagates protocols."""
    test_args = [
        "multiagent-eval", "playground", 
        "--protocol", "local", 
        "--agent", "python playground.py"
    ]
    
    with patch("sys.argv", test_args), \
         patch("eval_runner.handlers.evaluation.handle_playground") as mock_handler:
        cli.main()
        
        args_passed = mock_handler.call_args[0][0]
        assert args_passed.protocol == "local"
        assert args_passed.agent == "python playground.py"

def test_cli_help_is_snappy():
    """Verifies that help output is still accessible and hasn't regressed."""
    with patch("sys.argv", ["multiagent-eval", "--help"]), \
         pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 0
