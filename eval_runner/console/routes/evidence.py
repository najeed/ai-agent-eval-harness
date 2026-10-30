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


def _certification_graph(
    events_with_lines: list[tuple[dict[str, Any], str]],
    *,
    expected_root: str | None,
    required_oracle_ids: list[str] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Rebuild the certification graph and require its committed root."""
    from agentv_runtime.evidence_graph import build_evidence_graph_from_events

    graph = build_evidence_graph_from_events(
        events_with_lines, required_oracle_ids=required_oracle_ids or []
    )
    if expected_root and graph.get("evidence_root_hash") == expected_root:
        return graph, True
    filtered = [
        (event, line)
        for event, line in events_with_lines
        if not (
            event.get("event") == "evaluator_finalization"
            or (
                event.get("event") in ("run_end", "verification_decision", "session_decision")
                and isinstance(
                    event.get("finalization")
                    or (
                        event.get("data", {}).get("finalization")
                        if isinstance(event.get("data"), dict)
                        else None
                    ),
                    dict,
                )
            )
        )
    ]
    filtered_graph = build_evidence_graph_from_events(
        filtered, required_oracle_ids=required_oracle_ids or []
    )
    return filtered_graph, bool(
        expected_root and filtered_graph.get("evidence_root_hash") == expected_root
    )


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
        try:
            text = raw_line.decode("utf-8").strip()
        except UnicodeDecodeError:
            corrupt_line_offsets.append(line_start_offset)
            continue
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
            crypto_verification.setdefault("errors", [])
            from eval_runner.verifier import TraceVerifier

            authority = TraceVerifier.verify_run(
                run_id,
                run_store=run_store,
                context=context,
                scenario_data=scenario_resolved or None,
            )
            crypto_verification["verified"] = authority["is_valid"]
            if authority.get("failure_reason"):
                crypto_verification["errors"].append(authority["failure_reason"])
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
    # Trace assertions are provider-owned observations for RCA.  They cannot
    # determine a verdict, score, or certification state.
    observed_assertions: list[dict[str, Any]] = []
    for ev in reversed(events):
        ev_data = ev.get("data", {}) if isinstance(ev.get("data"), dict) else {}
        ev_asserts = ev_data.get("assertions") or ev.get("assertions")
        if isinstance(ev_asserts, list) and ev_asserts:
            observed_assertions = [item for item in ev_asserts if isinstance(item, dict)]
            break

    # The trace is never an independent certification authority.  A package
    # can report a certified outcome only when the provider has sealed a
    # transactional certificate, its signature verifies, and the graph rebuilt
    # from the exact provider bytes has the root committed in that certificate.
    certification = manifest_data.get("certification") or {}
    signed_package = manifest_data.get("verification_package") or {}
    if not isinstance(certification, dict):
        certification = {}
    if not isinstance(signed_package, dict):
        signed_package = {}
    compliance = manifest_data.get("compliance") or {}
    certification_outcome = str(certification.get("outcome") or "").upper()
    is_sealed = str(run.get("lifecycle") or run.get("status") or "").upper() == "SEALED"
    expected_root = (
        str(
            signed_package.get("evidence_root_hash")
            or manifest_data.get("evidence_root_hash")
            or ""
        )
        or None
    )
    required_oracles = (
        signed_package.get("required_oracle_ids")
        or manifest_data.get("metadata", {}).get("required_oracle_ids")
        or []
    )
    evidence_graph, graph_matches_certificate = _certification_graph(
        events_with_lines,
        expected_root=expected_root,
        required_oracle_ids=list(required_oracles),
    )
    evidence_graph["authority"] = (
        "certification_root_equivalent"
        if graph_matches_certificate
        else "preliminary_reconstructed"
    )
    signed_certificate = bool(
        is_sealed
        and certification.get("transactional") is True
        and certification_outcome in {"CERTIFIED_PASS", "ATTESTED_FAIL"}
        and isinstance(signed_package, dict)
    )
    cryptographically_verified = bool(
        crypto_verification.get("verified") is True
        and crypto_verification.get("manifest_hash_match") is True
    )
    evidence_chain_valid = bool(
        signed_certificate
        and cryptographically_verified
        and graph_matches_certificate
        and not corrupt_line_offsets
    )
    if corrupt_line_offsets:
        verified_outcome, execution_status, score, assertions = (
            "EVIDENCE_INVALID",
            "EVIDENCE_INVALID",
            None,
            [],
        )
        # Do not project the parseable subset as a usable evidence graph.
        # The exact trace hash and corruption offsets remain available for
        # investigation, but no presentation node can be mistaken for
        # certified evidence after a malformed byte sequence.
        evidence_graph = {
            "graph_version": evidence_graph.get("graph_version"),
            "authority": "invalid_trace",
            "evidence_root_hash": None,
            "total_nodes": 0,
            "nodes": [],
        }
    elif signed_certificate and not graph_matches_certificate:
        verified_outcome, execution_status, score, assertions = (
            "EVIDENCE_INVALID",
            "EVIDENCE_ROOT_MISMATCH",
            None,
            [],
        )
    elif evidence_chain_valid:
        is_pass = certification_outcome == "CERTIFIED_PASS"
        verified_outcome = "VERIFIED" if is_pass else "ATTESTED_FAIL"
        execution_status = certification_outcome
        score = compliance.get("score")
        assertions = list(signed_package.get("executed_oracle_results") or [])
    elif not is_sealed:
        # Provider-trace assertions remain useful RCA observations, but the
        # PRELIMINARY state and null score make clear that they are not a
        # certification verdict.
        verified_outcome, execution_status, score, assertions = (
            "PRELIMINARY",
            "PRELIMINARY",
            None,
            observed_assertions,
        )
    else:
        verified_outcome, execution_status, score, assertions = (
            "UNVERIFIED",
            certification_outcome or "SEALED",
            None,
            [],
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
            "duration_seconds": 0,
            "score": score,
            "assertions": assertions,
        },
        # Provider-trace observations support RCA, but are deliberately
        # separate from the certification verdict for unverified sealed runs.
        "observed_assertions": observed_assertions,
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


def _verify_package_request(*, authoritative: bool):
    """Verify a package without allowing diagnostic options to imply authority."""
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

    if authoritative and data.get("require_signature") is False:
        return jsonify(
            {
                "error": (
                    "AuthoritativeVerificationRequiresSignature: use "
                    "/v1/evidence/verify-diagnostic for unsigned analysis"
                )
            }
        ), 400
    if authoritative and (data.get("public_key_pem") or data.get("raw_trace_events") is not None):
        return jsonify(
            {
                "error": (
                    "AuthoritativeVerificationRequiresTrustedProviderInputs: "
                    "caller-supplied keys and reconstructed event streams are diagnostic-only"
                )
            }
        ), 400

    raw_trace_events = None if authoritative else data.get("raw_trace_events")
    public_key_pem = None if authoritative else data.get("public_key_pem")
    require_signature = True if authoritative else bool(data.get("require_signature", False))
    scenario_data = data.get("scenario_data")
    require_scenario = (
        True
        if authoritative
        else bool(data.get("require_scenario", False) or scenario_data is not None)
    )

    # Authoritative verification always consumes exact bytes and an anchored
    # signature.  Diagnostic verification may be used for offline triage but
    # cannot certify a package.
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
        canonical_manifest=data.get("execution_manifest") or data.get("canonical_manifest"),
        require_scenario_binding=require_scenario,
    )
    res["verification_mode"] = "AUTHORITATIVE" if authoritative else "DIAGNOSTIC"
    res["authoritative"] = bool(authoritative and res.get("authoritative"))
    res["certified"] = bool(authoritative and res.get("certified"))
    if not authoritative and res.get("verified"):
        res["status"] = "DIAGNOSTIC_VALID"
    status_code = 200 if res.get("verified") else 422
    return jsonify(res), status_code


@evidence_bp.route("/v1/evidence/verify", methods=["POST"])
@require_permission("runs:read")
def verify_verification_package():
    """Perform authoritative, signature-required package verification."""
    return _verify_package_request(authoritative=True)


@evidence_bp.route("/v1/evidence/verify-diagnostic", methods=["POST"])
@require_permission("runs:read")
def verify_verification_package_diagnostic():
    """Perform explicitly non-authoritative offline package diagnostics."""
    return _verify_package_request(authoritative=False)
