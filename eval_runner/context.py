from __future__ import annotations

"""
context.py

Defines typed context objects for evaluation sessions and turns.
These objects bridge the Core with Plugins, replacing raw dictionaries.

Security: Frozen dataclasses with deep-copy protection on mutable nested
fields to prevent Prototype Pollution (Audit Point #8).
"""

import copy  # noqa: E402
import types  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from typing import Any  # noqa: E402


def _freeze_dict(d: dict) -> types.MappingProxyType:
    """Wrap a dict in a read-only MappingProxyType."""
    return types.MappingProxyType(copy.deepcopy(d))


@dataclass(frozen=True)
class EvaluationContext:
    """Context for an entire evaluation scenario."""

    identifier: str
    scenario_data: dict[str, Any]
    run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    global_state: dict[str, Any] = field(default_factory=dict)
    plugin_data: dict[str, Any] = field(
        default_factory=dict
    )  # Bucket for plugins to store cross-task data
    grounding_hits: dict[str, dict[str, int]] = field(
        default_factory=lambda: {"policies": {}, "tools": {}}
    )
    span_context: dict[str, Any] | None = None

    def __post_init__(self):
        # Deep-copy and freeze mutable dict fields to prevent Prototype Pollution
        object.__setattr__(self, "scenario_data", _freeze_dict(self.scenario_data))
        object.__setattr__(self, "metadata", _freeze_dict(self.metadata))
        object.__setattr__(self, "global_state", _freeze_dict(self.global_state))


@dataclass(frozen=True)
class TurnContext:
    """Context for a single conversation turn."""

    task_id: str
    turn_number: int
    current_message: str
    history: tuple[dict[str, Any], ...]  # Tuple for immutability
    input_payload: dict[str, Any] = field(default_factory=dict)
    agent_response: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    span_context: dict[str, Any] | None = None

    def __post_init__(self):
        # Convert history list to tuple if passed as list
        if isinstance(self.history, list):
            object.__setattr__(self, "history", tuple(copy.deepcopy(self.history)))
