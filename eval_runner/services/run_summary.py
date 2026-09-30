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

    @staticmethod
    def _parsed_terminal_state(trace_path: Any, run_id: str) -> tuple[str, str, str]:
        """Derive execution state from parsed terminal evidence, never text search.

        Returns ``(status, lifecycle, trace_integrity)``.  A malformed record
        invalidates the whole stream; an earlier error does not override a
        later authoritative terminal PASS (for example after a retry or
        compensation).
        """
        from eval_runner.services.certification import CertificationService

        try:
            events = CertificationService.parse_trace_strict(trace_path, run_id)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            # Status rendering supports legacy framed logs whose non-event
            # prefix is not JSONL.  Certification still uses the strict parser
            # and will reject such a trace; this fallback never claims COMPLETE
            # integrity without a parsed terminal carrier.
            events = []
            try:
                with open(trace_path, encoding="utf-8") as trace_file:
                    for line in trace_file:
                        candidate = line[line.find("{") :] if "{" in line else ""
                        if not candidate:
                            continue
                        parsed = json.loads(candidate)
                        if isinstance(parsed, dict):
                            events.append(parsed)
            except (OSError, ValueError, json.JSONDecodeError):
                logger.warning("Trace %s is structurally invalid: %s", run_id, exc)
                return "INVALID", "INVALID", "INVALID"

        terminal: dict[str, Any] | None = None
        for event in events:
            if event.get("event") in {
                "run_end",
                "end",
                "session_decision",
                "evaluation_result",
                "evaluation_verdict",
                "workflow_verdict",
                "certification_failed",
            }:
                terminal = event

        if terminal is None:
            return "RUNNING", "RUNNING", "PARTIAL"
        if terminal.get("event") == "certification_failed":
            return "FAILED", "FAILED", "COMPLETE"

        data = terminal.get("data") if isinstance(terminal.get("data"), dict) else terminal
        raw_outcome = (
            str(
                data.get("outcome")
                or data.get("status")
                or data.get("decision")
                or data.get("verdict")
                or ""
            )
            .strip()
            .upper()
        )
        if data.get("passed") is True or raw_outcome in {"PASS", "PASSED", "SUCCESS", "COMPLETED"}:
            return "PASSED", "COMPLETED", "COMPLETE"
        if data.get("passed") is False or raw_outcome in {
            "FAIL",
            "FAILED",
            "ERROR",
            "EVALUATION_INVALID",
            "INVALID",
            "CERTIFICATION_FAILED",
        }:
            return "FAILED", "FAILED", "COMPLETE"
        # Legacy run_end records carried no typed outcome; their presence is a
        # completed successful run for display compatibility only.
        if terminal.get("event") in {"run_end", "end"}:
            return "PASSED", "COMPLETED", "PARTIAL"
        return "INVALID", "INVALID", "INVALID"

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

        # ``run_manifest.json`` may be the execution manifest.  Certificate
        # presence is meaningful only when a VC artifact binds ``trace_hash``.
        from eval_runner.verifier import locate_certificate_file

        certificate_path = locate_certificate_file(run_id)
        has_certificate = certificate_path is not None

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

        trace_integrity = "RECOVERED" if cached.get("_fragment_path") else "PARTIAL"

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
            else:
                status, lifecycle, trace_integrity = cls._parsed_terminal_state(tp, run_id)
                if status == "RUNNING" and time.time() - os.path.getmtime(tp) > 300:
                    status = "STALLED"
                    lifecycle = "STALLED"

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
