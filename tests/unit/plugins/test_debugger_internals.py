"""
test_debugger_internals.py

Unit tests for the Debugger core logic, focusing on breakpoint management 
and state capture to close coverage gaps in eval_runner/debugger/core.py.
"""

import pytest
from unittest.mock import MagicMock
from eval_runner.debugger.core import Debugger

def test_debugger_breakpoint_management():
    """Verify adding/removing/checking breakpoints."""
    db = Debugger()
    db.add_breakpoint("n1")
    assert db.is_at_breakpoint("n1")
    assert not db.is_at_breakpoint("n2")
    
    db.remove_breakpoint("n1")
    assert not db.is_at_breakpoint("n1")

def test_debugger_pause_resume():
    """Verify debugger pause/resume state."""
    db = Debugger()
    assert not db.is_paused()
    db.pause()
    assert db.is_paused()
    db.resume()
    assert not db.is_paused()

def test_debugger_snapshot_capture():
    """Verify that the debugger captures a valid world state snapshot."""
    db = Debugger()
    mock_sandbox = MagicMock()
    mock_sandbox.state = {"token": "xyz"}
    mock_sandbox.shared_state.registry = {"global:v": 1}
    
    snapshot = db.capture_snapshot(mock_sandbox, "n1")
    assert snapshot["node_id"] == "n1"
    assert snapshot["state"]["token"] == "xyz"
    assert snapshot["shared_state"]["global:v"] == 1
    assert "timestamp" in snapshot
