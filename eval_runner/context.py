"""
context.py

Defines typed context objects for evaluation sessions and turns.
These objects bridge the Core with Plugins, replacing raw dictionaries.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class EvaluationContext:
    """Context for an entire evaluation scenario."""
    scenario_id: str
    scenario_data: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    global_state: Dict[str, Any] = field(default_factory=dict)
    plugin_data: Dict[str, Any] = field(default_factory=dict) # Bucket for plugins to store cross-task data
    grounding_hits: Dict[str, Dict[str, int]] = field(default_factory=lambda: {"policies": {}, "tools": {}})

@dataclass
class TurnContext:
    """Context for a single conversation turn."""
    task_id: str
    turn_number: int
    current_message: str
    history: List[Dict[str, Any]]
    agent_response: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
