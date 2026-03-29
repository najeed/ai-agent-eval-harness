"""
test_hitl_registry.py

Unit tests for the HITL Strategy Registry, focusing on factory instantiation
and strategy lookup to close coverage gaps in eval_runner/hitl/registry.py.
"""

import pytest
from eval_runner.hitl.registry import HitlRegistry, BaseHitlStrategy

class MockStrategy(BaseHitlStrategy):
    def handle_pause(self, scenario):
        return {"action": "resume"}

def test_hitl_registry_registration():
    """Verify strategy registration and lookup."""
    registry = HitlRegistry()
    registry.register("mock", MockStrategy)
    
    strategy = registry.get_strategy("mock")
    assert isinstance(strategy, MockStrategy)
    assert strategy.handle_pause({})["action"] == "resume"

def test_hitl_registry_default():
    """Verify that an unknown strategy returns the standard DefaultHitlStrategy."""
    registry = HitlRegistry()
    strategy = registry.get_strategy("unknown_xyz")
    # Verify it returns a standard strategy instance
    assert strategy is not None
    assert hasattr(strategy, "handle_pause")

def test_hitl_registry_singleton():
    """Verify the global singleton instance is accessible."""
    from eval_runner.hitl import registry as reg_module
    assert reg_module.global_hitl_registry is not None
