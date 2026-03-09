"""
loader.py

This module provides utilities for loading scenario and dataset files for the AI Agent Evaluation Harness.
It supports loading scenario JSON files with schema validation, and dataset loading for CSV/JSONL.

Typical usage example:
    from eval_runner import loader
    scenario = loader.load_scenario(Path('path/to/scenario.json'))
"""
# eval-runner/loader.py

import csv
import json
from pathlib import Path
from jsonschema import validate, ValidationError

# Load the schema once at module level
_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "scenario.schema.json"
_SCENARIO_SCHEMA = None


def _get_schema() -> dict:
    """Lazy-loads and caches the scenario JSON schema."""
    global _SCENARIO_SCHEMA
    if _SCENARIO_SCHEMA is None:
        with open(_SCHEMA_PATH, "r") as f:
            _SCENARIO_SCHEMA = json.load(f)
    return _SCENARIO_SCHEMA


from typing import Dict, Callable, List

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
    def get(cls, extension: str) -> Callable:
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


def load_scenario(file_path: Path) -> dict:
    """Loads and validates a scenario JSON file."""
    if not file_path.exists():
        raise FileNotFoundError(f"Scenario file not found at {file_path}")

    with open(file_path, "r") as f:
        try:
            scenario_data = json.load(f)
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(
                f"Error decoding JSON from {file_path}: {e.msg}", e.doc, e.pos
            )

    validate(instance=scenario_data, schema=_get_schema())
    return scenario_data


def load_dataset(file_path: Path, format_type: str = None) -> List[Dict]:
    """Loads a dataset file using the registered loaders."""
    if not file_path.exists():
        raise FileNotFoundError(f"Dataset file not found at {file_path}")

    # Use explicit format_type if provided, else fall back to file extension
    ext = format_type if format_type else file_path.suffix
    if not ext.startswith("."):
        ext = f".{ext}"

    loader_func = LoaderRegistry.get(ext)
    if loader_func:
        return loader_func(file_path)

    print(f"   [Loader] Warning: Unsupported dataset format {ext}")
    return []
