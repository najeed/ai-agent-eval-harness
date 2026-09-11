"""
eval_runner.services.certification

Authoritative Industrial Certification Domain Service.
Decoupled from presentation/route layers, providing server-authoritative
evaluation result derivation, fail-closed verification, and cryptographic signing.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from eval_runner import config
from eval_runner.certification_lock import PerRunCertificationLock
from eval_runner.trace_utils import resolve_trace_path
from eval_runner.utils.base import is_path_safe
from eval_runner.verifier import TraceVerifier

logger = logging.getLogger("eval_runner.services.certification")


class CertificationService:
    """
    Core Runtime Certification Authority.
    Derives evaluation status, score, and truth level strictly from immutable runtime evidence.
    """

    @staticmethod
    def read_run_truth_level(run_id: str) -> tuple[str | None, bool]:
        """
        Inspect the run's raw trace file to extract the authoritative execution mode.
        Returns (execution_mode, is_provisional).
        """
        trace = resolve_trace_path(run_id) if run_id else None
        if not trace or not trace.is_file() or not is_path_safe(trace, config.RUN_LOG_DIR):
            return None, False

        try:
            with open(trace, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    ev = json.loads(line)
                    if ev.get("event") not in ("run_start", "start"):
                        continue
                    data = ev.get("data", {}) or {}
                    meta = data.get("metadata") or ev.get("metadata") or {}
                    mode = (
                        data.get("execution_mode")
                        or meta.get("execution_mode")
                        or ev.get("execution_mode")
                    )
                    is_prov = bool(
                        data.get("provisional") or meta.get("provisional") or ev.get("provisional")
                    )
                    if is_prov or mode in ("simulated", "unknown"):
                        return mode or "simulated", True
                    if mode:
                        return mode, False
        except Exception as e:  # noqa: BLE001 - truth-level is best-effort metadata
            logger.debug("Could not read execution truth level for %s: %s", run_id, e)

        return None, False

    @staticmethod
    def extract_computed_run_outcome(vault_dir: Path, target_trace: Path) -> tuple[str, float]:
        """
        Extracts the authoritative computed outcome directly from the immutable execution trace.
        Never reads previous run_manifest.json to avoid circular trust.
        Consumes one authoritative final WorkflowOutcome/VerificationResult,
        identified by run + attempt, and rejects multiple/conflicting terminal decisions.
        Handled retries and intermediate failures do not override the final terminal decision.
        Returns (status, score). If unparseable or inconclusive, returns ("inconclusive", 0.0).
        """
        try:
            terminal_events: list[dict[str, Any]] = []
            with open(target_trace, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception as line_err:
                        logger.debug("Skipping unparseable trace line: %s", line_err)
                        continue

                    event_name = ev.get("event")
                    if event_name in (
                        "run_end",
                        "end",
                        "session_decision",
                        "evaluation_result",
                        "evaluation_verdict",
                        "workflow_verdict",
                    ):
                        terminal_events.append(ev)

            if not terminal_events:
                return "inconclusive", 0.0

            extracted_decisions: list[tuple[str, float]] = []
            for ev in terminal_events:
                data = ev.get("data", {}) or {}
                raw_status = (
                    data.get("status")
                    or ev.get("status")
                    or data.get("outcome")
                    or ev.get("outcome")
                    or ""
                )
                score_val = data.get("score") if data.get("score") is not None else ev.get("score")
                decision = data.get("decision") or ev.get("decision") or ""
                verdict = data.get("verdict") or ev.get("verdict") or ""

                passed_val = (
                    data.get("passed") if data.get("passed") is not None else ev.get("passed")
                )
                if passed_val is False:
                    raw_status = "fail"
                elif passed_val is True and not raw_status:
                    raw_status = "pass"

                if not raw_status and data.get("pass_at_k") is not None:
                    pak = float(data["pass_at_k"])
                    raw_status = "pass" if pak > 0 else "fail"
                    if score_val is None:
                        score_val = pak
                if not raw_status and data.get("all_pass") is not None:
                    raw_status = "pass" if data["all_pass"] else "fail"

                status_lower = str(raw_status).strip().lower()
                decision_upper = str(decision).strip().upper()
                verdict_upper = str(verdict).strip().upper()

                if (
                    status_lower in ("fail", "failed", "failure", "rejected")
                    or decision_upper in ("FAIL", "FAILED", "REJECTED", "UNVERIFIED")
                    or verdict_upper in ("FAIL", "FAILED", "POLICY_BREACH", "NOT_VERIFIED")
                ):
                    extracted_decisions.append(
                        ("fail", float(score_val if score_val is not None else 0.0))
                    )
                elif (
                    status_lower in ("pass", "passed", "success", "verified")
                    or decision_upper in ("PASS", "PASSED", "VERIFIED")
                    or verdict_upper in ("PASS", "PASSED", "VERIFIED")
                ):
                    extracted_decisions.append(
                        ("pass", float(score_val if score_val is not None else 1.0))
                    )
                elif decision_upper == "EVALUATION_INVALID" or status_lower == "evaluation_invalid":
                    extracted_decisions.append(("fail", 0.0))

            if not extracted_decisions:
                return "inconclusive", 0.0

            distinct_statuses = {d[0] for d in extracted_decisions}
            if len(distinct_statuses) > 1:
                logger.error("Conflicting terminal decisions in trace: %s", distinct_statuses)
                return "inconclusive", 0.0

            final_status, final_score = extracted_decisions[-1]
            return final_status, final_score
        except Exception as e:
            logger.debug("Failed parsing trace for computed outcome: %s", e)

        return "inconclusive", 0.0

    @classmethod
    def execute_industrial_certification(
        cls,
        run_id: str,
        identity_id: str = "system_id",
        status: str | None = None,
        score: float | None = None,
        policy_ref: str | None = None,
        ttl: int | None = None,
        behavioral_fingerprint_id: str | None = None,
        scenario_data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Authoritative Industrial Certification Service.
        Derives status and score strictly from the computed evaluation outcome.
        Fails closed if the outcome is inconclusive or cannot be positively verified.
        Holds an exclusive per-run certification lock across the entire transaction.
        """
        if (
            not run_id
            or not isinstance(run_id, str)
            or ".." in run_id
            or "/" in run_id
            or "\\" in run_id
        ):
            raise ValueError(f"Invalid or unsafe run_id: {run_id}")

        with PerRunCertificationLock(run_id):
            target_trace = resolve_trace_path(run_id)
            if (
                not target_trace
                or not is_path_safe(target_trace, config.RUN_LOG_DIR)
                or not target_trace.exists()
            ):
                logger.error(
                    f"   [Certification] 404 FAIL: Authoritative vault trace not found: {run_id}"
                )
                raise FileNotFoundError(f"Run vault not found for {run_id}")

            vault_dir = target_trace.parent

            # 1. Execution Truth Level Verification
            execution_mode, provisional = cls.read_run_truth_level(run_id)
            if provisional or execution_mode in ("simulated", "unknown"):
                logger.error(
                    "   [Certification] FAIL CLOSED: Cannot issue certification "
                    "for provisional/unknown run %s (mode=%s, provisional=%s)",
                    run_id,
                    execution_mode,
                    provisional,
                )
                raise ValueError(
                    f"Run {run_id} is provisional (execution mode undeclared or unknown); "
                    "cannot issue authoritative certification."
                )

            # 2. Immutable Evaluation Outcome Extraction (Zero Circular Manifest Reading)
            computed_status, computed_score = cls.extract_computed_run_outcome(
                vault_dir, target_trace
            )
            if computed_status == "inconclusive":
                logger.error(
                    "   [Certification] FAIL CLOSED: Inconclusive outcome for %s: missing terminal",
                    run_id,
                )
                raise ValueError(
                    f"Run {run_id} has inconclusive outcome: missing terminal evaluation events; "
                    "cannot issue authoritative certification."
                )
            elif computed_status == "fail":
                effective_status = "fail"
                effective_score = computed_score
            else:
                effective_status = "pass"
                effective_score = computed_score

            # Mandatory scenario and runtime metadata binding
            meta_binding: dict[str, Any] = {}
            try:
                with open(target_trace, encoding="utf-8") as tf:
                    for line in tf:
                        if not line.strip():
                            continue
                        try:
                            rec = json.loads(line)
                            if rec.get("event") == "run_start" or rec.get("scenario_id"):
                                for key in (
                                    "scenario_id",
                                    "scenario_hash",
                                    "policy_id",
                                    "evaluator_config_hash",
                                    "agent_id",
                                    "agent_identity",
                                ):
                                    if rec.get(key) and key not in meta_binding:
                                        meta_binding[key] = rec[key]
                        except Exception as parse_err:
                            logger.debug(
                                "Could not parse trace record for metadata binding: %s", parse_err
                            )
            except Exception as read_err:
                logger.debug("Could not read trace file for metadata binding: %s", read_err)

            # Scenario data resolution & authoritative scenario_hash verification (Defect #4)
            effective_scenario_data = scenario_data
            if effective_scenario_data is None and meta_binding.get("scenario_id"):
                try:
                    from eval_runner.loader import load_scenario

                    loaded = load_scenario(meta_binding["scenario_id"])
                    if isinstance(loaded, dict):
                        effective_scenario_data = loaded
                    elif isinstance(loaded, list) and loaded:
                        effective_scenario_data = loaded[0]
                except Exception as load_err:
                    logger.debug(
                        "Could not resolve scenario_data for '%s': %s",
                        meta_binding["scenario_id"],
                        load_err,
                    )

            if effective_scenario_data is not None:
                from agentv_runtime.manifest import compute_scenario_hash

                canonical_scen_hash = compute_scenario_hash(effective_scenario_data)
                claimed_hash = meta_binding.get("scenario_hash")
                if claimed_hash and claimed_hash != canonical_scen_hash:
                    raise ValueError(
                        f"ScenarioHashMismatch: trace claimed scenario_hash '{claimed_hash}' "
                        f"does not match actual computed scenario hash '{canonical_scen_hash}'"
                    )
                meta_binding["scenario_hash"] = canonical_scen_hash

            # 3. Cryptographic Signature Execution
            manifest = TraceVerifier.sign_trace(
                str(target_trace),
                run_id=run_id,
                identity_id=identity_id,
                compliance_status=effective_status,
                compliance_score=effective_score,
                policy_ref=policy_ref,
                ttl_days=ttl or config.GOVERNANCE_TTL_DAYS,
                metadata=meta_binding or None,
                execution_mode=execution_mode,
                provisional=provisional,
                behavioral_fingerprint_id=behavioral_fingerprint_id,
                scenario_data=effective_scenario_data,
            )

            manifest_path = vault_dir / "run_manifest.json"
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)

            is_pass = effective_status == "pass"
            return {
                "status": "certified" if is_pass else "attested_failed",
                "compliance_status": effective_status,
                "certified": is_pass,
                "certificate_issued": True,
                "run_id": run_id,
                "score": effective_score,
                "manifest": manifest,
            }


def execute_industrial_certification(
    run_id: str,
    identity_id: str = "system_id",
    status: str | None = None,
    score: float | None = None,
    policy_ref: str | None = None,
    ttl: int | None = None,
    behavioral_fingerprint_id: str | None = None,
    scenario_data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Top-level convenience function delegating to CertificationService."""
    return CertificationService.execute_industrial_certification(
        run_id=run_id,
        identity_id=identity_id,
        status=status,
        score=score,
        policy_ref=policy_ref,
        ttl=ttl,
        behavioral_fingerprint_id=behavioral_fingerprint_id,
        scenario_data=scenario_data,
    )
