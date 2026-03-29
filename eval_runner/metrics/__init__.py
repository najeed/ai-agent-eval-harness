from __future__ import annotations
from typing import Dict, Callable, Optional


class MetricRegistry:
    """Registry for evaluation metrics."""

    _metrics: Dict[str, Callable] = {}
    _discovered: bool = False

    @classmethod
    def register(cls, name: str):
        """Decorator to register a metric function."""

        def decorator(func: Callable):
            cls._metrics[name] = func
            return func

        return decorator

    @classmethod
    def _discover(cls):
        """Triggers discovery of metrics."""
        if cls._discovered:
            return
        # Modules are imported at end of file to populate registry
        from . import utils, core, accuracy, planning, defense, technical
        cls._discovered = True

    @classmethod
    def get(cls, name: str) -> Optional[Callable]:
        """Retrieves a metric function by name."""
        cls._discover()
        return cls._metrics.get(name)

    @classmethod
    def list_metrics(cls) -> list:
        """Returns a list of registered metric names."""
        cls._discover()
        return list(cls._metrics.keys())

    @classmethod
    def reset(cls):
        """Resets the metric registry. 
        Note: We keep the registered metrics as they are static functions.
        We only reset the discovery flag if we want to force re-discovery.
        """
        # cls._metrics = {} # Don't clear static registrations
        cls._discovered = True # Keep them discovered


# --- Import sub-modules to trigger registration ---
# Legacy order matters for shadowing if any (none expected)
from . import utils, core, accuracy, planning, defense, technical

# Re-export core metrics for direct access (MetricRegistry.get is preferred, but tests use direct access)
from .core import (
    calculate_tool_call_correctness,
    calculate_generic_accuracy,
    calculate_communication_clarity,
    calculate_state_correctness,
    calculate_policy_compliance,
    calculate_path_parsimony,
    calculate_delegation_latency,
    calculate_delegation_loop_risk,
    calculate_consensus_scoring,
    calculate_pii_safety,
    calculate_refusal_calibration,
    calculate_consistency_score,
)
from .accuracy import calculate_luna_judge_score
