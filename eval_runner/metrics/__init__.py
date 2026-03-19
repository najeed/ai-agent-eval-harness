from __future__ import annotations
from typing import Dict, Callable, Optional, Any

class MetricRegistry:
    """Registry for evaluation metrics."""
    _metrics: Dict[str, Callable] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator to register a metric function."""
        def decorator(func: Callable):
            cls._metrics[name] = func
            return func
        return decorator

    @classmethod
    def get(cls, name: str) -> Optional[Callable]:
        """Retrieves a metric function by name."""
        return cls._metrics.get(name)

    @classmethod
    def list_metrics(cls) -> list:
        """Returns a list of registered metric names."""
        return list(cls._metrics.keys())

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
    calculate_consistency_score
)
from .accuracy import calculate_luna_judge_score
