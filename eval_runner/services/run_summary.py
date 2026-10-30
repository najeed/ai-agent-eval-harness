"""Provider-native run summary and verification status derivation."""

from __future__ import annotations

import logging
from typing import Any

from eval_runner.verifier import TraceVerifier

logger = logging.getLogger(__name__)

TERMINAL_LIFECYCLE_STATUSES = frozenset({"COMPLETED", "FAILED", "SEALED", "ABORTED"})


class RunSummaryService:
    """Derive summaries solely from the authoritative run-storage provider."""

    @staticmethod
    def _terminal_state(events: list[dict[str, Any]]) -> tuple[str, str, str]:
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
        outcome = (
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
        if data.get("passed") is True or outcome in {"PASS", "PASSED", "SUCCESS", "COMPLETED"}:
            return "PASSED", "COMPLETED", "COMPLETE"
        if data.get("passed") is False or outcome in {
            "FAIL",
            "FAILED",
            "ERROR",
            "EVALUATION_INVALID",
            "INVALID",
            "CERTIFICATION_FAILED",
        }:
            return "FAILED", "FAILED", "COMPLETE"
        if terminal.get("event") in {"run_end", "end"}:
            return "PASSED", "COMPLETED", "PARTIAL"
        return "INVALID", "INVALID", "INVALID"

    @staticmethod
    def _truth_level(events: list[dict[str, Any]], manifest: dict[str, Any]) -> tuple[str, bool]:
        execution_manifest = manifest.get("execution_manifest") or {}
        if not isinstance(execution_manifest, dict):
            execution_manifest = {}
        runtime_config = execution_manifest.get("runtime_config") or {}
        if not isinstance(runtime_config, dict):
            runtime_config = {}
        metadata = execution_manifest.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        mode = (
            manifest.get("execution_mode")
            or runtime_config.get("execution_mode")
            or metadata.get("execution_mode")
        )
        provisional = bool(manifest.get("provisional"))
        for event in events:
            if event.get("event") not in {"run_start", "start"}:
                continue
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            metadata = data.get("metadata") or event.get("metadata") or {}
            mode = (
                mode
                or data.get("execution_mode")
                or metadata.get("execution_mode")
                or event.get("execution_mode")
            )
            provisional = provisional or bool(
                data.get("provisional") or metadata.get("provisional") or event.get("provisional")
            )
            break
        mode_text = str(mode or "unknown")
        return mode_text, bool(provisional or mode_text.lower() not in {"live", "hybrid"})

    @classmethod
    def get_authoritative_verdict(
        cls, run_id: str, *, run_store: Any, context: dict[str, Any] | None = None
    ) -> str:
        """Verify only provider-owned manifest and trace bytes for ``run_id``."""
        if not run_id:
            return "NOT_EXECUTED"
        result = TraceVerifier.verify_run(run_id, run_store=run_store, context=context)
        status = result["verification_status"]
        return {"NOT_FOUND": "NOT_EXECUTED", "UNVERIFIED": "UNKNOWN"}.get(status, status)

    @classmethod
    def compute_summary(
        cls,
        run_id: str,
        *,
        run_store: Any,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a presentation summary without reading a run directory or reports vault."""
        run = run_store.get_run(run_id, context=context) if hasattr(run_store, "get_run") else None
        if run is None:
            return {
                "run_id": run_id,
                "status": "NOT_EXECUTED",
                "lifecycle": "NOT_EXECUTED",
                "verification_status": "NOT_EXECUTED",
            }
        manifest = (
            (
                run_store.get_manifest(run_id, context=context)
                if hasattr(run_store, "get_manifest")
                else None
            )
            or run.get("manifest")
            or {}
        )
        events = (
            run_store.get_events(run_id, offset=0, limit=10_000_000, context=context)
            if hasattr(run_store, "get_events")
            else []
        )
        verdict = cls.get_authoritative_verdict(run_id, run_store=run_store, context=context)
        status, lifecycle, integrity = cls._terminal_state(events)
        if verdict == "VERIFIED":
            status, lifecycle, integrity = "CERTIFIED", "SEALED", "COMPLETE"
        elif verdict == "VERIFIED_PROVISIONAL":
            status, lifecycle, integrity = "PROVISIONAL", "SEALED", "COMPLETE"
        elif verdict == "ATTESTED_FAIL":
            status, lifecycle, integrity = "ATTESTED_FAIL", "SEALED", "COMPLETE"
        elif not events:
            status = lifecycle = str(run.get("status") or "OPEN").upper()
        mode, provisional = cls._truth_level(events, manifest)
        package = manifest.get("verification_package") or manifest
        compliance = manifest.get("compliance") or {}
        score = run.get("score", package.get("score", compliance.get("score")))
        if score is None:
            score = (
                1.0
                if status in {"CERTIFIED", "PASSED", "SEALED"}
                else 0.0
                if status == "FAILED"
                else None
            )
        failed_oracles = [
            item
            for item in package.get("executed_oracle_results", [])
            if isinstance(item, dict)
            and (item.get("passed") is False or str(item.get("outcome", "")).upper() == "FAIL")
        ]
        reasons = [
            f"Oracle '{item.get('oracle_id', 'unknown')}' failed." for item in failed_oracles
        ]
        for event in events:
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            if event.get("is_root_cause") or data.get("is_root_cause"):
                message = (
                    event.get("message")
                    or data.get("message")
                    or event.get("error")
                    or data.get("error")
                )
                if message:
                    reasons.append(f"Root cause: {message}")
        timestamp = run.get("created_at") or run.get("timestamp")
        if not timestamp and events:
            first = events[0]
            data = first.get("data") if isinstance(first.get("data"), dict) else {}
            timestamp = first.get("timestamp") or first.get("_ts_iso") or data.get("timestamp")
        scenario = next(
            (
                value
                for value in (
                    run.get("scenario"),
                    run.get("scenario_id"),
                    manifest.get("scenario_id"),
                    (manifest.get("execution_manifest") or {}).get("scenario_id"),
                )
                if value and str(value).strip().lower() != "unknown"
            ),
            "unknown",
        )
        return {
            "run_id": run_id,
            "scenario": scenario,
            "timestamp": timestamp,
            "start_time": timestamp,
            "identifier": (
                run.get("identifier")
                or run.get("agent_id")
                or ((manifest.get("execution_manifest") or {}).get("agent_config") or {}).get(
                    "agent_id"
                )
                or ((manifest.get("execution_manifest") or {}).get("agent_config") or {}).get(
                    "agent_name"
                )
                or timestamp
            ),
            "lifecycle": lifecycle,
            "status": status,
            "result_status": run.get("result_status"),
            "duration_seconds": run.get("duration_seconds"),
            "score": score,
            "score_reason": reasons[0] if reasons else None,
            "score_category": "ORACLE_DEFECT" if failed_oracles else None,
            "failure_reasons": reasons,
            "failed_oracles": failed_oracles,
            "execution_mode": mode,
            "provisional": provisional,
            "trace_integrity": integrity,
            "verification_status": verdict,
            "has_certificate": bool(
                manifest.get("trace_hash")
                and (manifest.get("signature") or manifest.get("provenance_chain"))
            ),
            "target": (
                run.get("target")
                or ((manifest.get("execution_manifest") or {}).get("agent_config") or {}).get(
                    "configured_model_id"
                )
                or ((manifest.get("execution_manifest") or {}).get("agent_config") or {}).get(
                    "model"
                )
                or ((manifest.get("execution_manifest") or {}).get("agent_config") or {}).get(
                    "agent_name"
                )
                or ((manifest.get("execution_manifest") or {}).get("agent_config") or {}).get(
                    "agent_id"
                )
            ),
            "model": (
                run.get("model")
                or ((manifest.get("execution_manifest") or {}).get("agent_config") or {}).get(
                    "configured_model_id"
                )
                or ((manifest.get("execution_manifest") or {}).get("agent_config") or {}).get(
                    "model"
                )
            ),
            "agent": (
                run.get("agent")
                or ((manifest.get("execution_manifest") or {}).get("agent_config") or {}).get(
                    "agent_name"
                )
                or ((manifest.get("execution_manifest") or {}).get("agent_config") or {}).get(
                    "agent_id"
                )
            ),
        }


__all__ = ["RunSummaryService", "TERMINAL_LIFECYCLE_STATUSES"]
