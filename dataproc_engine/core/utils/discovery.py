"""
discovery.py

Internal discovery logic for the Dataproc Engine.
Enables "Zero-Touch" extensibility by scanning standard directories.
"""

import importlib
import pkgutil
import inspect
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
            # Prevent engine crash but log the error for visibility (Internal Utility Version)
            import logging
            logging.getLogger("dataproc_discovery").warning(f"Failed to load module '{full_module_name}' in package: {e}")
            pass
    return results
