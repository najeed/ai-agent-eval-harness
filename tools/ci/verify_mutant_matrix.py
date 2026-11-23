"""
Static AST referential integrity verifier and synchronizer
for the Mutant-to-Test Preserved Matrix.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
else:
    sys.path.remove(str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_MANIFEST = REPO_ROOT / "tests" / "acceptance" / "manifests" / "mutant_killer_matrix.json"


def _declared_test_functions(file_path: Path) -> set[str]:
    """Extract all test function names and class::method test names from a test file."""
    if not file_path.is_file():
        return set()
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test_"
        ):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(
                    item, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and item.name.startswith("test_"):
                    names.add(item.name)
                    names.add(f"{node.name}::{item.name}")
    return names


def check_integrity(
    manifest_path: Path | None = None,
) -> tuple[int, list[str]]:
    """
    Statically verify referential integrity of the mutant-to-test preserved matrix.

    Returns (violation_count, list_of_error_strings).
    Execution takes ~25ms with zero test executions.
    """
    target = manifest_path or DEFAULT_MANIFEST
    if not target.is_file():
        return 1, [f"Mutant killer matrix manifest not found at: {target}"]

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        return 1, [f"Manifest is not valid JSON: {err}"]

    if not isinstance(data, dict):
        return 1, ["Manifest root must be a JSON object."]

    mutants = data.get("mutants")
    scopes = data.get("scopes")
    if not isinstance(mutants, dict) or not isinstance(scopes, dict):
        return 1, ["Manifest must contain 'mutants' and 'scopes' dictionaries."]

    # Cache discovered test names per file to avoid redundant AST parses
    file_tests_cache: dict[str, set[str]] = {}
    violations: list[str] = []

    def validate_test_ref(location: str, record: dict) -> None:
        if not isinstance(record, dict):
            violations.append(f"{location}: entry must be a dictionary.")
            return
        test_file = record.get("test_file")
        test_name = record.get("test_name")
        if not test_file or not isinstance(test_file, str):
            violations.append(f"{location}: missing or invalid 'test_file'.")
            return
        if not test_name or not isinstance(test_name, str):
            violations.append(f"{location}: missing or invalid 'test_name'.")
            return

        norm_file = test_file.replace("\\", "/")
        full_file_path = REPO_ROOT / norm_file
        if not full_file_path.is_file():
            violations.append(f"{location}: referenced test file does not exist: {norm_file}")
            return

        if norm_file not in file_tests_cache:
            file_tests_cache[norm_file] = _declared_test_functions(full_file_path)

        declared = file_tests_cache[norm_file]
        base_test_name = test_name.split("[")[0]
        if base_test_name not in declared and test_name not in declared:
            violations.append(f"{location}: test function '{test_name}' not found in {norm_file}.")

    # Validate all exact mutant entries
    for mutant_key, record in mutants.items():
        validate_test_ref(f"mutants[{mutant_key}]", record)

    # Validate all scope fallback entries
    for scope_key, record in scopes.items():
        validate_test_ref(f"scopes[{scope_key}]", record)

    # Validate that critical targets from run_mutation_tests have scope targets
    from tools.ci.run_mutation_tests import CRITICAL_MUTATION_TARGETS

    for target_config in CRITICAL_MUTATION_TARGETS:
        try:
            rel_mod = target_config.path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        except ValueError:
            rel_mod = target_config.path.name
        for sc in target_config.scopes:
            scope_key = f"{rel_mod}::{sc}"
            if scope_key not in scopes:
                violations.append(
                    f"Missing scope target in matrix for critical boundary: {scope_key}"
                )

    return len(violations), violations


def sync_matrix(
    manifest_path: Path | None = None,
) -> tuple[int, int, int]:
    """
    Synchronize matrix by pruning dead test references and seeding missing scope targets.

    Returns (pruned_mutants, pruned_scopes, seeded_scopes).
    """
    target = manifest_path or DEFAULT_MANIFEST
    from tools.ci.run_mutation_tests import (
        CRITICAL_MUTATION_TARGETS,
        MUTANT_MATRIX_PROFILE,
        MUTANT_MATRIX_VERSION,
        _map_test_names_to_files,
    )

    data: dict = {}
    if target.is_file():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}

    mutants: dict[str, dict[str, str]] = data.get("mutants", {})
    scopes: dict[str, dict[str, str]] = data.get("scopes", {})

    file_tests_cache: dict[str, set[str]] = {}

    def is_valid_ref(record: dict) -> bool:
        if not isinstance(record, dict):
            return False
        test_file = record.get("test_file")
        test_name = record.get("test_name")
        if not test_file or not test_name:
            return False
        norm_file = test_file.replace("\\", "/")
        full_file_path = REPO_ROOT / norm_file
        if not full_file_path.is_file():
            return False
        if norm_file not in file_tests_cache:
            file_tests_cache[norm_file] = _declared_test_functions(full_file_path)
        base_test_name = test_name.split("[")[0]
        return (
            base_test_name in file_tests_cache[norm_file]
            or test_name in file_tests_cache[norm_file]
        )

    # 1. Prune stale mutants
    initial_mutants_count = len(mutants)
    valid_mutants = {k: v for k, v in mutants.items() if is_valid_ref(v)}
    pruned_mutants = initial_mutants_count - len(valid_mutants)

    # 2. Prune stale scopes
    initial_scopes_count = len(scopes)
    valid_scopes = {k: v for k, v in scopes.items() if is_valid_ref(v)}
    pruned_scopes = initial_scopes_count - len(valid_scopes)

    # 3. Seed missing scopes from CRITICAL_MUTATION_TARGETS
    seeded_scopes = 0
    for target_config in CRITICAL_MUTATION_TARGETS:
        try:
            rel_mod = target_config.path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        except ValueError:
            rel_mod = target_config.path.name
        test_map = _map_test_names_to_files(list(target_config.tests))
        for scope, test_names in (target_config.scope_test_names or {}).items():
            scope_key = f"{rel_mod}::{scope}"
            if scope_key not in valid_scopes and test_names:
                first_test = test_names[0]
                test_file = test_map.get(first_test, "")
                if test_file:
                    valid_scopes[scope_key] = {
                        "test_file": test_file,
                        "test_name": first_test,
                        "nodeid": f"{test_file}::{first_test}",
                    }
                    seeded_scopes += 1

    payload = {
        "profile": MUTANT_MATRIX_PROFILE,
        "version": MUTANT_MATRIX_VERSION,
        "total_mutants": len(valid_mutants),
        "total_scopes": len(valid_scopes),
        "mutants": valid_mutants,
        "scopes": valid_scopes,
    }

    target.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target.with_suffix(".tmp")
    temp_target.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
    temp_target.replace(target)

    return pruned_mutants, pruned_scopes, seeded_scopes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify and synchronize the Mutant-to-Test Preserved Matrix."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"Path to mutant killer matrix JSON (default: {DEFAULT_MANIFEST}).",
    )
    parser.add_argument(
        "--check-integrity",
        action="store_true",
        help="Statically verify referential integrity without executing tests (pre-commit mode).",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Synchronize matrix: prune stale tests and seed missing scope targets.",
    )

    args = parser.parse_args(argv)

    if args.sync:
        pruned_m, pruned_s, seeded_s = sync_matrix(args.manifest)
        print(
            f"[Mutant Matrix Synced] Pruned {pruned_m} dead mutant mappings, "
            f"pruned {pruned_s} stale scopes, seeded {seeded_s} scope "
            f"targets in {args.manifest.name}."
        )

    if args.check_integrity or not args.sync:
        count, violations = check_integrity(args.manifest)
        if count > 0:
            print(
                f"[FAIL] Mutant matrix integrity check failed with {count} violation(s):",
                file=sys.stderr,
            )
            for v in violations:
                print(f"  • {v}", file=sys.stderr)
            print(
                "\nRun 'python tools/ci/verify_mutant_matrix.py --sync' "
                "to automatically synchronize.",
                file=sys.stderr,
            )
            return 1
        print(f"[OK] Mutant matrix integrity verified cleanly ({args.manifest.name}).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
