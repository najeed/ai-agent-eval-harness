import json
import yaml
import logging
from typing import Any, Dict, List, Optional
from . import config

logger = logging.getLogger(__name__)

class RoutingRegistry:
    """
    Manages the Capability-Based Routing manifest.
    Decouples scenario 'requires' from physical infrastructure endpoints.
    """
    _cache: Optional[Dict[str, Any]] = None

    @classmethod
    def resolve(cls, capabilities: List[str]) -> Dict[str, Any]:
        """
        Resolves the best matching infrastructure for a list of capabilities.
        Returns a dict with 'protocol', 'endpoint', and optional 'metadata'.
        """
        registry = cls.get_resolved_registry()
        mappings = registry.get("mappings", {})

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
    def get_resolved_registry(cls) -> Dict[str, Any]:
        """
        Loads and merges all routing sources deterministically.
        Priority: manifest.json (default 0) < routing.d/*.json (explicit priority field).
        """
        if cls._cache is not None:
            return cls._cache

        # Collected fragments: list of (priority, filename, mappings)
        fragments = []

        # 1. Main Manifest baseline
        if config.ROUTING_CONFIG_PATH.exists():
            try:
                with open(config.ROUTING_CONFIG_PATH, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    if content:
                        fragments.append((
                            content.get("priority", 0), 
                            "manifest.json", 
                            content.get("mappings", {})
                        ))
            except Exception as e:
                logger.error(f"Failed to load routing manifest from {config.ROUTING_CONFIG_PATH}: {e}")

        # 2. Extension Directory (.aes/config/routing.d/)
        d_dir = config.ROUTING_D_DIR
        if d_dir.exists() and d_dir.is_dir():
            paths = sorted(list(d_dir.glob("*.json")) + list(d_dir.glob("*.yaml")))
            for path in paths:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        ext = yaml.safe_load(f) if path.suffix in [".yaml", ".yml"] else json.load(f)
                        if ext and "mappings" in ext:
                            fragments.append((
                                ext.get("priority", 10), # Extensions default to higher priority than manifest
                                path.name,
                                ext["mappings"]
                            ))
                except Exception as e:
                    logger.warning(f"Failed to load routing extension from {path.name}: {e}")

        # 3. Deterministic Merge: Sort by Priority (Ascending), then Name
        # Later (higher priority) fragments will overwrite earlier ones in dict.update()
        fragments.sort(key=lambda x: (x[0], x[1]))
        
        resolved_mappings = {}
        for prio, name, mappings in fragments:
            for cap, route in mappings.items():
                if cap in resolved_mappings:
                    logger.info(f"      [Routing] Overwriting capability '{cap}' with higher priority source: {name} (Prio: {prio})")
                resolved_mappings[cap] = route

        cls._cache = {"mappings": resolved_mappings}
        return resolved_mappings

    @classmethod
    def reload(cls):
        """Forces a reload of the registry."""
        cls._cache = None
        return cls.get_resolved_registry()
