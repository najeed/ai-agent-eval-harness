import logging
from typing import Any

from . import config

logger = logging.getLogger(__name__)


class RoutingRegistry:
    """
    Manages the Capability-Based Routing manifest.
    Decouples scenario 'requires' from physical infrastructure endpoints.
    """

    _cache: dict[str, Any] | None = None

    @classmethod
    def resolve(cls, capabilities: list[str]) -> dict[str, Any]:
        """
        Resolves the best matching infrastructure for a list of capabilities.
        Returns a dict with 'protocol', 'endpoint', and optional 'metadata'.
        """
        mappings = cls.get_resolved_registry()

        # 1. Exact Capability Match
        for cap in capabilities:
            if cap in mappings:
                logger.debug(f"Resolved capability '{cap}' to {mappings[cap]}")
                return mappings[cap]

        # 2. Default Fallback
        if "default" in mappings:
            logger.debug("Resolved to default routing.")
            return mappings["default"]

        # 3. Empty Fallback (caller will use global defaults)
        return {}

    @classmethod
    def get_resolved_registry(cls) -> dict[str, Any]:
        """
        Loads and merges all routing sources deterministically.
        Now sources from the Centralized RegistryManager.
        """
        if cls._cache is not None:
            return cls._cache

        # 1. Source from Centralized Registry
        registry = config.RegistryManager.get_resolved_registry()
        resolved_mappings = registry.get("routing", {}).get("mappings", {})

        logger.debug(
            f"   [Routing] Resolution complete via Centralized Registry. "
            f"Mappings: {len(resolved_mappings)}"
        )

        cls._cache = resolved_mappings
        return resolved_mappings

    @classmethod
    def reload(cls):
        """Forces a reload of the registry."""
        config.RegistryManager.reload()
        cls._cache = None
        return cls.get_resolved_registry()
