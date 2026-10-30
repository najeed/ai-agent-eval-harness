"""
agentv_runtime.discovery
Canonical extension discovery engine for AgentV OS.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import inspect
import logging
import os
import pkgutil
import threading
from collections.abc import Callable
from pathlib import Path
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
        disable_external = bool(os.getenv("AGENTV_DISABLE_EXTERNAL_PLUGINS"))
        try:
            for ep in importlib.metadata.entry_points(group=entry_point_group):
                if disable_external and not target_name:
                    dist_name = getattr(getattr(ep, "dist", None), "name", None)
                    if dist_name and dist_name not in {"agentv", "ai-agent-eval-harness"}:
                        continue
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


def discover_extension_entry_points(family: str) -> list[Any]:
    """Return entry points from the one canonical AgentV extension namespace."""
    try:
        return list(importlib.metadata.entry_points(group=f"{ENTRY_POINT_NAMESPACE}.{family}"))
    except Exception as exc:
        logger.warning("Failed to enumerate entry points for '%s': %s", family, exc)
        return []


def discover_plugin_instances(
    directory: str | Path, base_class: type[Any], *, package_prefix: str = ""
) -> list[Any]:
    """Load every plugin implementation from a project directory.

    Plugins are intentionally multi-load; unlike ``resolve_extension`` this
    returns every matching instance and is the single discovery operation for
    entry-point and project plugin registries.
    """
    root = Path(directory)
    if not root.is_dir():
        return []
    instances: list[Any] = []
    for source in root.glob("*.py"):
        if source.name == "__init__.py":
            continue
        module_name = f"{package_prefix}.{source.stem}" if package_prefix else source.stem
        try:
            module = importlib.import_module(module_name)
            for _, candidate in inspect.getmembers(module, inspect.isclass):
                if (
                    candidate is not base_class
                    and issubclass(candidate, base_class)
                    and candidate.__module__ == module.__name__
                ):
                    instances.append(candidate())
        except Exception as exc:
            logger.warning("Failed to load project plugin '%s': %s", module_name, exc)
    return instances


def discover_declared_plugin_instances(
    declarations: list[dict[str, Any]],
    base_class: type[Any],
) -> list[tuple[Any, dict[str, Any]]]:
    """Instantiate every enabled plugin declared by a runtime registry.

    This is deliberately multi-load (unlike ``resolve_extension``).  Policy
    validation and trust decisions remain with the caller, while module/class
    discovery is centralized here for entry-point, project, and declarative
    plugin sources.
    """
    instances: list[tuple[Any, dict[str, Any]]] = []
    for declaration in declarations:
        if not isinstance(declaration, dict) or not declaration.get("enabled", True):
            continue
        module_name = declaration.get("module")
        class_name = declaration.get("class")
        if not isinstance(module_name, str) or not isinstance(class_name, str):
            raise ValueError(f"Malformed plugin declaration: {declaration!r}")
        module = importlib.import_module(module_name)
        plugin_class = getattr(module, class_name)
        if not inspect.isclass(plugin_class) or not issubclass(plugin_class, base_class):
            raise TypeError(
                f"Declared plugin {module_name}.{class_name} does not implement contract"
            )
        instances.append((plugin_class(), declaration))
    return instances


def discover_classes_in_package(
    package: Any, base_class: type[Any], *, instantiate: bool = False, recursive: bool = True
) -> dict[str, Any]:
    """Discover matching classes in a package through the canonical scanner."""
    result: dict[str, Any] = {}
    iterator = (
        pkgutil.walk_packages(package.__path__, f"{package.__name__}.")
        if recursive
        else pkgutil.iter_modules(package.__path__, f"{package.__name__}.")
    )
    for item in iterator:
        try:
            module = importlib.import_module(item.name)
            for _, candidate in inspect.getmembers(module, inspect.isclass):
                if (
                    candidate is not base_class
                    and issubclass(candidate, base_class)
                    and candidate.__module__ == module.__name__
                ):
                    result[item.name.rsplit(".", 1)[-1]] = candidate() if instantiate else candidate
                    break
        except Exception as exc:
            logger.warning("Failed to load package module '%s': %s", item.name, exc)
    return result


def scan_package_for_adapters(package: Any, registry_func: Callable[[str, Any], None]) -> None:
    """Discover every adapter callable in a package and register it.

    Adapter discovery is multi-load and therefore belongs beside plugin
    discovery, not the singular-provider resolver.
    """
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        full_module_name = f"{package.__name__}.{module_name}"
        try:
            module = importlib.import_module(full_module_name)
            adapter = getattr(module, "adapter", None)
            if callable(adapter):
                registry_func(module_name, adapter)
        except Exception as exc:
            logger.warning("Failed to load adapter module '%s': %s", full_module_name, exc)


def set_extension(family: str, instance: Any) -> None:
    """Injects or overrides an extension instance in the process registry."""
    with _registry_lock:
        if instance is None:
            _extension_registry.pop(family, None)
        else:
            _extension_registry[family] = instance


def get_registered_extension(family: str) -> Any | None:
    """Return a previously registered multi-load registry without resolving a provider."""
    with _registry_lock:
        return _extension_registry.get(family)


def reset_extensions(family: str | None = None) -> None:
    """Clears cached extension instance(s) from the process registry."""
    with _registry_lock:
        if family is not None:
            _extension_registry.pop(family, None)
        else:
            _extension_registry.clear()


__all__ = [
    "ENTRY_POINT_NAMESPACE",
    "discover_extension_entry_points",
    "discover_plugin_instances",
    "discover_declared_plugin_instances",
    "discover_classes_in_package",
    "scan_package_for_adapters",
    "resolve_extension",
    "get_registered_extension",
    "set_extension",
    "reset_extensions",
]
