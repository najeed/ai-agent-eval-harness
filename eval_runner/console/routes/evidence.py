"""
eval_runner/console/routes/evidence.py
Evidence & Verification Package Exporter Blueprint.
Produces immutable, single-file .agentv-package.json verification packages
conforming to NIST 2026 AI auditability and reproducible evaluation specifications.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, jsonify, request

from eval_runner import config
from eval_runner.console.auth_manager import require_permission
from eval_runner.console.routes.runs import resolve_trace_path
from eval_runner.utils import is_path_safe

logger = logging.getLogger(__name__)

evidence_bp = Blueprint("evidence", __name__)


def compute_sha3_digest(content: bytes | str) -> str:
    """Compute deterministic SHA3-256 digest."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return f"sha3_256:{hashlib.sha3_256(content).hexdigest()}"


def build_verification_package(run_id: str) -> dict[str, Any] | None:
    """
    Constructs an immutable VerificationPackage bundling scenario, configuration,
    runtime events, verdicts, cryptographic proofs, and content-addressed hashes.
    """
    runs_dir = Path(config.RUN_LOG_DIR)
    reports_dir = Path(config.REPORTS_DIR)

    trace_path = resolve_trace_path(run_id)
    if not trace_path or not trace_path.exists():
        return None

    # Load trace events
    events: list[dict[str, Any]] = []
    scenario_resolved: dict[str, Any] = {}
    manifest_data: dict[str, Any] = {}

    vault_dir = runs_dir / run_id
    if vault_dir.is_dir():
        scen_file = vault_dir / "scenario_resolved.json"
        if scen_file.exists() and is_path_safe(str(scen_file), str(runs_dir)):
            try:
                scenario_resolved = json.loads(scen_file.read_text(encoding="utf-8"))
            except Exception as err:
                logger.debug("Failed reading scenario_resolved.json for %s: %s", run_id, err)

        manifest_file = vault_dir / "run_manifest.json"
        if manifest_file.exists() and is_path_safe(str(manifest_file), str(runs_dir)):
            try:
                manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
            except Exception as err:
                logger.debug("Failed reading run_manifest.json for %s: %s", run_id, err)

    raw_trace_bytes = trace_path.read_bytes()
    trace_hash = compute_sha3_digest(raw_trace_bytes)

    for line in raw_trace_bytes.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                ev = json.loads(line)
                events.append(ev)
            except Exception as err:
                logger.debug("Skipping unparseable trace event line: %s", err)
                continue

    # Extract verdicts and run status
    run_end_event = next((e for e in reversed(events) if e.get("event") == "run_end"), {})
    data_block = run_end_event.get("data", {})

    execution_status = data_block.get("status", "EXECUTION_COMPLETED")
    verified_outcome = (
        "VERIFIED"
        if data_block.get("passed", False) or data_block.get("verified", False)
        else "NOT_VERIFIED"
    )
    if any(e.get("event") == "policy_violation" for e in events):
        verified_outcome = "POLICY_BREACH"

    # Certificate & signatures
    cert_data: dict[str, Any] = {}
    cert_path = reports_dir / "certificates" / f"{run_id}_certificate.json"
    if not cert_path.exists() and vault_dir.is_dir():
        cert_path = vault_dir / f"{run_id}_certificate.json"

    if cert_path.exists() and is_path_safe(
        str(cert_path), str(reports_dir) if "reports" in str(cert_path) else str(runs_dir)
    ):
        try:
            cert_data = json.loads(cert_path.read_text(encoding="utf-8"))
        except Exception as err:
            logger.debug("Failed reading certificate for %s: %s", run_id, err)

    signatures = cert_data.get("signatures", cert_data.get("provenance_chain", []))

    # Authoritative Verdict Determination:
    # 1. Policy breach takes absolute precedence
    # 2. To claim VERIFIED, execution must have passed AND have cryptographic signatures
    # 3. Passed without cryptographic signatures is UNVERIFIED
    # 4. Otherwise NOT_VERIFIED
    if any(e.get("event") == "policy_violation" for e in events):
        verified_outcome = "POLICY_BREACH"
    elif data_block.get("passed", False) or data_block.get("verified", False):
        verified_outcome = "VERIFIED" if len(signatures) > 0 else "UNVERIFIED"
    else:
        verified_outcome = "NOT_VERIFIED"

    # Score calculation from authentic assertions
    assertions = data_block.get("assertions", [])
    if assertions:
        passed_count = sum(1 for a in assertions if a.get("passed", False))
        score = passed_count / len(assertions)
    elif "score" in data_block:
        score = float(data_block["score"])
    elif verified_outcome == "VERIFIED":
        score = 1.0
    else:
        score = 0.0

    # Deterministic canonical core (excluding envelope timestamps)
    canonical_payload = {
        "format": "agentv_verification_package",
        "package_version": "2.0.0",
        "run_id": run_id,
        "tenant_id": manifest_data.get("tenant_id", "default-tenant"),
        "workspace_id": manifest_data.get("workspace_id", "default-workspace"),
        "manifest": manifest_data,
        "scenario": scenario_resolved,
        "verdict": {
            "execution_status": execution_status,
            "verified_outcome": verified_outcome,
            "duration_seconds": data_block.get("duration", 0),
            "score": score,
        },
        "evidence_manifest": {
            "trace_hash": trace_hash,
            "total_events": len(events),
            "assertions_evaluated": len(assertions),
            "artifacts": [
                {"name": "run.jsonl", "hash": trace_hash, "type": "trace_events"},
            ],
        },
        "signatures": signatures,
    }

    # Deterministic package hash over canonical representation
    serialized_canonical = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))
    package_hash = compute_sha3_digest(serialized_canonical)

    return {
        **canonical_payload,
        "package_hash": package_hash,
        "package_created_at": datetime.now(UTC).isoformat(),
    }


@evidence_bp.route("/v1/evidence/packages/<run_id>", methods=["GET"])
@require_permission("runs:read")
def get_verification_package(run_id: str):
    """Serve or export immutable .agentv-package.json Verification Package."""
    package = build_verification_package(run_id)
    if not package:
        return jsonify({"error": "Verification package not found for run", "run_id": run_id}), 404

    as_download = request.args.get("download", "false").lower() == "true"
    if as_download:
        payload = json.dumps(package, indent=2)
        return Response(
            payload,
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={run_id}.agentv-package.json"},
        )

    return jsonify(package)


@evidence_bp.route("/v1/evidence/packages", methods=["GET"])
@require_permission("runs:read")
def list_verification_packages():
    """List summary records of all available verification packages."""
    runs_dir = Path(config.RUN_LOG_DIR)
    if not runs_dir.exists():
        return jsonify({"packages": []})

    packages_summary = []
    for path in runs_dir.iterdir():
        if path.is_dir() and path.name.startswith("run-"):
            rid = path.name
            cert_exists = (path / f"{rid}_certificate.json").exists()
            manifest_exists = (path / "run_manifest.json").exists()
            packages_summary.append(
                {
                    "run_id": rid,
                    "has_certificate": cert_exists,
                    "has_manifest": manifest_exists,
                    "package_url": f"/api/v1/evidence/packages/{rid}",
                    "download_url": f"/api/v1/evidence/packages/{rid}?download=true",
                }
            )

    return jsonify({"packages": packages_summary})
