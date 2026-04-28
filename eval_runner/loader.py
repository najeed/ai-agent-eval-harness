"""
loader.py

This module provides utilities for loading scenario and dataset files for the AgentV.
It supports loading scenario JSON files with schema validation, and dataset loading for CSV/JSONL.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jsonschema import ValidationError

from . import config
from .trace_utils import load_events
from .utils import normalize_uri

# --- UNIVERSAL IMMUTABLE REGISTRY (Industrial Purity v1.4.0) ---
_REGISTRY_CACHE = None
_SCENARIO_SCHEMA = None
_LAST_PROJECT_ROOT = None


def get_internal_spec_root() -> Path:
    """authoritatve spec root relative to the source code baseline."""
    return Path(__file__).parent.parent / "spec"


def get_spec_root() -> Path:
    """Dynamically resolves the specification root based on the PROJECT_ROOT."""
    return config.PROJECT_ROOT / "spec"


def reset_universal_registry():
    """Industrial helper for test environments to clear cached registry state."""
    global _REGISTRY_CACHE, _SCENARIO_SCHEMA, _LAST_PROJECT_ROOT
    _REGISTRY_CACHE = None
    _SCENARIO_SCHEMA = None
    _LAST_PROJECT_ROOT = None


def get_universal_registry():
    """
    Core industrial-grade registry for all forensic specifications.
    Pre-compiles internal baseline and project-specific overlays into an immutable collection.
    Complies with Guardrails v3.4 Section 1.6 (Environment Portability).
    """
    global _REGISTRY_CACHE, _LAST_PROJECT_ROOT

    # Industrial Multi-Tenancy Protection: Reset cache if project root changes
    current_root = config.PROJECT_ROOT.resolve()
    if _LAST_PROJECT_ROOT is not None and _LAST_PROJECT_ROOT != current_root:
        reset_universal_registry()

    if _REGISTRY_CACHE is not None:
        return _REGISTRY_CACHE

    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT7

    registry = Registry()

    # 1. Authoritative Internal Baseline (Code-Relative)
    internal_root = get_internal_spec_root()
    # 2. Dynamic Project Overlay (Environment-Relative)
    project_root = get_spec_root()

    roots_to_crawl = [internal_root]
    if project_root.exists() and project_root.resolve() != internal_root.resolve():
        roots_to_crawl.append(project_root)

    for root in roots_to_crawl:
        # Recursively index every JSON file (Root Schemas and Definitions) in the spec/ directory
        for json_path in root.glob("**/*.json"):
            try:
                with open(json_path, encoding="utf-8") as f:
                    json_data = json.load(f)

                # A. Physical URI (Legacy/Isolation support)
                file_uri = normalize_uri(json_path)

                # B. Logical URI (Guardrails v3.4 Section 1.6 - Identity Portability)
                rel_path = json_path.relative_to(root)
                logical_uri = f"https://agentvos.ai/spec/{rel_path.as_posix()}"

                # Anchor Logic: Authoritative Identity (Guardrails v3.4 Section 1.6)
                # We prioritize the Logical URI identity for absolute portability.
                if "$id" not in json_data:
                    json_data["$id"] = logical_uri

                # Ensure every resource has a specification (default to DRAFT7 for fragments)
                if "$schema" in json_data:
                    resource = Resource.from_contents(json_data)
                else:
                    resource = Resource.from_contents(json_data, default_specification=DRAFT7)

                # Double-Registration for total environment portability
                registry = registry.with_resource(file_uri, resource)
                registry = registry.with_resource(logical_uri, resource)

                # C. Finalize Anchor
                _LAST_PROJECT_ROOT = current_root

                # Optimization: Specifically index the parent for relative sibling resolution
                if json_path.name.endswith(".schema.json"):
                    base_uri = normalize_uri(json_path.parent) + "/"
                    registry = registry.with_resource(base_uri, resource)
            except Exception as e:
                # Critical Boot-Time Failure: Spec integrity is mandatory
                import sys

                sys.stderr.write(
                    f"   [Loader] CRITICAL: Failed to index resource {json_path}: {e}\n"
                )
                raise RuntimeError(
                    f"❌ [Loader] Specification Registry Corruption: {json_path} - {e}"
                ) from e

    _REGISTRY_CACHE = registry
    return _REGISTRY_CACHE


def _get_schema() -> dict:
    """Lazy-loads and caches the scenario JSON schema. Forensic: Logical resolution."""
    global _SCENARIO_SCHEMA
    if _SCENARIO_SCHEMA is None:
        # Prefer the internal baseline for platform logic
        schema_path = get_internal_spec_root() / "aes" / "aes.schema.json"
        with open(schema_path, encoding="utf-8") as f:
            _SCENARIO_SCHEMA = json.load(f)
    return _SCENARIO_SCHEMA


class LoaderRegistry:
    """Registry for data loaders."""

    _loaders: dict[str, Callable] = {}

    @classmethod
    def register(cls, extension: str):
        """Decorator to register a loader for a specific file extension."""

        def decorator(func: Callable):
            cls._loaders[extension.lower()] = func
            return func

        return decorator

    @classmethod
    def get(cls, extension: str) -> Callable | None:
        """Retrieves a loader for a specific extension."""
        return cls._loaders.get(extension.lower())


@LoaderRegistry.register(".csv")
def load_csv(file_path: Path) -> list[dict]:
    dataset = []
    with open(file_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dataset.append(row)
    return dataset


@LoaderRegistry.register(".jsonl")
def load_jsonl(file_path: Path) -> list[dict]:
    try:
        return load_events(file_path)
    except Exception as e:
        print(f"   [Loader] Error: Failed to load JSONL/JSON: {e}")
        return []


@LoaderRegistry.register(".json")
def load_single_scenario(file_path: Path) -> list[dict]:
    """Loads a single scenario JSON file and returns it as a list."""
    return [load_scenario(str(file_path))]


def _normalize_identity(scenario_data: dict, file_path: Path) -> dict:
    """
    Authoritative Identifier Resolution (AES v1.4.0 Compliance).
    Unifies identity across metadata blocks, legacy keys, and physical storage.
    """
    metadata = scenario_data.get("metadata", {})

    # 1. Authoritative Resolution (AES v1.4.0 Compliance)
    # The schema check ensures metadata.id exists.
    # Standardize the URI for validation
    identifier = metadata.get("id")

    # 2. Top-level Engine ID (Required for evaluation context and reporting)
    scenario_data["id"] = identifier

    # 3. Synchronize Metadata for downstream plugin compatibility
    if "id" not in metadata:
        metadata["id"] = identifier
    scenario_data["metadata"] = metadata

    # 4. Pure Architecture: No legacy fallbacks or debt.

    return scenario_data


def load_scenario(
    path: str | Path,
) -> dict[str, Any] | list[dict[str, Any]]:
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

    # 2. Handle Scenario IDs (Industrial Alias resolution AgentV v1.6.0)
    from .catalog import ScenarioCatalog

    catalog = ScenarioCatalog.get_instance()
    abs_path = catalog.get_absolute_path(path_str)

    if abs_path:
        file_path = abs_path
    else:
        # Fallback to direct file path
        file_path = Path(path)

    if not file_path.exists():
        msg = (
            f"Scenario not found: '{path}'.\n"
            f"   - If this is a Scenario ID, ensure the catalog is indexed (run 'agentv list').\n"
            "   - If this is a file, verify the project-relative path "
            "(e.g., 'industries/fin/...')."
        )
        raise FileNotFoundError(msg)

    with open(file_path) as f:
        try:
            scenario_data = json.loads(f.read())
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(  # noqa: B904
                f"Error decoding JSON from {file_path}: {e.msg}", e.doc, e.pos
            )

    # 3. Resolve Relative Dataset Paths (Path Decoupling)
    if "dataset" in scenario_data and isinstance(scenario_data["dataset"], dict):
        ds_path = scenario_data["dataset"].get("path")
        if ds_path and (ds_path.startswith("./") or ds_path.startswith("../")):
            # Resolve relative to the scenario file's directory
            absolute_ds_path = (file_path.parent / ds_path).resolve()
            scenario_data["dataset"]["path"] = str(absolute_ds_path)
            print(f"      [Loader] Resolved relative dataset path: {ds_path} -> {absolute_ds_path}")

    # Standard Workflow Check
    if "workflow" not in scenario_data:
        raise ValueError("Scenario missing required 'workflow' block (Unified Standard).")

    # Ensure 'workflow' is a dictionary
    if not isinstance(scenario_data["workflow"], dict):
        raise ValueError("Invalid 'workflow' block structure (must be a dictionary).")

    # --- V1.4 COMPLIANCE ENFORCEMENT ---
    # We no longer support legacy v1.2 or v1.3 signatures.
    aes_version = scenario_data.get("aes_version")
    if aes_version != 1.4:
        invalid_ver = aes_version or "missing"
        raise ValueError(
            f"Unsupported AES version: {invalid_ver}. "
            f"This harness requires v1.4.0 for Forensic Integrity compliance."
        )

    # Handle validation with the Universal Immutable Registry (No-Debt Standard)
    try:
        from jsonschema import ValidationError
        from jsonschema.validators import validator_for

        registry = get_universal_registry()
        schema = _get_schema()

        # Anchor Logic: Ensure the schema dict is associated with its canonical identity
        # The Registry provides all external $ref resolution without I/O side effects
        if "$id" not in schema:
            schema["$id"] = "https://agentvos.ai/spec/aes/aes.schema.json"

        validator_cls = validator_for(schema)
        validator = validator_cls(schema, registry=registry)
        validator.validate(instance=scenario_data)

    except ValidationError as e:
        print(f"   [Loader] Validation Error in {file_path}: {e.message}")
        raise

    # Inject path for traceability in repro scripts/reports
    scenario_data["path"] = path_str

    # --- FORENSIC IDENTITY HARDENING ---
    scenario_data = _normalize_identity(scenario_data, file_path)

    return scenario_data


def load_dataset(file_path: str | Path, format_type: str | None = None) -> list[dict]:
    """Loads a dataset file or scenario(s) using the registered loaders."""
    # Handle Benchmark URIs before Path normalization
    if isinstance(file_path, str) and "://" in file_path:
        scenarios = load_scenario(file_path)
        return scenarios if isinstance(scenarios, list) else [scenarios]

    # 1. Alias Resolution (AgentV v1.6.0)
    # Check if 'file_path' is an ID before path-ifying it
    if isinstance(file_path, str):
        from .catalog import ScenarioCatalog

        catalog = ScenarioCatalog.get_instance()
        abs_p = catalog.get_absolute_path(file_path)
        if abs_p:
            path_obj = abs_p
        else:
            path_obj = Path(file_path)
    else:
        path_obj = file_path

    if not path_obj.exists():
        msg = (
            f"Dataset or Path not found: '{file_path}'.\n"
            f"   - If this is a Scenario ID, ensure the catalog is indexed (run 'agentv list').\n"
            f"   - If this is a file, verify the project-relative path."
        )
        raise FileNotFoundError(msg)

    # Handle Directory
    if path_obj.is_dir():
        all_scenarios = []
        for p in path_obj.glob("**/*.json"):
            try:
                all_scenarios.extend(load_single_scenario(p))
            except ValidationError as e:
                print(f"      [Loader] Validation Error in {p}: {e.message}")
                continue
            except Exception as e:
                print(f"      [Loader] unexpected Error in {p}: {e}")
                continue
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
