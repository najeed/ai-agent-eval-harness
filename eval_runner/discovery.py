"""
discovery.py

Centralized discovery logic for plugins, adapters, and providers.
Enables "Zero-Touch" extensibility by scanning standard directories.
"""

import os
import importlib
import pkgutil
import inspect
from pathlib import Path
from typing import List, Type, Any, Dict

def discover_classes_in_module(module, base_class: Type, instantiate: bool = True) -> List[Any]:
    """Finds all classes in a module that inherit from a base class."""
    found = []
    for name, obj in inspect.getmembers(module):
        if (
            inspect.isclass(obj)
            and issubclass(obj, base_class)
            and obj is not base_class
            and obj.__module__ == module.__name__
        ):
            found.append(obj() if instantiate else obj)
    return found

def discover_plugins_in_directory(directory: Path, base_class: Type, package_prefix: str = "") -> List[Any]:
    """
    Scans a directory for .py files and attempts to load classes inheriting from base_class.
    """
    plugins = []
    if not directory.exists() or not directory.is_dir():
        return plugins

    for file_path in directory.glob("*.py"):
        if file_path.name == "__init__.py":
            continue
        
        module_name = file_path.stem
        if package_prefix:
            full_module_name = f"{package_prefix}.{module_name}"
        else:
            full_module_name = module_name

        try:
            module = importlib.import_module(full_module_name)
            plugins.extend(discover_classes_in_module(module, base_class))
        except Exception as e:
            # Prevent engine crash but log the error for visibility
            print(f"   [Discovery] Warning: Failed to load plugin '{full_module_name}': {e}")
            pass
            
    return plugins

def discover_classes_in_package(package, base_class: Type, instantiate: bool = False, recursive: bool = True) -> Dict[str, Any]:
    """
    Scans a package for submodules and returns a dictionary mapping module stems to their discovered classes.
    """
    results = {}
    package_path = package.__path__
    package_name = package.__name__
    
    # pkgutil.walk_packages allows recursive traversal
    walker = pkgutil.walk_packages(package_path, f"{package_name}.") if recursive else pkgutil.iter_modules(package_path, f"{package_name}.")
    
    for info in walker:
        try:
            full_module_name = info.name
            module_stem = full_module_name.split(".")[-1]
            
            module = importlib.import_module(full_module_name)
            classes = discover_classes_in_module(module, base_class, instantiate=instantiate)
            if classes:
                # Store by stem (e.g. 'demographics')
                results[module_stem] = classes[0]
        except Exception as e:
            print(f"   [Discovery] Warning: Failed to load module '{full_module_name}' in package: {e}")
            pass
    return results

def scan_package_for_adapters(package, registry_func):
    """
    Scans a package for submodules and registers their 'adapter' function.
    """
    package_path = package.__path__
    package_name = package.__name__
    
    for _, module_name, _ in pkgutil.iter_modules(package_path):
        try:
            full_module_name = f"{package_name}.{module_name}"
            module = importlib.import_module(full_module_name)
            
            if hasattr(module, "adapter") and callable(module.adapter):
                registry_func(module_name, module.adapter)
        except Exception as e:
            print(f"   [Discovery] Warning: Failed to load adapter module '{full_module_name}': {e}")
            pass
