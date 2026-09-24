#!/usr/bin/env python3
"""
tools/ci/create_acceptance_attestation.py
Creates a cryptographically verifiable AcceptanceAttestation v1 binding:
source commit, wheel SHA-256, suite hash, manifest hash, oracle repository and SHA,
case-result root, and release gate decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def compute_case_result_root(results: list[dict[str, Any]]) -> str:
    """Computes deterministic Merkle-style root over ordered case results."""
    from agentv_runtime.canonical import canonical_json_dumps

    case_hashes = []
    for r in sorted(results, key=lambda x: str(x.get("case_id", ""))):
        cleaned = {k: v for k, v in r.items() if not str(k).startswith("_")}
        c_bytes = canonical_json_dumps(cleaned).encode("utf-8")
        case_hashes.append(hashlib.sha256(c_bytes).hexdigest())

    combined = ":".join(case_hashes).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def resolve_commit_sha(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    env_sha = os.environ.get("GITHUB_SHA")
    if env_sha:
        return env_sha
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
        return out
    except Exception:
        return "0000000000000000000000000000000000000000"


def create_attestation(
    summary_path: Path,
    manifest_path: Path,
    wheel_path: Path | None = None,
    source_commit: str | None = None,
    oracle_repo: str = "",
    oracle_sha: str = "",
    workflow_run_id: str = "",
) -> dict[str, Any]:
    with open(summary_path, encoding="utf-8") as f:
        summary = json.load(f)

    manifest_bytes = manifest_path.read_bytes()
    manifest_hash = compute_sha256(manifest_bytes)

    # Suite hash from loaded yaml content
    suite_data = yaml.safe_load(manifest_bytes)
    suite_bytes = json.dumps(suite_data, sort_keys=True).encode("utf-8")
    suite_hash = compute_sha256(suite_bytes)

    commit_sha = resolve_commit_sha(source_commit)
    wheel_sha = compute_sha256(wheel_path) if (wheel_path and wheel_path.exists()) else "none"

    raw_results = summary.get("results", [])
    case_root = compute_case_result_root(raw_results)

    failed_cases = int(summary.get("failed_cases", 0))
    gate_status = "PASSED" if (failed_cases == 0 and len(raw_results) > 0) else "FAILED"

    attestation: dict[str, Any] = {
        "attestation_version": "1.0",
        "source_commit": commit_sha,
        "wheel_sha256": wheel_sha,
        "suite_hash": suite_hash,
        "manifest_hash": manifest_hash,
        "oracle_repo": oracle_repo or os.environ.get("AGENTV_TESTER_REPOSITORY", "none"),
        "oracle_sha": oracle_sha or os.environ.get("AGENTV_TESTER_SHA", "none"),
        "case_result_root": case_root,
        "timestamp": datetime.now(UTC).isoformat(),
        "workflow_run_id": workflow_run_id or os.environ.get("GITHUB_RUN_ID", ""),
        "gate_status": gate_status,
    }

    if SCHEMA_PATH.exists():
        with open(SCHEMA_PATH, encoding="utf-8") as sf:
            schema = json.load(sf)
        jsonschema.validate(instance=attestation, schema=schema)

    return attestation


def main() -> int:
    parser = argparse.ArgumentParser(description="Create AcceptanceAttestation v1")
    parser.add_argument(
        "--summary",
        default="reports/acceptance/latest/acceptance-summary.json",
        help="Path to acceptance summary JSON",
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
        "--source-commit",
        default=None,
        help="Explicit git source commit SHA",
    )
    parser.add_argument(
        "--oracle-repo",
        default="",
        help="Independent oracle repository identifier",
    )
    parser.add_argument(
        "--oracle-sha",
        default="",
        help="Pinned immutable commit SHA for independent oracle",
    )
    parser.add_argument(
        "--output",
        default="reports/acceptance/latest/acceptance-attestation.json",
        help="Path to write the generated attestation JSON",
    )

    args = parser.parse_args()

    summary_p = Path(args.summary)
    if not summary_p.is_absolute():
        summary_p = (REPO_ROOT / summary_p).resolve()

    manifest_p = Path(args.manifest)
    if not manifest_p.is_absolute():
        manifest_p = (REPO_ROOT / manifest_p).resolve()

    wheel_p = None
    if args.wheel:
        wheel_p = Path(args.wheel)
        if not wheel_p.is_absolute():
            wheel_p = (REPO_ROOT / wheel_p).resolve()

    out_p = Path(args.output)
    if not out_p.is_absolute():
        out_p = (REPO_ROOT / out_p).resolve()

    attestation = create_attestation(
        summary_path=summary_p,
        manifest_path=manifest_p,
        wheel_path=wheel_p,
        source_commit=args.source_commit,
        oracle_repo=args.oracle_repo,
        oracle_sha=args.oracle_sha,
    )

    out_p.parent.mkdir(parents=True, exist_ok=True)
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(attestation, f, indent=2)

    print(f"[ACCEPTANCE ATTESTATION] Successfully wrote attestation to {out_p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
