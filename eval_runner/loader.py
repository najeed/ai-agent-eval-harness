"""
loader.py

This module provides utilities for loading scenario and dataset files for the AI Agent Evaluation Harness.
It supports loading scenario JSON files with schema validation, and dataset loading for CSV/JSONL.
"""

import csv
import json
from pathlib import Path
from typing import Dict, Callable, List, Optional, Any, Union
from jsonschema import validate, ValidationError # type: ignore

# Load the schema once at module level
_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "scenario.schema.json"
_SCENARIO_SCHEMA = None


def _get_schema() -> dict:
    """Lazy-loads and caches the scenario JSON schema."""
    global _SCENARIO_SCHEMA
    if _SCENARIO_SCHEMA is None:
        with open(_SCHEMA_PATH, "r") as f:
            _SCENARIO_SCHEMA = json.loads(f.read())
    return _SCENARIO_SCHEMA


class LoaderRegistry:
    """Registry for data loaders."""
    _loaders: Dict[str, Callable] = {}

    @classmethod
    def register(cls, extension: str):
        """Decorator to register a loader for a specific file extension."""
        def decorator(func: Callable):
            cls._loaders[extension.lower()] = func
            return func
        return decorator

    @classmethod
    def get(cls, extension: str) -> Optional[Callable]:
        """Retrieves a loader for a specific extension."""
        return cls._loaders.get(extension.lower())


@LoaderRegistry.register(".csv")
def load_csv(file_path: Path) -> List[Dict]:
    dataset = []
    with open(file_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            dataset.append(row)
    return dataset


@LoaderRegistry.register(".jsonl")
def load_jsonl(file_path: Path) -> List[Dict]:
    dataset = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                dataset.append(json.loads(line))
    return dataset


@LoaderRegistry.register(".json")
def load_single_scenario(file_path: Path) -> List[Dict]:
    """Loads a single scenario JSON file and returns it as a list."""
    return [load_scenario(file_path)]


def load_scenario(file_path: Path) -> dict:
    """Loads and validates a scenario JSON file."""
    if not file_path.exists():
        raise FileNotFoundError(f"Scenario file not found at {file_path}")

    with open(file_path, "r") as f:
        try:
            scenario_data = json.loads(f.read())
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(
                f"Error decoding JSON from {file_path}: {e.msg}", e.doc, e.pos
            )

    validate(instance=scenario_data, schema=_get_schema())
    return scenario_data


def load_dataset(file_path: Union[str, Path], format_type: Optional[str] = None) -> List[Dict]:
    """Loads a dataset file or scenario(s) using the registered loaders."""
    path_obj = Path(file_path) if isinstance(file_path, str) else file_path

    if not path_obj.exists():
        raise FileNotFoundError(f"Path not found: {path_obj}")

    # Handle Directory
    if path_obj.is_dir():
        all_scenarios = []
        for p in path_obj.glob("**/*.json"):
            try:
                all_scenarios.extend(load_single_scenario(p))
            except Exception as e:
                print(f"   [Loader] Warning: Failed to load scenario {p}: {e}")
        return all_scenarios

    # Handle Single File
    extension = format_type if format_type else path_obj.suffix
    if extension and not extension.startswith("."):
        extension = f".{extension}"

    if not extension:
        print(f"   [Loader] Warning: Could not determine format for {path_obj}")
        return []

    loader_func = LoaderRegistry.get(extension)
    if loader_func is not None:
        return loader_func(path_obj)

    print(f"   [Loader] Warning: Unsupported format {extension} for {path_obj}")
    return []
