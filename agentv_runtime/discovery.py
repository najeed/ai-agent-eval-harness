"""
agentv_runtime.discovery
Canonical extension discovery engine for AgentV OS.
"""

from __future__ import annotations

import importlib.metadata
import logging
import os
import threading
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)

ENTRY_POINT_NAMESPACE = "agentv_runtime"

_registry_lock = threading.RLock()
_extension_registry: dict[str, Any] = {}


def resolve_extension(  # noqa: UP047
    family: str,
    *,
    explicit: T | None = None,
    env_var: str | None = None,
    default_factory: Callable[[], T],
) -> T:
    """
    Resolves an extension instance for a given family in strict priority order:
    1. Explicit instance provided by caller (injected dependency)
    2. Cached instance from process extension registry
    3. Provider named in environment variable (e.g. AGENTV_RUN_STORES=database)
    4. Provider named 'default' registered in entry points
    5. Single registered external provider (auto-bind if unique)
    6. Built-in reference implementation (fallback default_factory)
    """
    if explicit is not None:
        return explicit

    with _registry_lock:
        if family in _extension_registry and _extension_registry[family] is not None:
            return _extension_registry[family]

        singular_family = family[:-1] if family.endswith("s") else family
        target_name = (
            os.getenv(env_var)
            if env_var
            else os.getenv(f"AGENTV_{family.upper()}")
            or os.getenv(f"AGENTV_{singular_family.upper()}")
        )
        entry_point_group = f"{ENTRY_POINT_NAMESPACE}.{family}"

        discovered = {}
        try:
            for ep in importlib.metadata.entry_points(group=entry_point_group):
                discovered[ep.name] = ep
        except Exception as exc:
            logger.warning("Failed to enumerate entry points for '%s': %s", entry_point_group, exc)

        instance: T | None = None

        if target_name:
            if target_name not in discovered:
                raise RuntimeError(
                    f"Configured {family} provider '{target_name}' was not discovered in "
                    f"entry-point group '{entry_point_group}'."
                )
            try:
                provider_cls = discovered[target_name].load()
                instance = provider_cls()
                logger.info("Using configured %s provider '%s'", family, target_name)
            except Exception as exc:
                raise RuntimeError(
                    f"Configured {family} provider '{target_name}' failed to load."
                ) from exc

        if instance is None and "default" in discovered:
            try:
                provider_cls = discovered["default"].load()
                instance = provider_cls()
                logger.info("Using default registered %s provider", family)
            except Exception as exc:
                logger.warning("Failed to load default registered %s provider: %s", family, exc)

        if instance is None and len(discovered) == 1:
            name, ep = next(iter(discovered.items()))
            try:
                provider_cls = ep.load()
                instance = provider_cls()
                logger.info("Auto-bound single registered %s provider '%s'", family, name)
            except Exception as exc:
                logger.warning(
                    "Failed to load single registered %s provider '%s': %s", family, name, exc
                )

        if instance is not None:
            _extension_registry[family] = instance
            return instance

        return default_factory()


def set_extension(family: str, instance: Any) -> None:
    """Injects or overrides an extension instance in the process registry."""
    with _registry_lock:
        if instance is None:
            _extension_registry.pop(family, None)
        else:
            _extension_registry[family] = instance


def reset_extensions(family: str | None = None) -> None:
    """Clears cached extension instance(s) from the process registry."""
    with _registry_lock:
        if family is not None:
            _extension_registry.pop(family, None)
        else:
            _extension_registry.clear()


__all__ = [
    "ENTRY_POINT_NAMESPACE",
    "resolve_extension",
    "set_extension",
    "reset_extensions",
]
