from __future__ import annotations
"""
context.py

Defines typed context objects for evaluation sessions and turns.
These objects bridge the Core with Plugins, replacing raw dictionaries.

Security: Frozen dataclasses with deep-copy protection on mutable nested
fields to prevent Prototype Pollution (Audit Point #8).
"""

import copy
import types
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

def _freeze_dict(d: dict) -> types.MappingProxyType:
    """Wrap a dict in a read-only MappingProxyType."""
    return types.MappingProxyType(copy.deepcopy(d))

@dataclass(frozen=True)
class EvaluationContext:
    """Context for an entire evaluation scenario."""
    scenario_id: str
    scenario_data: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    global_state: Dict[str, Any] = field(default_factory=dict)
    plugin_data: Dict[str, Any] = field(default_factory=dict) # Bucket for plugins to store cross-task data
    grounding_hits: Dict[str, Dict[str, int]] = field(default_factory=lambda: {"policies": {}, "tools": {}})

    def __post_init__(self):
        # Deep-copy and freeze mutable dict fields to prevent Prototype Pollution
        object.__setattr__(self, 'scenario_data', _freeze_dict(self.scenario_data))
        object.__setattr__(self, 'metadata', _freeze_dict(self.metadata))
        object.__setattr__(self, 'global_state', _freeze_dict(self.global_state))

@dataclass(frozen=True)
class TurnContext:
    """Context for a single conversation turn."""
    task_id: str
    turn_number: int
    current_message: str
    history: Tuple[Dict[str, Any], ...]  # Tuple for immutability
    agent_response: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Convert history list to tuple if passed as list
        if isinstance(self.history, list):
            object.__setattr__(self, 'history', tuple(copy.deepcopy(self.history)))
