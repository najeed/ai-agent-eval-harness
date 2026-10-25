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
from typing import Any

from flask import Blueprint, Response, jsonify, request

from agentv_runtime.manifest import resolve_artifact_scope
from agentv_runtime.versions import VERIFICATION_PACKAGE_VERSION
from eval_runner.console.auth_manager import active_runtime_context, require_permission
from eval_runner.console.routes.runs import _active_run_store, _run_is_in_active_context

logger = logging.getLogger(__name__)

evidence_bp = Blueprint("evidence", __name__)


def compute_sha3_digest(content: bytes | str) -> str:
    """Compute deterministic SHA3-256 digest."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return f"sha3_256:{hashlib.sha3_256(content).hexdigest()}"


def build_verification_package(
    run_id: str, *, run_store: Any, context: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """
    Constructs an immutable VerificationPackage bundling scenario, configuration,
    runtime events, verdicts, cryptographic proofs, and content-addressed hashes.
    """
    run = run_store.get_run(run_id, context=context)
    raw_trace_bytes = run_store.get_trace_bytes(run_id, context=context)
    try:
        manifest_data = run_store.get_manifest(run_id, context=context) or {}
    except Exception:
        manifest_data = {}
    if run is None or raw_trace_bytes is None:
        return None

    # Load trace events
    events: list[dict[str, Any]] = []
    scenario_resolved = (
        manifest_data.get("scenario_data")
        or manifest_data.get("scenario")
        or run.get("scenario_data")
        or {}
    )
    trace_hash = compute_sha3_digest(raw_trace_bytes)

    # Parse preserving per-line provenance: (event, raw_line) pairs plus
    # byte offsets of any UNPARSEABLE lines.
    events: list[dict[str, Any]] = []
    events_with_lines: list[tuple[dict[str, Any], str]] = []
    corrupt_line_offsets: list[int] = []
    offset = 0
    for raw_line in raw_trace_bytes.split(b"\n"):
        line_start_offset = offset
        offset += len(raw_line) + 1  # account for the split newline
        text = raw_line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            ev = json.loads(text)
            events.append(ev)
            events_with_lines.append((ev, text))
        except Exception as err:
            logger.debug("Skipping unparseable trace event line: %s", err)
            corrupt_line_offsets.append(line_start_offset)

    # [E3] Corruption policy: unparseable trace content means the evidence
    # stream is not certifiable. The outcome can never be VERIFIED while
    # corruption is present, and exact byte offsets are reported.
    if corrupt_line_offsets:
        integrity_corruption: dict[str, Any] | None = {
            "status": "EVIDENCE_INVALID",
            "corrupt_count": len(corrupt_line_offsets),
            "corrupt_line_byte_offsets": corrupt_line_offsets,
            "policy": (
                "Unparseable trace content detected; the evidence stream cannot "
                "be certified until the trace is intact."
            ),
        }
    else:
        integrity_corruption = None

    # Extract verdicts and run status
    run_end_event = next((e for e in reversed(events) if e.get("event") == "run_end"), {})
    data_block = run_end_event.get("data", {})

    execution_status = data_block.get("status", "EXECUTION_COMPLETED")

    # Load certificate and signature chain
    cert_data = manifest_data

    signatures = cert_data.get("provenance_chain", cert_data.get("signatures", []))

    # ---------------------------------------------------------------------------
    # Authoritative Cryptographic Verification
    # ---------------------------------------------------------------------------
    # We call the authoritative signing verifier to determine whether the
    # signature chain in the certificate is genuinely valid, not merely present.
    # The verdict VERIFIED can only be assigned when verify_trace returns True.
    # ---------------------------------------------------------------------------
    crypto_verification: dict[str, Any] = {
        "verified": False,
        "signer_identity": None,
        "manifest_hash_match": False,
        "scenario_hash_match": False,
        "errors": [],
        "algorithm": None,
    }

    if cert_data:
        try:
            from eval_runner.verifier import verify_trace_certificate

            crypto_verification = verify_trace_certificate(
                run_id=run_id,
                trace_bytes=raw_trace_bytes,
                cert_data=cert_data,
                scenario_data=scenario_resolved or None,
            )
        except ImportError:
            # verify_trace_certificate not yet available; fall back to conservative check
            crypto_verification["errors"].append(
                "verify_trace_certificate not available; signature not verified."
            )
        except Exception as err:
            logger.warning("Cryptographic verification failed for %s: %s", run_id, err)
            crypto_verification["errors"].append(str(err))

    # Authoritative Verdict — determined by real verification and finalization,
    # not artifact presence.
    compliance = manifest_data.get("compliance") or {}
    cert = manifest_data.get("certification") or {}
    cert_outcome = str(cert.get("outcome") or "").lower()
    computed_status = str(
        cert_outcome or compliance.get("status") or manifest_data.get("status") or execution_status
    ).lower()
    computed_score = compliance.get("score", manifest_data.get("score"))
    if cert_outcome == "attested_fail":
        is_eval_pass = False
    elif data_block.get("passed") is True or computed_status in {"pass", "passed", "certified"}:
        is_eval_pass = True
    elif data_block.get("passed") is False or computed_status in {
        "fail",
        "failed",
        "execution_failed",
        "attested_fail",
        "attested_failed",
    }:
        is_eval_pass = False
    elif (
        crypto_verification.get("verified") is True
        and crypto_verification.get("manifest_hash_match") is True
        and computed_status
        not in {"fail", "failed", "execution_failed", "attested_fail", "attested_failed"}
    ):
        is_eval_pass = True
    else:
        is_eval_pass = None

    # Priority: evidence_invalid > policy_violation > crypto-verified >
    # unverified > not-verified / inconclusive
    if corrupt_line_offsets:
        verified_outcome = "EVIDENCE_INVALID"
    elif any(e.get("event") == "policy_violation" for e in events):
        verified_outcome = "POLICY_BREACH"
    elif (
        is_eval_pass is True
        and crypto_verification.get("verified") is True
        and crypto_verification.get("manifest_hash_match") is True
    ):
        verified_outcome = "VERIFIED"
    elif (
        is_eval_pass is False
        and crypto_verification.get("verified") is True
        and crypto_verification.get("manifest_hash_match") is True
    ):
        verified_outcome = "ATTESTED_FAIL"
    elif is_eval_pass is True:
        # Execution passed but signature did not verify — report truthfully
        verified_outcome = "UNVERIFIED"
    elif is_eval_pass is False:
        verified_outcome = "NOT_VERIFIED"
    else:
        # Authoritative finalization/computed outcomes unavailable
        verified_outcome = "INCONCLUSIVE"

    evidence_chain_valid: bool = (
        verified_outcome in {"VERIFIED", "ATTESTED_FAIL"} and not corrupt_line_offsets
    )

    assertions = data_block.get("assertions", [])
    if not assertions:
        for ev in reversed(events):
            ev_data = ev.get("data", {}) if isinstance(ev.get("data"), dict) else {}
            ev_asserts = ev_data.get("assertions") or ev.get("assertions")
            if isinstance(ev_asserts, list) and ev_asserts:
                assertions = ev_asserts
                break
    # Score calculation strictly from authoritative finalization or computed outcome
    if computed_status not in (None, "inconclusive") and computed_score is not None:
        score = float(computed_score)
    else:
        if assertions:
            passed_count = sum(1 for a in assertions if a.get("passed", False))
            score = passed_count / len(assertions)
        elif "score" in data_block:
            score = float(data_block["score"])
        elif verified_outcome == "VERIFIED":
            score = 1.0
        else:
            score = 0.0

    # Evidence Graph v1: every assertion linked to its source event
    # (by _seq + exact-line content hash) or reported UNRESOLVED.
    from agentv_runtime.evidence_graph import build_evidence_graph

    carrier_seq = next(
        (
            e.get("_seq")
            for e in reversed(events)
            if e.get("event") == "run_end" and isinstance(e.get("_seq"), int)
        ),
        None,
    )
    evidence_graph = build_evidence_graph(
        events_with_lines,
        assertions,
        carrier_seq=carrier_seq,
        artifact_hashes={"run.jsonl": trace_hash},
    )

    # [Chain header] Run → Scenario(revision) → Config → Target → Mode → Run.
    # Five immutable bindings an auditor must have WITHOUT reconstructing
    # them from the trace. scenario_hash is computed over the resolved
    # scenario actually executed (authoritative revision identity).
    from agentv_runtime.manifest import compute_scenario_hash

    run_start = next((e for e in events if e.get("event") == "run_start"), {})
    start_meta = (
        run_start.get("data", {}).get("metadata", {})
        if isinstance(run_start.get("data"), dict)
        else {}
    ) or {}
    mode_raw = (
        run_start.get("execution_mode")
        or start_meta.get("execution_mode")
        or manifest_data.get("execution_mode")
    )
    declared = bool(
        run_start.get("execution_mode_declared")
        or start_meta.get("execution_mode_declared")
        or mode_raw
    )
    chain = {
        "run_id": run_id,
        "scenario_hash": (compute_scenario_hash(scenario_resolved) if scenario_resolved else None),
        "resolved_config_hash": (
            run_start.get("reproducibility_fingerprint")
            or start_meta.get("reproducibility_fingerprint")
        ),
        "agent_target_id": (
            run_start.get("identifier")
            or start_meta.get("identifier")
            or manifest_data.get("identifier")
        ),
        "execution_mode": str(mode_raw) if mode_raw else "unknown",
        "execution_mode_declared": declared,
    }

    # Deterministic canonical core (excluding envelope timestamps)
    artifact_scope = resolve_artifact_scope(manifest_data)
    canonical_payload = {
        "format": "agentv_verification_package",
        "package_version": VERIFICATION_PACKAGE_VERSION,
        "run_id": run_id,
        "org_id": (artifact_scope["org_id"] or manifest_data.get("org_id") or "default-org"),
        "tenant_id": (
            artifact_scope["tenant_id"] or manifest_data.get("tenant_id") or "default-tenant"
        ),
        "workspace_id": (
            artifact_scope["workspace_id"]
            or manifest_data.get("workspace_id")
            or "default-workspace"
        ),
        "active_environment": (
            artifact_scope["active_environment"]
            or manifest_data.get("active_environment")
            or "production"
        ),
        "chain": chain,
        "manifest": manifest_data,
        "scenario": scenario_resolved,
        "verdict": {
            "execution_status": execution_status,
            "verified_outcome": verified_outcome,
            "duration_seconds": data_block.get("duration", 0),
            "score": score,
            "assertions": assertions,
        },
        "evidence_chain_valid": evidence_chain_valid,
        "cryptographic_verification": crypto_verification,
        "evidence_manifest": {
            "trace_hash": trace_hash,
            "total_events": len(events),
            "assertions_evaluated": len(assertions),
            "artifacts": [
                {"name": "run.jsonl", "hash": trace_hash, "type": "trace_events"},
            ],
        },
        "evidence_graph": evidence_graph,
        **({"integrity_corruption": integrity_corruption} if integrity_corruption else {}),
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
    if not _run_is_in_active_context(run_id):
        return jsonify({"error": "Verification package not found for run", "run_id": run_id}), 404
    package = build_verification_package(
        run_id, run_store=_active_run_store(), context=active_runtime_context()
    )
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
    packages_summary = []
    context = active_runtime_context()
    store = _active_run_store()
    for run in store.list_runs(limit=200, context=context):
        rid = run.get("run_id")
        if not rid or not _run_is_in_active_context(rid):
            continue
        manifest = store.get_manifest(rid, context=context) or {}
        packages_summary.append(
            {
                "run_id": rid,
                "has_certificate": bool(
                    manifest.get("verification_package") or manifest.get("vc_version")
                ),
                "has_manifest": bool(manifest),
                "package_url": f"/api/v1/evidence/packages/{rid}",
                "download_url": f"/api/v1/evidence/packages/{rid}?download=true",
            }
        )

    return jsonify({"packages": packages_summary})


@evidence_bp.route("/v1/evidence/verify", methods=["POST"])
@require_permission("runs:read")
def verify_verification_package():
    """
    Independently verifies an .agentv-package.json verification package.
    Validates trace byte parity, manifest binding, evidence graph root,
    decision verdict conformance, required oracle inventory, and signature.
    """
    from eval_runner.verifier import VerificationAuthority

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid payload: request body must be a JSON object"}), 400

    package_data = data.get("package") or data
    if not isinstance(package_data, dict):
        return jsonify({"error": "Invalid payload: package must be a JSON object"}), 400

    raw_trace_b64 = data.get("raw_trace_bytes")
    raw_trace_bytes = None
    if raw_trace_b64:
        import base64

        try:
            raw_trace_bytes = base64.b64decode(raw_trace_b64)
        except Exception as b64_err:
            return jsonify({"error": f"Invalid base64 trace payload: {b64_err}"}), 400

    raw_trace_events = data.get("raw_trace_events")
    public_key_pem = data.get("public_key_pem")
    require_signature = bool(data.get("require_signature", True))
    scenario_data = data.get("scenario_data")
    require_scenario = bool(data.get("require_scenario", True) or scenario_data is not None)

    # Fail closed if raw_trace_bytes missing in production verification
    if raw_trace_bytes is None and require_signature:
        return (
            jsonify(
                {
                    "verified": False,
                    "status": "UNVERIFIED",
                    "failures": [
                        "TraceBytesMissing: production package verification "
                        "requires raw trace bytes"
                    ],
                    "package_id": (
                        package_data.get("package_id") if isinstance(package_data, dict) else None
                    ),
                }
            ),
            422,
        )

    res = VerificationAuthority.verify_package(
        package_data,
        scenario_data=scenario_data,
        raw_trace_bytes=raw_trace_bytes,
        raw_trace_events=raw_trace_events,
        public_key_pem=public_key_pem,
        require_signature=require_signature,
        require_scenario_binding=require_scenario,
    )
    status_code = 200 if res.get("verified") else 422
    return jsonify(res), status_code
