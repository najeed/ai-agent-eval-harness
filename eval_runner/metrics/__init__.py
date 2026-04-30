from __future__ import annotations

from collections.abc import Callable
from typing import Dict, Optional  # noqa: F401, UP035


class MetricRegistry:
    """Registry for evaluation metrics."""

    _metrics: dict[str, Callable] = {}
    _provenance: dict[str, str] = {}  # name -> source (e.g. "CORE", plugin class name)
    _discovered: bool = False

    @classmethod
    def register(cls, name: str, source: str = "CORE"):
        """Decorator to register a metric function with optional source provenance."""

        def decorator(func: Callable):
            cls._metrics[name] = func
            cls._provenance[name] = source
            return func

        return decorator

    @classmethod
    def _discover(cls):
        """Triggers discovery of metrics."""
        if cls._discovered:
            return
        # Modules are imported at end of file to populate registry
        cls._discovered = True

    @classmethod
    def get(cls, name: str) -> Callable | None:
        """Retrieves a metric function by name."""
        cls._discover()
        return cls._metrics.get(name)

    @classmethod
    def get_source(cls, name: str) -> str:
        """Retrieves the source provenance of a metric."""
        cls._discover()
        return cls._provenance.get(name, "UNKNOWN")

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
        cls._discovered = True  # Keep them discovered


# --- Import sub-modules to trigger registration ---
# Legacy order matters for shadowing if any (none expected)
from . import accuracy, core, defense, planning, technical, utils  # noqa: E402, F401
from .accuracy import calculate_luna_judge_score  # noqa: E402, F401

# Re-export core metrics for direct access (MetricRegistry.get is preferred, but tests use direct access)  # noqa: E501
from .core import (  # noqa: E402
    calculate_communication_clarity,  # noqa: F401
    calculate_consensus_scoring,  # noqa: F401
    calculate_consistency_score,  # noqa: F401
    calculate_delegation_latency,  # noqa: F401
    calculate_delegation_loop_risk,  # noqa: F401
    calculate_generic_accuracy,  # noqa: F401
    calculate_path_parsimony,  # noqa: F401
    calculate_pii_safety,  # noqa: F401
    calculate_policy_compliance,  # noqa: F401
    calculate_refusal_calibration,  # noqa: F401
    calculate_state_correctness,  # noqa: F401
    calculate_tool_call_correctness,  # noqa: F401
)
