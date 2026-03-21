from __future__ import annotations

"""
loader.py

This module provides utilities for loading scenario and dataset files for the MultiAgentEval.
It supports loading scenario JSON files with schema validation, and dataset loading for CSV/JSONL.
"""

import csv
import json
from pathlib import Path
from typing import Dict, Callable, List, Optional, Any, Union
from jsonschema import validate, ValidationError  # type: ignore
from .trace_utils import load_events

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
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dataset.append(row)
    return dataset


@LoaderRegistry.register(".jsonl")
def load_jsonl(file_path: Path) -> List[Dict]:
    try:
        return load_events(file_path)
    except Exception as e:
        print(f"   [Loader] Error: Failed to load JSONL/JSON: {e}")
        return []


@LoaderRegistry.register(".json")
def load_single_scenario(file_path: Path) -> List[Dict]:
    """Loads a single scenario JSON file and returns it as a list."""
    return [load_scenario(str(file_path))]


def load_scenario(
    path: Union[str, Path],
) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Loads scenarios from a JSON/YAML file or a Benchmark URI (e.g., gaia://2023).
    """
    path_str = str(path)

    # 1. Handle Benchmark URIs
    if "://" in path_str:
        scheme, uri = path_str.split("://", 1)
        from .benchmarks import BENCHMARK_REGISTRY

        if scheme in BENCHMARK_REGISTRY:
            benchmark_class = BENCHMARK_REGISTRY[scheme]
            return benchmark_class.load(uri)
        else:
            print(f"      [Loader] Warning: Unknown benchmark scheme '{scheme}'")
            return []

    # 2. Handle File Paths
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Scenario file not found at {file_path}")

    with open(file_path, "r") as f:
        try:
            scenario_data = json.loads(f.read())
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(f"Error decoding JSON from {file_path}: {e.msg}", e.doc, e.pos)

    # 3. Resolve Relative Dataset Paths (Path Decoupling)
    if "dataset" in scenario_data and isinstance(scenario_data["dataset"], dict):
        ds_path = scenario_data["dataset"].get("path")
        if ds_path and (ds_path.startswith("./") or ds_path.startswith("../")):
            # Resolve relative to the scenario file's directory
            absolute_ds_path = (file_path.parent / ds_path).resolve()
            scenario_data["dataset"]["path"] = str(absolute_ds_path)
            print(f"      [Loader] Resolved relative dataset path: {ds_path} -> {absolute_ds_path}")

    # Note: validation is only for standard scenario files
    validate(instance=scenario_data, schema=_get_schema())

    # Inject path for traceability in repro scripts/reports
    scenario_data["path"] = path_str

    return scenario_data


def load_dataset(file_path: Union[str, Path], format_type: Optional[str] = None) -> List[Dict]:
    """Loads a dataset file or scenario(s) using the registered loaders."""
    # Handle Benchmark URIs before Path normalization
    if isinstance(file_path, str) and "://" in file_path:
        scenarios = load_scenario(file_path)
        return scenarios if isinstance(scenarios, list) else [scenarios]

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
