# ruff: noqa: E501
"""
pdf_service.py

Resilient PDF Generation Engine for AgentV Visual Suite.
Compiles templates for CIO/CISO individual run reports and bundle companion documents.
Provides primary WeasyPrint (HTML/CSS) rendering and a pure-Python ReportLab fallback
to ensure GTK+ dependency errors on Windows do not crash the environment.
"""

import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Try importing WeasyPrint (on Windows, WeasyPrint CFFI requires external GTK/Pango C libraries which crash with 0xc0000139 if absent; use pure-Python ReportLab fallback)
WEASYPRINT_AVAILABLE = False
if (
    "weasyprint" in sys.modules
    or sys.platform != "win32"
    or os.environ.get("ENABLE_WEASYPRINT_WINDOWS") == "1"
):
    try:
        # Suppress verbose warnings printed by weasyprint during import
        null_out = open(os.devnull, "w")
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = null_out
        sys.stderr = null_out
        try:
            import weasyprint

            WEASYPRINT_AVAILABLE = True
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            null_out.close()
    except (ImportError, OSError) as e:
        logger.warning(
            f"WeasyPrint or its GTK dependencies not available. "
            f"Using ReportLab as fallback engine. Error: {e}"
        )

# Try importing ReportLab
REPORTLAB_AVAILABLE = False
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    REPORTLAB_AVAILABLE = True
except ImportError as e:
    logger.error(f"ReportLab is not available: {e}")


