"""
eval_runner.services.run_summary
Single Authoritative Truth Model for Run Summaries, Lifecycle, and Verification Status.
Consumed uniformly by /runs, /v1/runs/stream-list, /v1/runs/<run_id>, Dashboard, and Reports.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from typing import Any

from eval_runner import config
from eval_runner.services.certification import CertificationService
from eval_runner.trace_utils import resolve_trace_path

logger = logging.getLogger(__name__)

TERMINAL_LIFECYCLE_STATUSES = frozenset({"COMPLETED", "FAILED", "SEALED", "ABORTED"})


class RunSummaryService:
    """Derives lifecycle, execution result, integrity, provisionality, and certification status."""

    @classmethod
    def get_authoritative_verdict(cls, run_id: str) -> str:
        """
        Authoritative verification computation.
        Returns: VERIFIED | VERIFIED_PROVISIONAL | FAILED_VERIFICATION |
        NOT_EXECUTED | ERROR | UNKNOWN
        """
        if not run_id:
            return "NOT_EXECUTED"

        tp = resolve_trace_path(run_id, allow_master_recovery=False)
        if not tp or not tp.exists():
            return "NOT_EXECUTED"

        from eval_runner.verifier import TraceVerifier, locate_certificate_file

        manifest_path = locate_certificate_file(run_id)
        if manifest_path is None or not manifest_path.exists():
            return "UNKNOWN"

        try:
            is_valid = TraceVerifier.verify_trace(str(tp), str(manifest_path), verify_ledger=True)
            if not is_valid:
                return "FAILED_VERIFICATION"

            try:
                with open(manifest_path, encoding="utf-8") as f_m:
                    m_data = json.load(f_m)
                    if m_data.get("provisional") is True or m_data.get("execution_mode") in (
                        "simulated",
                        "unknown",
                    ):
                        return "VERIFIED_PROVISIONAL"
            except Exception as prov_err:
                logger.debug(f"Provisional manifest check note for {run_id}: {prov_err}")

            return "VERIFIED"
        except Exception as err:
            logger.debug(f"Authoritative verdict check failed for {run_id}: {err}")
            return "ERROR"

    @classmethod
    def compute_summary(
        cls,
        run_id: str,
        cached_entry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Derives the single canonical truth summary for a given run ID.
        """
        cached = cached_entry or {}
        scenario = cached.get("scenario") or ""
        timestamp = cached.get("timestamp") or ""
        identifier = cached.get("identifier") or ""
        duration_seconds = cached.get("duration_seconds")
        cached_result_status = cached.get("result_status")
        cached_exec_mode = cached.get("execution_mode")

        cert_path = config.REPORTS_DIR / "certificates" / f"{run_id}_vc.json"
        vault_manifest = config.RUN_LOG_DIR / run_id / "run_manifest.json"
        has_certificate = cert_path.exists() or vault_manifest.exists()

        auth_verdict = cls.get_authoritative_verdict(run_id)

        # Truth-level derivation (execution_mode, provisional)
        if not cached_exec_mode:
            exec_mode, provisional = CertificationService.read_run_truth_level(run_id)
        else:
            exec_mode = cached_exec_mode
            provisional = bool(not exec_mode or exec_mode in ("simulated", "unknown"))

        # Trace path resolution
        tp = None
        path_val = cached.get("path") or cached.get("_fragment_path")
        if path_val:
            cand = config.RUN_LOG_DIR / path_val
            if cand.exists():
                tp = cand
        if not tp:
            tp = resolve_trace_path(run_id, allow_master_recovery=True)

        trace_integrity = "PARTIAL"
        if cached_result_status:
            trace_integrity = "COMPLETE"
        elif cached.get("_fragment_path"):
            trace_integrity = "RECOVERED"

        status = "RUNNING"
        lifecycle = "RUNNING"

        if auth_verdict == "VERIFIED":
            status = "CERTIFIED"
            lifecycle = "SEALED"
        elif auth_verdict == "VERIFIED_PROVISIONAL":
            status = "PROVISIONAL"
            lifecycle = "SEALED"
        elif has_certificate and (not tp or not tp.exists()):
            status = "ARTIFACT_PRESENT"
            lifecycle = "COMPLETED"
        elif not tp or not tp.exists():
            status = "NOT_EXECUTED"
            lifecycle = "NOT_EXECUTED"
            if timestamp:
                try:
                    ts_clean = timestamp.split("+")[0].split("Z")[0]
                    run_ts = datetime.fromisoformat(ts_clean).timestamp()
                    if time.time() - run_ts < 300:
                        status = "RUNNING"
                        lifecycle = "RUNNING"
                    else:
                        status = "STALLED"
                        lifecycle = "STALLED"
                except Exception:
                    status = "STALLED"
                    lifecycle = "STALLED"
        else:
            # Physical trace exists - determine status from trace indicators
            run_dir = tp.parent
            has_seal = (run_dir / ".sealed").exists()
            from eval_runner.verifier import locate_certificate_file

            has_cert_file = locate_certificate_file(run_id) is not None
            is_sealed = bool(has_seal and has_cert_file)

            if is_sealed:
                status = "SEALED"
                lifecycle = "SEALED"
                trace_integrity = "COMPLETE"
            elif cached_result_status == "PASS":
                status = "PASSED"
                lifecycle = "COMPLETED"
                trace_integrity = "COMPLETE"
            elif cached_result_status == "FAIL":
                status = "FAILED"
                lifecycle = "FAILED"
                trace_integrity = "COMPLETE"
            else:
                # Inspect trace tail
                try:
                    size = os.path.getsize(tp)
                    mtime = os.path.getmtime(tp)
                    if size > 0:
                        with open(tp, "rb") as f:
                            if size > 32 * 1024:
                                f.seek(size - 32 * 1024)
                            content = f.read()

                        has_error = (
                            b'"event": "error"' in content
                            or b'"level": "error"' in content
                            or b'"status": "error"' in content
                            or b'"status": "certification_failed"' in content
                            or b'"event": "certification_failed"' in content
                            or b'"outcome": "EVALUATION_INVALID"' in content
                            or b'"status": "failure"' in content
                            or b'"status": "failed"' in content
                            or b'"status": "fail"' in content
                            or b'"passed": false' in content
                            or b'"passed":false' in content
                        )
                        has_end = (
                            b'"event": "run_end"' in content
                            or b'"event": "verification_certificate_issued"' in content
                        )

                        if has_end:
                            trace_integrity = "COMPLETE"
                            if has_error:
                                status = "FAILED"
                                lifecycle = "FAILED"
                            else:
                                status = "PASSED"
                                lifecycle = "COMPLETED"
                        elif has_error:
                            status = "FAILED"
                            lifecycle = "FAILED"
                        else:
                            if mtime > 0 and (time.time() - mtime > 300):
                                status = "STALLED"
                                lifecycle = "STALLED"
                            else:
                                status = "RUNNING"
                                lifecycle = "RUNNING"
                    else:
                        status = "RUNNING"
                        lifecycle = "RUNNING"
                except Exception as e:
                    logger.debug(f"Error inspecting trace for run {run_id}: {e}")
                    status = "RUNNING"
                    lifecycle = "RUNNING"

        summary = {
            "run_id": run_id,
            "scenario": scenario,
            "timestamp": timestamp,
            "identifier": identifier,
            "lifecycle": lifecycle,
            "status": status,
            "result_status": cached_result_status,
            "duration_seconds": duration_seconds,
            "execution_mode": exec_mode,
            "provisional": provisional,
            "trace_integrity": trace_integrity,
            "verification_status": auth_verdict,
            "has_certificate": has_certificate,
        }
        if cached.get("_fragment_path"):
            summary["_fragment_path"] = cached["_fragment_path"]
        if cached.get("path"):
            summary["path"] = cached["path"]

        return summary


__all__ = ["RunSummaryService", "TERMINAL_LIFECYCLE_STATUSES"]
