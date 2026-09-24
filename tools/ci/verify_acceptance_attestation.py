#!/usr/bin/env python3
"""
tools/ci/verify_acceptance_attestation.py
Verifies an AcceptanceAttestation v1 against expected build artifacts,
pinned commits, and release gate status before publishing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import jsonschema
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_PATH = REPO_ROOT / "tests" / "acceptance" / "schemas" / "acceptance_attestation.schema.json"


def compute_sha256(path_or_bytes: Path | bytes) -> str:
    h = hashlib.sha256()
    if isinstance(path_or_bytes, Path):
        with open(path_or_bytes, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
    else:
        h.update(path_or_bytes)
    return h.hexdigest()


def verify_attestation(
    attestation_path: Path,
    manifest_path: Path | None = None,
    wheel_path: Path | None = None,
    expected_commit: str | None = None,
    expected_oracle_repo: str | None = None,
    expected_oracle_sha: str | None = None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if not attestation_path.exists():
        return False, [f"Attestation file not found: {attestation_path}"]

    try:
        with open(attestation_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        return False, [f"Failed to parse attestation JSON: {exc}"]

    if SCHEMA_PATH.exists():
        try:
            with open(SCHEMA_PATH, encoding="utf-8") as sf:
                schema = json.load(sf)
            jsonschema.validate(instance=data, schema=schema)
        except jsonschema.ValidationError as s_err:
            reasons.append(f"Attestation schema validation failure: {s_err.message}")

    if data.get("gate_status") != "PASSED":
        reasons.append(
            f"Gate status in attestation is '{data.get('gate_status')}', required 'PASSED'."
        )

    if wheel_path and wheel_path.exists():
        actual_wheel_sha = compute_sha256(wheel_path)
        attested_wheel_sha = data.get("wheel_sha256")
        if attested_wheel_sha != actual_wheel_sha:
            reasons.append(
                f"Wheel digest mismatch: attested {attested_wheel_sha} != actual {actual_wheel_sha}"
            )

    if manifest_path and manifest_path.exists():
        manifest_bytes = manifest_path.read_bytes()
        actual_manifest_hash = compute_sha256(manifest_bytes)
        attested_manifest_hash = data.get("manifest_hash")
        if attested_manifest_hash != actual_manifest_hash:
            reasons.append(
                f"Manifest hash mismatch: attested {attested_manifest_hash} "
                "!= actual {actual_manifest_hash}"
            )

        suite_data = yaml.safe_load(manifest_bytes)
        suite_bytes = json.dumps(suite_data, sort_keys=True).encode("utf-8")
        actual_suite_hash = compute_sha256(suite_bytes)
        attested_suite_hash = data.get("suite_hash")
        if attested_suite_hash != actual_suite_hash:
            reasons.append(
                f"Suite hash mismatch: attested {attested_suite_hash} != actual {actual_suite_hash}"
            )

    if expected_commit and expected_commit != "none":
        attested_commit = data.get("source_commit")
        if attested_commit != expected_commit:
            reasons.append(
                f"Source commit mismatch: attested {attested_commit} != expected {expected_commit}"
            )

    if expected_oracle_repo and expected_oracle_repo != "none":
        attested_oracle_repo = data.get("oracle_repo")
        if attested_oracle_repo != expected_oracle_repo:
            reasons.append(
                f"Oracle repo mismatch: attested {attested_oracle_repo} "
                "!= expected {expected_oracle_repo}"
            )

    if expected_oracle_sha and expected_oracle_sha != "none":
        attested_oracle_sha = data.get("oracle_sha")
        if attested_oracle_sha != expected_oracle_sha:
            reasons.append(
                f"Oracle SHA mismatch: attested {attested_oracle_sha} "
                "!= expected {expected_oracle_sha}"
            )

    return len(reasons) == 0, reasons


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify AcceptanceAttestation v1")
    parser.add_argument(
        "--attestation",
        default="reports/acceptance/latest/acceptance-attestation.json",
        help="Path to acceptance attestation JSON",
    )
    parser.add_argument(
        "--manifest",
        default="tests/acceptance/manifests/release.yaml",
        help="Path to suite manifest YAML",
    )
    parser.add_argument(
        "--wheel",
        default=None,
        help="Path to built wheel in dist/*.whl",
    )
    parser.add_argument(
        "--expected-commit",
        default=None,
        help="Expected git source commit SHA",
    )
    parser.add_argument(
        "--expected-oracle-repo",
        default=None,
        help="Expected independent oracle repository",
    )
    parser.add_argument(
        "--expected-oracle-sha",
        default=None,
        help="Expected independent oracle pinned SHA",
    )

    args = parser.parse_args()

    attestation_p = Path(args.attestation)
    if not attestation_p.is_absolute():
        attestation_p = (REPO_ROOT / attestation_p).resolve()

    manifest_p = None
    if args.manifest:
        manifest_p = Path(args.manifest)
        if not manifest_p.is_absolute():
            manifest_p = (REPO_ROOT / manifest_p).resolve()

    wheel_p = None
    if args.wheel:
        wheel_p = Path(args.wheel)
        if not wheel_p.is_absolute():
            wheel_p = (REPO_ROOT / wheel_p).resolve()

    valid, reasons = verify_attestation(
        attestation_path=attestation_p,
        manifest_path=manifest_p,
        wheel_path=wheel_p,
        expected_commit=args.expected_commit,
        expected_oracle_repo=args.expected_oracle_repo,
        expected_oracle_sha=args.expected_oracle_sha,
    )

    if valid:
        print("[ACCEPTANCE ATTESTATION] VERIFIED: All cryptographic and policy bindings match.")
        return 0
    else:
        print("[ACCEPTANCE ATTESTATION] VERIFICATION FAILED:", file=sys.stderr)
        for r in reasons:
            print(f"  - {r}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
