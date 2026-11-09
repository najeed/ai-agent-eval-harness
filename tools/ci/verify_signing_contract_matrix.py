"""Require complete local signing evidence; never infer live KMS feature readiness."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "tests" / "acceptance" / "manifests" / "signing_contract_matrix.json"

TARGET_MODULES = (
    "tests/unit/core/test_digest_signature_contract.py",
    "tests/unit/core/test_signing_acceptance_matrix.py",
    "tests/unit/core/test_signing_input_policy_contract.py",
    "tests/acceptance/test_digest_signature_release_matrix.py",
)

FALLBACK_REQUIRED: dict[str, int] = {
    "test_bad_structured_response_cannot_publish_or_seal": 10,
    "test_cross_implementation_canonicalization_vectors": 4,
    "test_digest_signature_release_matrix": 22,
    "test_envelope_fields_match_unsigned_envelope": 1,
    "test_envelope_shape_is_strict_for_json_inputs": 7,
    "test_every_envelope_binding_is_enforced_even_with_a_genuine_signature": 18,
    "test_exact_certificate_projection_excludes_only_frozen_fields": 1,
    "test_external_resolver_cannot_change_the_expected_identity": 3,
    "test_external_resolver_policy_must_match_the_selected_public_anchor": 1,
    "test_external_trust_policy_restricts_valid_signatures": 5,
    "test_full_certification_preserves_envelopes_and_verifies_without_backend": 1,
    "test_hardware_failure_never_consults_available_local_key": 28,
    "test_invalid_or_oversized_signer_identity_never_reaches_remote": 2,
    "test_large_finalization_round_trip_preserves_and_verifies_envelope": 1,
    "test_large_payload_is_an_envelope_signature_with_independent_offline_verification": 1,
    "test_malformed_or_ambiguous_responses_do_not_downgrade": 13,
    "test_mutable_kms_alias_is_not_an_immutable_key_binding": 1,
    "test_noncanonical_payloads_cannot_claim_rfc8785": 4,
    "test_nonzero_base64_padding_bits_are_rejected_even_for_valid_signature_bytes": 1,
    "test_offline_process_reconstructs_frozen_projection": 4,
    "test_raw_backend_hex_whitespace_is_not_silently_normalized": 1,
    "test_raw_legacy_hex_signature_is_rejected": 1,
    "test_raw_signing_response_cannot_use_permissive_hex_whitespace": 1,
    "test_remote_outage_and_wrong_key_fail_without_local_fallback": 1,
    "test_resolve_policy_with_none_public_key": 1,
    "test_resolved_backend_outage_cannot_use_existing_local_private_key": 1,
    "test_signature_semantics_and_exact_field_types_are_not_inferred": 6,
    "test_strict_transport_json_rejects_ambiguous_or_unsupported_inputs": 11,
    "test_unsigned_envelope_requires_bytes_and_identity": 1,
    "test_validate_signing_response_valid_raw_hex": 1,
}


def load_required_matrix(manifest_path: Path | None = None) -> dict[str, int]:
    """Load required signing matrix case counts from manifest or fallback."""
    target = manifest_path or DEFAULT_MANIFEST
    if target.is_file():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "required_cases" in data:
                return dict(data["required_cases"])
        except (json.JSONDecodeError, OSError):
            pass
    return dict(FALLBACK_REQUIRED)


REQUIRED = load_required_matrix()


def sync_matrix(
    source_junit: Path | None = None,
    manifest_path: Path | None = None,
    target_modules: tuple[str, ...] = TARGET_MODULES,
) -> tuple[int, int]:
    """Synchronize the signing matrix manifest from JUnit XML or pytest collection."""
    observed: Counter[str] = Counter()
    target_manifest = manifest_path or DEFAULT_MANIFEST

    if source_junit and source_junit.is_file():
        root = ET.parse(source_junit).getroot()  # nosec B314
        for case in root.iter("testcase"):
            name = case.get("name", "")
            function = name.split("[", 1)[0]
            observed[function] += 1
    else:
        # Run pytest in collection-only mode across target modules
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", *target_modules, "--collect-only", "-q"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        for line in proc.stdout.splitlines():
            line = line.strip()
            if "::test_" in line:
                test_name = line.split("::")[-1]
                func_name = test_name.split("[", 1)[0]
                observed[func_name] += 1

    total_cases = sum(observed.values())
    manifest_content = {
        "profile": "agentv.signature.digest-envelope.v1",
        "total_cases": total_cases,
        "target_modules": list(target_modules),
        "required_cases": dict(sorted(observed.items())),
    }
    target_manifest.parent.mkdir(parents=True, exist_ok=True)
    target_manifest.write_text(json.dumps(manifest_content, indent=2) + "\n", encoding="utf-8")
    return len(observed), total_cases


def check_purity(
    manifest_path: Path | None = None,
    target_modules: tuple[str, ...] = TARGET_MODULES,
) -> list[str]:
    """Fast AST-level check verifying that on-disk test functions match the manifest."""
    manifest_funcs = set(load_required_matrix(manifest_path).keys())
    ast_funcs: set[str] = set()

    for rel_path in target_modules:
        file_path = REPO_ROOT / rel_path
        if not file_path.is_file():
            continue
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and node.name.startswith("test_"):
                    ast_funcs.add(node.name)
        except SyntaxError as err:
            return [f"SyntaxError parsing {rel_path}: {err}"]

    unregistered = sorted(ast_funcs - manifest_funcs)
    missing = sorted(manifest_funcs - ast_funcs)
    violations: list[str] = []
    if unregistered:
        violations.append(
            f"Unregistered signing contract test functions: {unregistered}. "
            "Run 'python tools/ci/verify_signing_contract_matrix.py --sync' to update manifest."
        )
    if missing:
        violations.append(
            f"Manifest expects missing test functions: {missing}. "
            "Run 'python tools/ci/verify_signing_contract_matrix.py --sync' to update manifest."
        )
    return violations


def verify(path: Path, manifest_path: Path | None = None) -> dict:
    required = load_required_matrix(manifest_path)
    root = ET.parse(path).getroot()  # nosec B314
    observed = Counter()
    names = set()
    for case in root.iter("testcase"):
        name = case.get("name", "")
        function = name.split("[", 1)[0]
        if function not in required:
            raise ValueError(f"Unexpected signing-matrix test: {name}")
        if name in names:
            raise ValueError(f"Duplicate signing-matrix test: {name}")
        names.add(name)
        if any(case.find(tag) is not None for tag in ("failure", "error", "skipped")):
            raise ValueError(f"Signing-matrix test did not pass: {name}")
        observed[function] += 1
    if dict(observed) != required:
        raise ValueError(f"Incomplete signing matrix: expected {required}, got {dict(observed)}")
    return {
        "profile": "agentv.signature.digest-envelope.v1",
        "core_local_evidence_verified": True,
        "passed_cases": len(names),
        "evidence_type": "local-and-transport-double",
        "live_kms_evidence_verified": False,
        "enterprise_adapter_verified": False,
        "large_payload_kms_feature_claim_ready": False,
        "release_approval": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "junit", type=Path, nargs="?", default=None, help="Path to JUnit XML report"
    )
    parser.add_argument("--output", type=Path, default=None, help="Output summary JSON file")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to signing contract matrix manifest JSON",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Synchronize manifest from JUnit XML or pytest collection",
    )
    parser.add_argument(
        "--check-purity",
        action="store_true",
        help="Perform fast AST check ensuring all test functions match manifest",
    )
    args = parser.parse_args()

    if args.check_purity:
        violations = check_purity(args.manifest)
        if violations:
            for violation in violations:
                print(f"::error::{violation}", file=sys.stderr)
            parser.exit(1, "Signing contract matrix purity check failed.\n")
        print("Signing contract matrix AST purity: 100% synchronized")
        return

    if args.sync:
        num_funcs, total_cases = sync_matrix(args.junit, args.manifest)
        print(
            f"Successfully synchronized {args.manifest}: "
            f"{total_cases} test cases across {num_funcs} functions."
        )
        return

    if not args.junit:
        parser.error(
            "Positional argument 'junit' is required when not using --sync or --check-purity."
        )
    if not args.output:
        parser.error("Argument '--output' is required for verification mode.")

    try:
        result = verify(args.junit, args.manifest)
    except (ValueError, OSError, ET.ParseError) as exc:
        parser.exit(1, f"Signing acceptance gate failed: {exc}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Core signing contract: {result['passed_cases']} passed; live KMS feature gate pending")


if __name__ == "__main__":
    main()
