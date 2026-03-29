"""
eval_runner/debugger/core.py

Hardened Debugger implementation for the AES v1.2 engine.
Provides breakpoint management and world-state snapshot capture.
"""

from typing import Dict, Any, Set, Optional
import time

class Debugger:
    """Master debugger for the evaluation session."""
    
    def __init__(self):
        self.breakpoints: Set[str] = set()
        self.paused = False
        self.snapshots: Dict[str, Any] = {}

    def add_breakpoint(self, node_id: str):
        """Register a node for breakpoint monitoring."""
        self.breakpoints.add(node_id)

    def remove_breakpoint(self, node_id: str):
        """Remove a node from breakpoint monitoring."""
        self.breakpoints.discard(node_id)

    def is_at_breakpoint(self, node_id: str) -> bool:
        """Check if a node has an active breakpoint."""
        return node_id in self.breakpoints

    def pause(self):
        """Pause the execution loop."""
        self.paused = True

    def resume(self):
        """Resume the execution loop."""
        self.paused = False

    def is_paused(self) -> bool:
        """Check if the debugger is currently paused."""
        return self.paused

    def capture_snapshot(self, sandbox: Any, node_id: str) -> Dict[str, Any]:
        """Capture the current world state and registry for a specific node."""
        snapshot = {
            "node_id": node_id,
            "timestamp": time.time(),
            "state": (sandbox.state.copy() if hasattr(sandbox, "state") else {}),
            "shared_state": (sandbox.shared_state.registry.copy() if hasattr(sandbox, "shared_state") and hasattr(sandbox.shared_state, "registry") else {}),
        }
        self.snapshots[node_id] = snapshot
        return snapshot