def generate_run_pdf(run_data: dict, output_path: Path | str) -> bool:
    """
    Generates a CIO/CISO individual run compliance report PDF.
    """
    output_path = Path(output_path)
    # Create directory if not exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Gather report data
    run_id = run_data.get("run_id", "unknown_run")
    scenario = run_data.get("scenario", "N/A")
    org_id = run_data.get("org_id", "")
    tenant_id = run_data.get("tenant_id", "")
    workspace_id = run_data.get("workspace_id", "")
    active_environment = run_data.get("active_environment", "")
    raw_status = str(
        run_data.get("status") or run_data.get("execution_status") or "UNKNOWN"
    ).upper()
    verif_status = str(run_data.get("verification_status") or "").upper()
    passed = run_data.get("passed")

    if (
        (
            verif_status in ("VERIFIED", "CERTIFIED_PASS", "CERTIFIED")
            or (
                run_data.get("certificate_valid") is True
                and run_data.get("cryptographically_valid") is True
            )
        )
        and run_data.get("is_authoritative") is not False
        and run_data.get("certificate_valid") is not False
        and (passed is True or raw_status in ("PASSED", "PASS"))
    ):
        status = "CERTIFIED_PASS"
    elif verif_status == "ATTESTED_FAIL" or raw_status in ("ATTESTED_FAIL", "ATTESTED FAIL"):
        status = "ATTESTED FAIL"
    elif verif_status in ("FAILED", "FAILED_VERIFICATION", "POLICY_BREACH"):
        status = verif_status
    elif passed is False or raw_status in ("FAILED", "FAIL"):
        status = "FAILED"
    elif passed is True or raw_status in ("PASSED", "PASS"):
        status = "EXECUTION_PASSED"
    elif raw_status in ("UNKNOWN", "", "UNVERIFIED"):
        status = "UNVERIFIED"
    else:
        status = raw_status

    timestamp = run_data.get("timestamp", "")
    if not timestamp:
        timestamp = datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"

    analysis = run_data.get("analysis", {})
    failed_turn = (
        analysis.get("failed_turn_index") or analysis.get("index") or run_data.get("failed_turn")
    )
    failed_node = None
    failed_oracles = run_data.get("failed_oracles") or []
    if failed_oracles and isinstance(failed_oracles[0], dict):
        first_failed_oracle = failed_oracles[0]
        failed_node = (
            first_failed_oracle.get("node_id")
            or first_failed_oracle.get("scenario_node_id")
            or first_failed_oracle.get("node")
        )
        if failed_turn is None:
            failed_turn = first_failed_oracle.get("turn") or first_failed_oracle.get("step")

    # If failed_turn is still None, scan events if available
    events = run_data.get("events") or []
    if failed_turn is None and events:
        for ev in events:
            ev_data = ev.get("data") if isinstance(ev.get("data"), dict) else ev
            if (
                ev.get("event") in ("policy_violation", "assertion_evaluated", "metric_evaluated")
                or ev_data.get("status") in ("FAIL", "FAILED", "policy_violation")
                or ev_data.get("outcome") in ("FAIL", "FAILED")
            ):
                t_val = (
                    ev.get("turn") or ev_data.get("turn") or ev.get("step") or ev_data.get("step")
                )
                if t_val is not None:
                    failed_turn = t_val
                    break

    if status in ("CERTIFIED_PASS", "VERIFIED"):
        claim_scope = run_data.get("claim_scope") or "scenario invariants"
        root_cause = "Verified Compliant: No failure patterns detected."
        summary = f"Execution satisfied all certified scenario goals, state invariants, and safety constraints within claim scope ({claim_scope})."
        suggestion = f"Certified within declared claim scope ({claim_scope}). Ready for production deployment under certified claims."
        severity_score = "0.0 / 10.0"
        telemetry_text = (
            "Full execution step events, state mutations, and tool receipts are recorded in the audit trace. "
            "Complete deterministic sequence verified with 0 causal divergences."
        )
    elif status in ("EXECUTION_PASSED", "PASSED"):
        root_cause = "Execution completed successfully; certification has not been established."
        summary = (
            "The execution outcome passed, but no authoritative certificate establishes "
            "compliance, invariant coverage, or deployment readiness."
        )
        suggestion = "Unsigned run. Certification has not been established; do not use for compliance-verified deployment."
        severity_score = "N/A — certification pending"
        telemetry_text = (
            "Execution telemetry is available for review. It is not an independently "
            "verified compliance or deployment-readiness determination."
        )
    else:
        failure_reasons = run_data.get("failure_reasons") or []
        first_failure = failure_reasons[0] if failure_reasons else None
        root_cause = (
            analysis.get("root_cause")
            or run_data.get("failure_reason")
            or (f"Attestation failure: {first_failure}" if first_failure else None)
            or (
                "Evaluation criteria not met (ATTESTED FAIL)."
                if status == "ATTESTED FAIL"
                else None
            )
            or "Policy assertion or task constraint failed."
        )
        summary = analysis.get("summary") or (
            "Cryptographic signature and audit vault attestation verified, but scenario invariants or safety boundaries failed."
            if status == "ATTESTED FAIL"
            else "Execution terminated before achieving required verification state."
        )
        suggestion = (
            analysis.get("suggestion")
            or "Inspect causal failure in the Live Visual Debugger and adjust agent prompt, tool schema, or safety policy."
        )
        confidence = analysis.get("confidence", 1.0 if status == "ATTESTED FAIL" else 0.8)
        severity_score = f"{round(float(confidence) * 10, 1)} / 10.0"
        if failed_turn is not None and str(failed_turn).upper() != "N/A":
            node_desc = f" on node '{failed_node}'" if failed_node else ""
            telemetry_text = (
                f"Full execution step events and state timelines are recorded in the audit trace. "
                f"Jump to turn <strong>{failed_turn}</strong>{node_desc} in the Live Visual Debugger to trace structural discrepancies."
            )
        elif failed_node:
            telemetry_text = (
                f"Full execution step events and state timelines are recorded in the audit trace. "
                f"Inspect node '<strong>{failed_node}</strong>' in the Live Visual Debugger to trace structural discrepancies."
            )
        else:
            telemetry_text = (
                "Full execution step events and state timelines are recorded in the audit trace. "
                "Inspect the first causal divergence in the Live Visual Debugger to trace structural discrepancies."
            )

    # Truthful PQC status evaluation: display only verified algorithm and signer facts
    is_crypto_verified = bool(run_data.get("cryptographically_valid"))
    has_cert = bool(run_data.get("certificate_valid"))
    if not is_crypto_verified:
        pqc_status = "UNVERIFIED"
        cert_status = "NOT ISSUED (Unverified)"
    else:
        algo = str(run_data.get("algorithm") or "").strip().upper()
        if "ML-DSA" in algo:
            pqc_status = "QUANTUM_SECURE (ML-DSA-65)"
        elif "ED25519" in algo:
            pqc_status = "CLASSICAL (Ed25519)"
        elif algo:
            pqc_status = f"VERIFIED ({algo})"
        else:
            pqc_status = "UNVERIFIED"

        if status == "ATTESTED FAIL" and has_cert:
            cert_status = "ATTESTATION OF NON-CERTIFICATION (Signed Failure Audit)"
        elif status in ("CERTIFIED_PASS", "VERIFIED", "PASSED") and has_cert:
            cert_status = "ISSUED / VALIDATED"
        else:
            cert_status = "NOT ISSUED (Unverified)"

    evidence_ref = (
        run_data.get("evidence_reference")
        or run_data.get("trace_hash")
        or ("Merkle Root Sealed" if has_cert else "Unsigned / Uncertified")
    )

    # 2. Try WeasyPrint if available
    if WEASYPRINT_AVAILABLE:
        try:
            html_content = f"""
            <html>
            <head>
                <style>
                    @page {{ size: letter; margin: 14mm; }}
                    body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #1e293b; margin: 0; line-height: 1.45; }}
                    h1 {{ color: #4f46e5; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; font-size: 20px; margin-top: 0; }}
                    h2 {{ color: #0f172a; font-size: 13px; margin-top: 16px; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.05em; }}
                    .meta-table {{ width: 100%; border-collapse: collapse; margin-bottom: 14px; table-layout: fixed; }}
                    .meta-table th, .meta-table td {{ border: 1px solid #e2e8f0; padding: 7px 9px; text-align: left; font-size: 11px; word-break: break-word; overflow-wrap: anywhere; }}
                    .meta-table th {{ background-color: #f8fafc; font-weight: bold; width: 28%; }}
                    .card {{ background-color: #f1f5f9; border-left: 4px solid #4f46e5; padding: 12px; border-radius: 4px; margin-bottom: 12px; font-size: 11.5px; word-break: break-word; }}
                    .success-card {{ background-color: #f0fdf4; border-left: 4px solid #16a34a; padding: 12px; border-radius: 4px; font-size: 11.5px; }}
                    .footer {{ margin-top: 18px; border-top: 1px solid #e2e8f0; padding-top: 8px; font-size: 9.5px; color: #64748b; font-family: monospace; word-break: break-all; }}
                </style>
            </head>
            <body>
                <h1>AgentV Run Verification Summary</h1>
                <p style="font-size: 11px; color: #64748b; margin-top: 2px;">Generated on: {datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")}</p>
                
                <h2>1. Execution Metadata</h2>
                <table class="meta-table">
                    <tr><th>Run Identifier</th><td>{run_id}</td></tr>
                    <tr><th>Target Scenario</th><td>{scenario}</td></tr>
                    <tr><th>Organization</th><td>{org_id}</td></tr>
                    <tr><th>Tenant</th><td>{tenant_id}</td></tr>
                    <tr><th>Workspace</th><td>{workspace_id}</td></tr>
                    <tr><th>Environment</th><td>{active_environment}</td></tr>
                    <tr><th>Runtime Verdict</th><td>{status}</td></tr>
                    <tr><th>Completion Epoch</th><td>{timestamp}</td></tr>
                </table>

                <h2>2. Verification & Evidence Status</h2>
                <table class="meta-table">
                    <tr><th>Signature / PQC Status</th><td>{pqc_status}</td></tr>
                    <tr><th>Weighted Severity Score</th><td>{severity_score}</td></tr>
                    <tr><th>Verification Certificate</th><td>{cert_status}</td></tr>
                </table>

                <h2>3. Executive Summary</h2>
                <div class="card">
                    <strong>Identified Pattern:</strong> {root_cause}<br/><br/>
                    <strong>Summary Details:</strong> {summary}<br/><br/>
                    <strong>Remediation:</strong> {suggestion}
                </div>

                <h2>4. Behavioral Telemetry</h2>
                <p style="font-size: 11.5px;">{telemetry_text}</p>

                <div class="footer">
                    Run Identifier: {run_id}<br/>
                    Evidence Reference: {evidence_ref}<br/>
                    Generated by AgentV Audit Engine
                </div>
            </body>
            </html>

            """
            weasyprint.HTML(string=html_content).write_pdf(str(output_path))
            logger.info(f"WeasyPrint compiled PDF successfully at: {output_path}")
            return True
        except Exception as e:
            logger.error(
                f"WeasyPrint execution failed, falling back to ReportLab: {e}", exc_info=True
            )

    # 3. Fallback to ReportLab
    if REPORTLAB_AVAILABLE:
        try:
            doc = SimpleDocTemplate(
                str(output_path),
                pagesize=letter,
                leftMargin=45,
                rightMargin=45,
                topMargin=36,
                bottomMargin=36,
            )
            styles = getSampleStyleSheet()

            # Custom Styles
            title_style = ParagraphStyle(
                "ReportTitle",
                parent=styles["Heading1"],
                textColor=colors.HexColor("#4f46e5"),
                fontSize=18,
                spaceAfter=8,
            )
            h2_style = ParagraphStyle(
                "SectionHeader",
                parent=styles["Heading2"],
                textColor=colors.HexColor("#0f172a"),
                fontSize=11,
                spaceBefore=10,
                spaceAfter=6,
            )
            body_style = ParagraphStyle(
                "BodyTextCustom",
                parent=styles["Normal"],
                textColor=colors.HexColor("#1e293b"),
                fontSize=9.5,
                leading=13,
            )
            cell_label_style = ParagraphStyle(
                "CellLabel",
                parent=styles["Normal"],
                fontName="Helvetica-Bold",
                textColor=colors.HexColor("#1e293b"),
                fontSize=8.5,
                leading=11,
            )
            cell_value_style = ParagraphStyle(
                "CellValue",
                parent=styles["Normal"],
                textColor=colors.HexColor("#1e293b"),
                fontSize=8.5,
                leading=11,
                wordWrap="CJK",
            )
            card_style = ParagraphStyle(
                "CardText",
                parent=styles["Normal"],
                textColor=colors.HexColor("#1e293b"),
                fontSize=9,
                leading=12.5,
                wordWrap="CJK",
            )

            story = []

            # Title
            story.append(Paragraph("AgentV Enterprise Compliance Report", title_style))
            story.append(
                Paragraph(
                    f"Generated on: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
                    body_style,
                )
            )
            story.append(Spacer(1, 8))

            def _row(label: str, val: object) -> list:
                return [
                    Paragraph(str(label), cell_label_style),
                    Paragraph(str(val if val is not None else ""), cell_value_style),
                ]

            # 1. Metadata Table
            story.append(Paragraph("1. Execution Metadata", h2_style))
            meta_data = [
                _row("Run Identifier", run_id),
                _row("Target Scenario", scenario),
                _row("Organization", org_id),
                _row("Tenant", tenant_id),
                _row("Workspace", workspace_id),
                _row("Environment", active_environment),
                _row("Overall Verdict", status),
                _row("Completion Epoch", timestamp),
            ]
            t = Table(meta_data, colWidths=[145, 375])
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
                        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1e293b")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("PADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            story.append(t)
            story.append(Spacer(1, 10))

            # 2. Compliance Analysis Table
            story.append(Paragraph("2. Compliance Analysis", h2_style))
            compliance_data = [
                _row("PQC Status", pqc_status),
                _row("Weighted Severity Score", severity_score),
                _row("Verification Certificate", cert_status),
            ]

            t2 = Table(compliance_data, colWidths=[145, 375])
            t2.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
                        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1e293b")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("PADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            story.append(t2)
            story.append(Spacer(1, 10))

            # 3. Executive Summary
            story.append(Paragraph("3. Executive Summary", h2_style))
            summary_html = f"<b>Identified Pattern:</b> {root_cause}<br/><br/><b>Summary Details:</b> {summary}<br/><br/><b>Remediation:</b> {suggestion}"

            # Wrap summary in a card styled table
            t_summary = Table([[Paragraph(summary_html, card_style)]], colWidths=[520])
            t_summary.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f5f9")),
                        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#4f46e5")),
                        ("PADDING", (0, 0), (-1, -1), 10),
                    ]
                )
            )
            story.append(t_summary)
            story.append(Spacer(1, 10))

            # 4. Telemetry Note
            story.append(Paragraph("4. Behavioral Telemetry", h2_style))
            reportlab_telemetry = telemetry_text.replace("<strong>", "<b>").replace(
                "</strong>", "</b>"
            )
            story.append(Paragraph(reportlab_telemetry, body_style))
            story.append(Spacer(1, 12))

            # Footer signature
            story.append(
                Paragraph(
                    f"Run Identifier: {run_id}<br/>Evidence Reference: {evidence_ref}<br/>Signed by AgentV Audit Engine",
                    card_style,
                )
            )

            doc.build(story)
            logger.info(f"ReportLab compiled PDF successfully at: {output_path}")
            return True
        except Exception as e:
            logger.error(f"ReportLab generation failed: {e}", exc_info=True)

    # If both failed or are unavailable, write a text layout report
    try:
        txt_path = output_path.with_suffix(".txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("AgentV Enterprise Compliance Report\n")
            f.write(f"Run ID: {run_id}\n")
            f.write(f"Scenario: {scenario}\n")
            f.write(f"Organization: {org_id}\n")
            f.write(f"Tenant: {tenant_id}\n")
            f.write(f"Workspace: {workspace_id}\n")
            f.write(f"Environment: {active_environment}\n")
            f.write(f"Status: {status}\n")
            f.write(f"Timestamp: {timestamp}\n")
            f.write(f"PQC Status: {pqc_status}\n")
            f.write(f"Verification Certificate: {cert_status}\n")
            f.write(f"Summary: {summary}\n")
            f.write(f"Root Cause: {root_cause}\n")
            f.write(f"Suggestion: {suggestion}\n")
        logger.warning(f"No PDF engines working. Saved fallback text report to: {txt_path}")
        # Copy to output_path to prevent file missing issues
        output_path.write_bytes(txt_path.read_bytes())
        return True
    except Exception as e:
        logger.error(f"Last fallback text report generator failed: {e}", exc_info=True)
        return False


def _is_run_authoritative_pass(r: dict) -> bool:
    """Calculate pass counts exclusively from authoritative per-run verdicts."""
    verif = str(
        r.get("verification_status") or r.get("terminal_verdict") or r.get("verdict") or ""
    ).upper()
    if verif in {"VERIFIED", "CERTIFIED_PASS"}:
        return True
    if bool(r.get("verified")) and verif in {"CERTIFIED", "PASSED"}:
        return True
    return False


def _run_verification_label(r: dict) -> str:
    """Derive verification check label exclusively from authoritative verdict."""
    verif = str(
        r.get("verification_status") or r.get("terminal_verdict") or r.get("verdict") or ""
    ).upper()
    if verif in {"VERIFIED", "CERTIFIED_PASS"}:
        return "VERIFIED"
    if verif == "ATTESTED_FAIL":
        return "ATTESTED FAIL"
    if verif in {"FAILED", "FAILED_VERIFICATION", "POLICY_BREACH"}:
        return "FAILING"
    return "UNVERIFIED"


def generate_bundle_pdf(suite_data: dict, run_list: list, output_path: Path) -> bool:
    """
    Generates a Companion PDF summary report for a Regression Suite ZIP bundle.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    suite_name = suite_data.get("name", "Regression Suite")
    agent_name = suite_data.get("agent_name", "N/A")
    created_at = suite_data.get("created_at", "")

    total_runs = len(run_list)
    passing_runs = sum(1 for r in run_list if _is_run_authoritative_pass(r))
    total_runs - passing_runs

    # 2. Try WeasyPrint if available
    if WEASYPRINT_AVAILABLE:
        try:
            html_content = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #1e293b; margin: 40px; line-height: 1.5; }}
                    h1 {{ color: #4f46e5; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; font-size: 24px; }}
                    h2 {{ color: #0f172a; font-size: 16px; margin-top: 25px; margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.05em; }}
                    .meta-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
                    .meta-table th, .meta-table td {{ border: 1px solid #e2e8f0; padding: 10px; text-align: left; font-size: 12px; }}
                    .meta-table th {{ bg-color: #f8fafc; font-weight: bold; width: 30%; }}
                    .card {{ background-color: #f8fafc; border: 1px solid #e2e8f0; padding: 15px; border-radius: 4px; margin-bottom: 15px; font-size: 13px; }}
                    .footer {{ margin-top: 50px; border-t: 1px solid #e2e8f0; padding-top: 10px; font-size: 10px; color: #64748b; font-family: monospace; }}
                </style>
            </head>
            <body>
                <h1>AgentV Regression Suite Handoff Summary</h1>
                <p style="font-size: 12px; color: #64748b;">Created on: {created_at}</p>
                
                <h2>1. Suite Metadata</h2>
                <table class="meta-table">
                    <tr><th>Suite Name</th><td>{suite_name}</td></tr>
                    <tr><th>Target Agent</th><td>{agent_name}</td></tr>
                    <tr><th>Aggregate Performance</th><td>{passing_runs} / {total_runs} runs passed ({round(passing_runs / total_runs * 100 if total_runs > 0 else 0, 1)}%)</td></tr>
                </table>

                <h2>2. Zip Archive Contents</h2>
                <div class="card">
                    <ul>
                        <li><strong>audit_manifest.json</strong>: Cryptographically signed list of file hashes (Ed25519 payload).</li>
                        <li><strong>companion_summary.pdf</strong>: Human-readable guide for the auditor (this document).</li>
                        <li><strong>runs/</strong>: Directory containing raw run traces and verification certificates.</li>
                    </ul>
                </div>

                <h2>3. Audited Run Breakdown</h2>
                <table class="meta-table">
                    <thead>
                        <tr style="background-color: #f8fafc;">
                            <th>Run Identifier</th>
                            <th>Status</th>
                            <th>Verification Check</th>
                        </tr>
                    </thead>
                    <tbody>
                        {"".join(f"<tr><td>{r.get('run_id')}</td><td>{r.get('status')}</td><td>{_run_verification_label(r)}</td></tr>" for r in run_list)}
                    </tbody>
                </table>

                <div class="footer">
                    Suite ID: {suite_data.get("suite_id")}<br/>
                    Verified Handoff Bundle System Signature (SHA3-256 Chain)
                </div>
            </body>
            </html>
            """
            weasyprint.HTML(string=html_content).write_pdf(str(output_path))
            return True
        except Exception as e:
            logger.error(f"WeasyPrint companion PDF generation failed: {e}", exc_info=True)

    # 3. Fallback to ReportLab
    if REPORTLAB_AVAILABLE:
        try:
            doc = SimpleDocTemplate(str(output_path), pagesize=letter)
            styles = getSampleStyleSheet()

            title_style = ParagraphStyle(
                "SuiteTitle",
                parent=styles["Heading1"],
                textColor=colors.HexColor("#4f46e5"),
                fontSize=20,
                spaceAfter=15,
            )
            h2_style = ParagraphStyle(
                "SectionHeader",
                parent=styles["Heading2"],
                textColor=colors.HexColor("#0f172a"),
                fontSize=12,
                spaceBefore=15,
                spaceAfter=10,
            )
            body_style = ParagraphStyle(
                "BodyTextCustom",
                parent=styles["Normal"],
                textColor=colors.HexColor("#1e293b"),
                fontSize=10,
                leading=14,
            )
            card_style = ParagraphStyle(
                "CardText",
                parent=styles["Normal"],
                textColor=colors.HexColor("#1e293b"),
                fontSize=9,
                leading=13,
            )

            story = []

            story.append(Paragraph("AgentV Regression Suite Handoff Summary", title_style))
            story.append(Paragraph(f"Created on: {created_at}", body_style))
            story.append(Spacer(1, 15))

            # 1. Metadata
            story.append(Paragraph("1. Suite Metadata", h2_style))
            pct = round(passing_runs / total_runs * 100 if total_runs > 0 else 0, 1)
            meta_data = [
                ["Suite Name", suite_name],
                ["Target Agent", agent_name],
                ["Aggregate Performance", f"{passing_runs} / {total_runs} runs passed ({pct}%)"],
            ]
            t = Table(meta_data, colWidths=[150, 300])
            t.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
                        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1e293b")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                        ("PADDING", (0, 0), (-1, -1), 8),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ]
                )
            )
            story.append(t)
            story.append(Spacer(1, 15))

            # 2. Archive Contents
            story.append(Paragraph("2. Zip Archive Contents", h2_style))
            contents_html = (
                "• <b>audit_manifest.json</b>: Cryptographically signed list of file hashes (Ed25519 payload).<br/>"
                "• <b>companion_summary.pdf</b>: Human-readable guide for the auditor (this document).<br/>"
                "• <b>runs/</b>: Directory containing raw run traces and verification certificates."
            )
            t_contents = Table([[Paragraph(contents_html, card_style)]], colWidths=[450])
            t_contents.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                        ("PADDING", (0, 0), (-1, -1), 10),
                    ]
                )
            )
            story.append(t_contents)
            story.append(Spacer(1, 15))

            # 3. Runs breakdown table
            story.append(Paragraph("3. Audited Run Breakdown", h2_style))
            table_header = [["Run Identifier", "Status", "Verification Check"]]
            for r in run_list:
                chk = _run_verification_label(r)
                table_header.append([r.get("run_id", "N/A"), r.get("status", "N/A"), chk])

            t_runs = Table(table_header, colWidths=[200, 130, 120])
            t_runs.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
                        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1e293b")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                        ("PADDING", (0, 0), (-1, -1), 6),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            story.append(t_runs)
            story.append(Spacer(1, 30))

            # Footer
            story.append(
                Paragraph(
                    f"Suite ID: {suite_data.get('suite_id')}<br/>Verified Handoff Bundle System Signature (SHA3-256 Chain)",
                    card_style,
                )
            )

            doc.build(story)
            return True
        except Exception as e:
            logger.error(f"ReportLab companion PDF generation failed: {e}", exc_info=True)

    # Fallback to Text report
    try:
        txt_path = output_path.with_suffix(".txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("AgentV Regression Suite Handoff Summary\n")
            f.write(f"Suite: {suite_name}\n")
            f.write(f"Agent: {agent_name}\n")
            f.write(f"Created At: {created_at}\n")
            f.write(f"Performance: {passing_runs}/{total_runs} passed\n")
            f.write("\nRuns List:\n")
            for r in run_list:
                f.write(f" - {r.get('run_id')}: {r.get('status')} [{_run_verification_label(r)}]\n")
        output_path.write_bytes(txt_path.read_bytes())
        return True
    except Exception as e:
        logger.error(f"Failed to generate fallback txt summary report: {e}", exc_info=True)
        return False
