"""Compatibility exports for the canonical runtime discovery service.

Production discovery lives in :mod:`agentv_runtime.discovery`.  This module is
deliberately import-only so older integrations do not create a second registry
or a second project-scanning implementation.
"""

import inspect

from agentv_runtime.discovery import (
    discover_classes_in_package,
    discover_plugin_instances as discover_plugins_in_directory,
    scan_package_for_adapters,
)


def discover_classes_in_module(module, base_class: type, instantiate: bool = True):
    """Compatibility adapter; discovery implementation remains in Runtime."""

    return [
        candidate() if instantiate else candidate
        for _, candidate in inspect.getmembers(module, inspect.isclass)
        if candidate is not base_class
        and issubclass(candidate, base_class)
        and candidate.__module__ == module.__name__
    ]


__all__ = [
    "discover_plugins_in_directory",
    "discover_classes_in_module",
    "discover_classes_in_package",
    "scan_package_for_adapters",
]
