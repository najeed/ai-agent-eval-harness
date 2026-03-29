"""
eval_runner/hitl/registry.py

Hardened HITL (Human-in-the-loop) Strategy Registry for the AES v1.2 engine.
Provides pluggable management and lifecycle hooks for HITL interactions.
"""

from typing import Dict, Type, Any, Optional
from abc import ABC, abstractmethod

class BaseHitlStrategy(ABC):
    """Abstract base class for all HITL strategies."""
    
    @abstractmethod
    def handle_pause(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        """Executed during the HITL_PAUSE event."""
        pass


class DefaultHitlStrategy(BaseHitlStrategy):
    """The standard, no-op HITL strategy."""
    
    def handle_pause(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        """Default behavior: Immediately resume."""
        return {"action": "resume"}


class HitlRegistry:
    """Registry for managing and looking up HITL strategies."""
    
    def __init__(self):
        self.strategies: Dict[str, Type[BaseHitlStrategy]] = {}
        self.instances: Dict[str, BaseHitlStrategy] = {}

    def register(self, name: str, strategy_cls: Type[BaseHitlStrategy]):
        """Register a new HITL strategy."""
        self.strategies[name] = strategy_cls

    def get_strategy(self, name: str) -> BaseHitlStrategy:
        """Lookup and return a singleton instance of the strategy."""
        if name not in self.instances:
            strategy_cls = self.strategies.get(name, DefaultHitlStrategy)
            self.instances[name] = strategy_cls()
        return self.instances[name]


# Global singleton for the HITL registry
global_hitl_registry = HitlRegistry()
