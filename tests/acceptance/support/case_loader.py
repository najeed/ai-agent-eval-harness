"""
tests.acceptance.support.case_loader
Authoritative loader and schema validator for AgentV acceptance test cases and manifests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCHEMA_PATH = (
    REPO_ROOT / "tests" / "acceptance" / "corpus" / "schema" / "acceptance_case.schema.json"
)

_SCHEMA: dict[str, Any] | None = None


def get_acceptance_schema() -> dict[str, Any]:
    """Load and cache the canonical acceptance-case JSON schema."""
    global _SCHEMA
    if _SCHEMA is None:
        if not SCHEMA_PATH.exists():
            raise FileNotFoundError(f"Acceptance case schema not found: {SCHEMA_PATH}")
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            _SCHEMA = json.load(f)
    return _SCHEMA


def validate_acceptance_case(case_data: dict[str, Any], file_ref: str | Path = "") -> None:
    """Validate an acceptance case against the Draft-07 JSON schema."""
    schema = get_acceptance_schema()
    try:
        jsonschema.validate(instance=case_data, schema=schema)
    except jsonschema.ValidationError as err:
        loc = f" in {file_ref}" if file_ref else ""
        raise ValueError(f"Acceptance case schema validation failed{loc}: {err.message}") from err


def load_case(path: str | Path) -> dict[str, Any]:
    """Load, parse, and schema-validate a single acceptance test case."""
    resolved_path = Path(path).resolve()
    if not resolved_path.exists():
        raise FileNotFoundError(f"Acceptance case file not found: {resolved_path}")

    with open(resolved_path, encoding="utf-8") as f:
        if resolved_path.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(f)
        else:
            data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Expected dict in acceptance case {resolved_path}, got {type(data)}")

    validate_acceptance_case(data, resolved_path)
    data["_source_file"] = str(resolved_path)
    return data


def discover_corpus_cases(corpus_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """Discover and validate all acceptance cases in the corpus directory."""
    if corpus_dir is None:
        target_dir = REPO_ROOT / "tests" / "acceptance" / "corpus"
    else:
        target_dir = Path(corpus_dir).resolve()

    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for ext in ("*.yaml", "*.yml", "*.json"):
        for file_path in target_dir.rglob(ext):
            # Skip schema folder
            if "schema" in file_path.parts:
                continue
            case = load_case(file_path)
            case_id = case["id"]
            if case_id in seen_ids:
                raise ValueError(f"Duplicate acceptance case ID detected: {case_id} at {file_path}")
            seen_ids.add(case_id)
            cases.append(case)

    return sorted(cases, key=lambda c: c["id"])


def load_manifest(manifest_path: str | Path) -> dict[str, Any]:
    """Load an acceptance manifest and resolve its referenced acceptance cases."""
    resolved_manifest = Path(manifest_path).resolve()
    if not resolved_manifest.exists():
        raise FileNotFoundError(f"Manifest not found: {resolved_manifest}")

    with open(resolved_manifest, encoding="utf-8") as f:
        manifest_data = yaml.safe_load(f)

    if not isinstance(manifest_data, dict):
        raise ValueError(f"Expected dict in manifest {resolved_manifest}")

    resolved_cases: list[dict[str, Any]] = []
    for rel_or_abs in manifest_data.get("cases", []):
        case_p = Path(rel_or_abs)
        if not case_p.is_absolute():
            case_p = (REPO_ROOT / case_p).resolve()
        resolved_cases.append(load_case(case_p))

    manifest_data["loaded_cases"] = resolved_cases
    return manifest_data


__all__ = [
    "get_acceptance_schema",
    "validate_acceptance_case",
    "load_case",
    "discover_corpus_cases",
    "load_manifest",
]
