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

from agentv_runtime.finalization import EvaluatorFinalizationRecord
from eval_runner import config
from eval_runner.certification_lock import PerRunCertificationLock
from eval_runner.trace_utils import resolve_trace_path
from eval_runner.utils.base import is_path_safe
from eval_runner.verifier import TraceVerifier

logger = logging.getLogger("eval_runner.services.certification")

EVIDENCE_EVENT_NAMES = {
    "step_executed",
    "step_complete",
    "tool_call",
    "tool_result",
    "external_tool_call",
    "external_tool_result",
    "metric",
    "assertion",
    "oracle_result",
    "state_hygiene",
    "state_parity",
    "node_verdict",
    "turn_end",
    "turn_start",
    "event_recorded",
}


class CertificationService:
    """
    Core Runtime Certification Authority.
    Derives evaluation status, score, and truth level strictly from immutable runtime evidence.
    """

    @staticmethod
    def parse_trace_strict(target_trace: Path, run_id: str | None = None) -> list[dict[str, Any]]:
        """Parse every nonblank JSONL record once; malformed/foreign records fail closed."""
        events: list[dict[str, Any]] = []
        with open(target_trace, encoding="utf-8") as trace_file:
            for line_number, line in enumerate(trace_file, start=1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"MalformedTraceRecord:{line_number}") from exc
                if not isinstance(event, dict):
                    raise ValueError(f"InvalidTraceRecord:{line_number}: expected object")
                event_run_id = event.get("run_id") or (event.get("data") or {}).get("run_id")
                if run_id and event_run_id and str(event_run_id) != run_id:
                    raise ValueError(f"ForeignTraceRecord:{line_number}: run_id mismatch")
                events.append(event)
        return events

    @classmethod
    def read_run_truth_level(cls, run_id: str) -> tuple[str | None, bool]:
        """
        Inspect the run's raw trace file to extract the authoritative execution mode.
        (Defect T1): Explicit, recognized execution_mode is a hard prerequisite.
        None, unknown, simulated, or provisional mode marks provisional=True.
        Returns (execution_mode, is_provisional).
        """
        trace = resolve_trace_path(run_id) if run_id else None
        if not trace or not trace.is_file() or not is_path_safe(trace, config.RUN_LOG_DIR):
            return None, False

        try:
            for ev in cls.parse_trace_strict(trace, run_id):
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
                if not mode:
                    return "unknown", True
                mode_clean = str(mode).strip().lower()
                if (
                    is_prov
                    or mode_clean in ("simulated", "unknown")
                    or mode_clean not in ("live", "hybrid")
                ):
                    return mode, True
                return mode, False
            return "unknown", True
        except Exception as e:  # noqa: BLE001
            logger.debug("Error reading execution truth level for %s: %s", run_id, e)
            return "unknown", True

    @classmethod
    def count_assertion_and_evidence_nodes(cls, target_trace: Path) -> int:
        """Counts substantive evaluation assertions and evidence events in the trace."""
        count = 0
        if not target_trace.exists():
            return 0
        try:
            for ev in cls.parse_trace_strict(target_trace):
                event_name = ev.get("event")
                if event_name in EVIDENCE_EVENT_NAMES:
                    count += 1
                elif "assertion" in ev or "oracle_results" in ev or "metrics" in ev:
                    count += 1
                elif isinstance(ev.get("data"), dict):
                    d = ev["data"]
                    if "assertion" in d or "oracle_results" in d or "metrics" in d:
                        count += 1
        except Exception as e:
            logger.debug("Error counting evidence nodes in %s: %s", target_trace, e)
        return count

    @classmethod
    def extract_finalization_record(cls, target_trace: Path) -> EvaluatorFinalizationRecord | None:
        """Extracts and validates an EvaluatorFinalizationRecord if present in the trace."""
        if not target_trace.exists():
            return None
        try:
            # Validate the complete raw stream before any selective derivation.
            cls.parse_trace_strict(target_trace)
            with open(target_trace, encoding="utf-8") as tf:
                for line in tf:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        ev = json.loads(stripped)
                    except Exception:
                        continue
                    fin_payload = None
                    if ev.get("event") == "evaluator_finalization":
                        fin_payload = ev.get("data") if isinstance(ev.get("data"), dict) else ev
                    elif ev.get("event") in ("run_end", "end"):
                        ev_data = ev.get("data") if isinstance(ev.get("data"), dict) else ev
                        if isinstance(ev_data.get("finalization"), dict):
                            fin_payload = ev_data["finalization"]
                        elif isinstance(ev.get("finalization"), dict):
                            fin_payload = ev["finalization"]

                    if fin_payload:
                        rec = EvaluatorFinalizationRecord.from_dict(
                            fin_payload, require_authoritative=True
                        )

                        # Authoritative Evaluator Signature Verification (Defect 1)
                        from eval_runner.identity import IdentityService

                        eval_pub = IdentityService.get_public_key(
                            rec.evaluator_identity, auto_provision=False
                        )
                        if not eval_pub:
                            raise ValueError(
                                f"EvaluatorIdentityUntrusted: evaluator '{rec.evaluator_identity}' "
                                "is not authorized in external trust root."
                            )
                        if not rec.verify_signature(eval_pub):
                            raise ValueError(
                                f"EvaluatorSignatureInvalid: signature for "
                                f"'{rec.evaluator_identity}' failed cryptographic verification."
                            )
                        return rec
        except ValueError:
            raise
        except Exception as e:
            logger.debug("Error extracting finalization record from %s: %s", target_trace, e)
        return None

    @staticmethod
    def extract_computed_run_outcome(vault_dir: Path, target_trace: Path) -> tuple[str, float]:
        """
        Extracts the authoritative computed outcome directly from the immutable trace.
        Never reads previous run_manifest.json to avoid circular trust.
        Consumes one authoritative final WorkflowOutcome or EvaluatorFinalizationRecord,
        rejects multiple conflicting or duplicate terminal decisions (Defect T4),
        and rejects any outcome event appended after finalization (Defect T4).
        Returns (status, score). If unparseable or inconclusive, returns ("inconclusive", 0.0).
        """
        try:
            CertificationService.parse_trace_strict(target_trace)
            finalization_seen = False
            finalization_decision: tuple[str, float, str] | None = None
            extracted_decisions: list[tuple[str, float, str]] = []

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

                    fin_payload = None
                    if event_name == "evaluator_finalization":
                        fin_payload = ev.get("data") if isinstance(ev.get("data"), dict) else ev
                    elif event_name in ("run_end", "end"):
                        ev_data = ev.get("data") if isinstance(ev.get("data"), dict) else ev
                        if isinstance(ev_data.get("finalization"), dict):
                            fin_payload = ev_data["finalization"]
                        elif isinstance(ev.get("finalization"), dict):
                            fin_payload = ev["finalization"]

                    if finalization_seen:
                        # Defect T4: Reject any event appended after finalization marker
                        if fin_payload or event_name == "evaluator_finalization":
                            logger.error("Multiple evaluator finalization records in trace")
                        else:
                            logger.error(
                                "Monotonic terminal boundary violation: "
                                "Event '%s' found after finalization marker",
                                event_name,
                            )
                        return "inconclusive", 0.0

                    if fin_payload:
                        try:
                            rec = EvaluatorFinalizationRecord.from_dict(
                                fin_payload, require_authoritative=True
                            )

                            # Authoritative Evaluator Signature Verification (Defect 1)
                            from eval_runner.identity import IdentityService

                            eval_pub = IdentityService.get_public_key(
                                rec.evaluator_identity, auto_provision=False
                            )
                            if not eval_pub or not rec.verify_signature(eval_pub):
                                logger.error(
                                    "Invalid evaluator signature for '%s' in trace",
                                    rec.evaluator_identity,
                                )
                                return "inconclusive", 0.0

                            finalization_seen = True
                            finalization_decision = (
                                rec.outcome.lower(),
                                float(rec.score),
                                "evaluator_finalization",
                            )
                        except Exception as fin_err:
                            logger.error(
                                "Failed validating EvaluatorFinalizationRecord: %s", fin_err
                            )
                            return "inconclusive", 0.0
                        continue

                    if event_name in (
                        "run_end",
                        "end",
                        "session_decision",
                        "evaluation_result",
                        "evaluation_verdict",
                        "workflow_verdict",
                    ):
                        data = ev.get("data", {}) or {}
                        raw_status = (
                            data.get("status")
                            or ev.get("status")
                            or data.get("outcome")
                            or ev.get("outcome")
                            or ""
                        )
                        score_val = (
                            data.get("score") if data.get("score") is not None else ev.get("score")
                        )
                        decision = data.get("decision") or ev.get("decision") or ""
                        verdict = data.get("verdict") or ev.get("verdict") or ""

                        passed_val = (
                            data.get("passed")
                            if data.get("passed") is not None
                            else ev.get("passed")
                        )
                        verified_val = (
                            data.get("verified")
                            if data.get("verified") is not None
                            else ev.get("verified")
                        )
                        if passed_val is False or verified_val is False:
                            raw_status = "fail"
                        elif (passed_val is True or verified_val is True) and (
                            not raw_status
                            or str(raw_status).strip().lower()
                            in ("completed", "execution_completed", "done", "success")
                        ):
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

                        dec_status = None
                        dec_score = 0.0

                        if (
                            status_lower in ("fail", "failed", "failure", "rejected")
                            or decision_upper
                            in ("FAIL", "FAILED", "REJECTED", "UNVERIFIED", "POLICY_BREACH")
                            or verdict_upper in ("FAIL", "FAILED", "POLICY_BREACH", "NOT_VERIFIED")
                        ):
                            dec_status = "fail"
                            dec_score = float(score_val if score_val is not None else 0.0)
                        elif (
                            status_lower in ("pass", "passed", "success", "verified")
                            or decision_upper in ("PASS", "PASSED", "VERIFIED")
                            or verdict_upper in ("PASS", "PASSED", "VERIFIED")
                        ):
                            dec_status = "pass"
                            dec_score = float(score_val if score_val is not None else 1.0)
                        elif (
                            decision_upper == "EVALUATION_INVALID"
                            or status_lower == "evaluation_invalid"
                        ):
                            dec_status = "fail"
                            dec_score = 0.0

                        if dec_status is not None:
                            extracted_decisions.append((dec_status, dec_score, event_name))

            if finalization_decision is not None:
                final_status, final_score, _ = finalization_decision
                for prev_status, _prev_score, ev_name in extracted_decisions:
                    if prev_status != final_status:
                        logger.error(
                            "Contradictory terminal decisions in trace: event '%s' declared '%s' "
                            "while evaluator finalization declared '%s'. Finalization must confirm "
                            "a consistent terminal decision, not override contradiction.",
                            ev_name,
                            prev_status,
                            final_status,
                        )
                        return "inconclusive", 0.0
                return final_status, final_score

            if not extracted_decisions:
                return "inconclusive", 0.0

            # Defect T4: Reject multiple authoritative terminal decisions
            if len(extracted_decisions) > 1:
                logger.error(
                    "Multiple authoritative terminal decisions detected without finalization "
                    "record (%d decisions): %s",
                    len(extracted_decisions),
                    [d[2] for d in extracted_decisions],
                )
                return "inconclusive", 0.0

            final_status, final_score, _ = extracted_decisions[-1]
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
        trace_path: str | Path | None = None,
        artifact_store: Any | None = None,
    ) -> dict[str, Any]:
        """
        Authoritative Industrial Certification Service.
        Derives status and score strictly from the computed evaluation outcome.
        Fails closed if the outcome is inconclusive, unverified, or provisional.
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

        lock = PerRunCertificationLock(run_id)
        with lock:
            if trace_path:
                candidate_trace = Path(trace_path)
                if not candidate_trace.is_absolute():
                    candidate_trace = (config.RUN_LOG_DIR / candidate_trace).resolve()
                if (
                    not is_path_safe(candidate_trace, config.RUN_LOG_DIR)
                    or not candidate_trace.exists()
                ):
                    logger.error(
                        "   [Certification] 404 FAIL: Supplied trace path not found or unsafe: %s",
                        trace_path,
                    )
                    raise FileNotFoundError(f"Run vault not found for {run_id}")
                if (
                    candidate_trace.name == "run.jsonl"
                    and candidate_trace.parent == Path(config.RUN_LOG_DIR).resolve()
                ):
                    raise ValueError(
                        f"SharedMasterLogCertificationForbidden: Cannot certify shared "
                        f"master log '{trace_path}'. Only canonical per-run vault traces "
                        "are certifiable."
                    )
                target_trace = candidate_trace
            else:
                target_trace = resolve_trace_path(run_id, allow_master_recovery=False)
                if (
                    not target_trace
                    or not is_path_safe(target_trace, config.RUN_LOG_DIR)
                    or not target_trace.exists()
                ):
                    logger.error(
                        "   [Certification] 404 FAIL: Authoritative vault trace not found: %s",
                        run_id,
                    )
                    raise FileNotFoundError(f"Run vault not found for {run_id}")

            vault_dir = target_trace.parent

            # Validate the complete physical JSONL stream before any decision,
            # metadata, or evidence derivation.  Later projections may select
            # records for their own purposes, but none may silently discard a
            # malformed or cross-run record.
            cls.parse_trace_strict(target_trace, run_id)

            # 1. Execution Truth Level Verification (Defect T1: 'live' execution only)
            execution_mode, provisional = cls.read_run_truth_level(run_id)
            clean_mode = str(execution_mode).strip().lower() if execution_mode else ""
            if provisional or not clean_mode or clean_mode != "live":
                logger.error(
                    "   [Certification] FAIL CLOSED: Cannot issue authoritative certification "
                    "for non-live run %s (mode=%s, provisional=%s)",
                    run_id,
                    execution_mode,
                    provisional,
                )
                raise ValueError(
                    f"Run {run_id} is provisional (execution mode '{clean_mode}' is not 'live'); "
                    "cannot issue authoritative certification."
                )

            # 2. Immutable Evaluation Outcome Extraction (Zero Circular Manifest Reading)
            computed_status, computed_score = cls.extract_computed_run_outcome(
                vault_dir, target_trace
            )
            if computed_status == "inconclusive":
                logger.error(
                    "   [Certification] FAIL CLOSED: Inconclusive outcome for %s: "
                    "missing or conflicting terminal",
                    run_id,
                )
                raise ValueError(
                    f"Run {run_id} has inconclusive outcome: missing terminal evaluation events; "
                    "cannot issue authoritative certification."
                )

            # Mandatory EvaluatorFinalizationRecord check (P0)
            fin_record = cls.extract_finalization_record(target_trace)
            if fin_record is None:
                logger.error(
                    "   [Certification] FAIL CLOSED: Trace %s missing mandatory "
                    "EvaluatorFinalizationRecord",
                    run_id,
                )
                raise ValueError(
                    f"Run {run_id} missing mandatory authoritative EvaluatorFinalizationRecord; "
                    "cannot issue certification."
                )

            if fin_record.run_id != run_id:
                raise ValueError(
                    f"FinalizationRunIdMismatch: finalization record run_id '{fin_record.run_id}' "
                    f"does not match run '{run_id}'"
                )

            effective_status = "pass" if fin_record.outcome.lower() == "pass" else "fail"
            effective_score = float(fin_record.score)

            # Mandatory scenario and runtime metadata binding
            meta_binding: dict[str, Any] = {}
            embedded_scenario_data: dict[str, Any] | None = None
            raw_events: list[tuple[dict[str, Any], str]] = []
            try:
                with open(target_trace, encoding="utf-8") as tf:
                    for line in tf:
                        stripped = line.strip()
                        if not stripped:
                            continue
                        try:
                            rec = json.loads(stripped)
                            ev_name = rec.get("event")
                            rec_data = rec.get("data") if isinstance(rec.get("data"), dict) else {}
                            # Finalization is computed before the terminal RUN_END
                            # record is emitted.  That record embeds the signed
                            # finalization itself and its assertion carrier; feeding
                            # it back into graph reconstruction would create a
                            # self-referential second evidence root.  Bind the root
                            # to the exact pre-finalization raw JSONL lines instead.
                            if not (
                                ev_name in ("run_end", "verification_decision", "session_decision")
                                and isinstance(
                                    rec.get("finalization") or rec_data.get("finalization"), dict
                                )
                            ):
                                raw_events.append((rec, line.rstrip("\r\n")))
                            has_scen = bool(rec.get("scenario_id") or rec_data.get("scenario_id"))
                            if ev_name in ("run_start", "start") or has_scen:
                                for key in (
                                    "scenario_id",
                                    "scenario_hash",
                                    "scenario_version",
                                    "policy_id",
                                    "evaluator_config_hash",
                                    "execution_manifest_hash",
                                    "agent_id",
                                    "agent_identity",
                                ):
                                    val = rec.get(key) or rec_data.get(key)
                                    if val and key not in meta_binding:
                                        meta_binding[key] = val
                                if not embedded_scenario_data:
                                    scen_cand = rec.get("scenario_data") or rec_data.get(
                                        "scenario_data"
                                    )
                                    if isinstance(scen_cand, dict):
                                        embedded_scenario_data = scen_cand
                        except Exception as parse_err:
                            logger.debug(
                                "Could not parse trace record for metadata binding: %s", parse_err
                            )
            except Exception as read_err:
                logger.debug("Could not read trace file for metadata binding: %s", read_err)

            # Reconstruct Evidence Graph using authoritative required_oracle_ids.
            from agentv_runtime.evidence_graph import build_evidence_graph_from_events

            ev_graph = build_evidence_graph_from_events(
                raw_events, required_oracle_ids=fin_record.required_oracle_ids
            )
            recomputed_evidence_root = ev_graph.get("evidence_root_hash", "")

            # Single Canonical Evidence-Root Cross-Check (Defect 2)
            if fin_record.evidence_root_hash != recomputed_evidence_root:
                raise ValueError(
                    f"EvidenceRootMismatch: finalization record evidence_root_hash "
                    f"'{fin_record.evidence_root_hash}' does not match recomputed "
                    f"evidence graph root '{recomputed_evidence_root}'"
                )

            if not ev_graph.get("is_complete_provenance", True):
                raise ValueError(
                    "DirectProvenanceViolation: Evidence graph contains unresolved or "
                    "carrier fallback provenance."
                )

            # Mandatory Scenario identity & authoritative scenario_hash verification (Defect T3)
            effective_scenario_data = scenario_data
            target_scen_id = fin_record.scenario_id
            if scenario_data and isinstance(scenario_data, dict):
                scen_id_in_arg = scenario_data.get("id") or scenario_data.get("scenario_id")
                if scen_id_in_arg and scen_id_in_arg != target_scen_id:
                    raise ValueError(
                        f"ScenarioIdMismatch: scenario_data id '{scen_id_in_arg}' does not match "
                        f"finalization record scenario_id '{target_scen_id}'"
                    )

            if effective_scenario_data is None and embedded_scenario_data is not None:
                effective_scenario_data = embedded_scenario_data

            if effective_scenario_data is None:
                # Prefer per-run immutable snapshot first (P1-1)
                resolved_snapshot = vault_dir / "scenario_resolved.json"
                if resolved_snapshot.exists():
                    try:
                        with open(resolved_snapshot, encoding="utf-8") as rf:
                            loaded_snap = json.load(rf)
                            if isinstance(loaded_snap, dict):
                                effective_scenario_data = loaded_snap
                    except Exception as snap_err:
                        logger.debug("Could not read scenario_resolved.json: %s", snap_err)

            if effective_scenario_data is None:
                try:
                    from eval_runner.loader import load_scenario

                    loaded = load_scenario(target_scen_id)
                    if isinstance(loaded, dict):
                        effective_scenario_data = loaded
                    elif isinstance(loaded, list) and loaded:
                        effective_scenario_data = loaded[0]
                except Exception as load_err:
                    logger.debug(
                        "Could not resolve scenario_data for '%s': %s",
                        target_scen_id,
                        load_err,
                    )

            if effective_scenario_data is None:
                raise ValueError(
                    f"Run {run_id} cannot resolve authoritative scenario definition for "
                    f"'{target_scen_id}'; certification blocked (Defect T3)."
                )

            from agentv_runtime.manifest import compute_scenario_hash

            canonical_scen_hash = compute_scenario_hash(effective_scenario_data)
            if fin_record.scenario_hash != canonical_scen_hash:
                raise ValueError(
                    f"ScenarioHashMismatch: trace claimed scenario_hash "
                    f"'{fin_record.scenario_hash}' does not match actual computed scenario hash "
                    f"'{canonical_scen_hash}'"
                )

            # Persist immutable per-run snapshot if not already present (P1-1 & P0-6)
            scen_resolved_path = vault_dir / "scenario_resolved.json"
            if not scen_resolved_path.exists():
                try:
                    scen_resolved_path.write_text(
                        json.dumps(effective_scenario_data, indent=2), encoding="utf-8"
                    )
                except Exception as scen_save_err:
                    logger.error(
                        "Failed to persist mandatory scenario_resolved.json snapshot for %s: %s",
                        run_id,
                        scen_save_err,
                    )
                    raise ValueError(
                        f"FailedToPersistScenarioSnapshot: Mandatory scenario_resolved.json "
                        f"snapshot could not be persisted for run '{run_id}': {scen_save_err}"
                    ) from scen_save_err

            meta_binding["scenario_id"] = fin_record.scenario_id
            meta_binding["scenario_version"] = fin_record.scenario_version
            meta_binding["scenario_hash"] = fin_record.scenario_hash
            meta_binding["evaluator_config_hash"] = fin_record.evaluator_config_hash
            meta_binding["execution_manifest_hash"] = fin_record.execution_manifest_hash
            meta_binding["evidence_root_hash"] = fin_record.evidence_root_hash
            meta_binding["evaluator_finalization_id"] = fin_record.finalization_id
            meta_binding["evaluator_identity"] = fin_record.evaluator_identity
            meta_binding["required_oracle_ids"] = fin_record.required_oracle_ids

            # Authoritative ExecutionManifest binding verification (Defect 5)
            manifest_file = vault_dir / "execution_manifest.json"
            if not manifest_file.exists():
                raise ValueError(
                    f"ExecutionManifestMissing: Run {run_id} missing mandatory "
                    "execution_manifest.json artifact; cannot issue authoritative "
                    "certification without physical manifest."
                )
            try:
                from agentv_runtime.manifest import ExecutionManifest

                with open(manifest_file, encoding="utf-8") as mf:
                    m_data = json.load(mf)
                exec_manifest = ExecutionManifest.from_dict(m_data)
                actual_manifest_hash = exec_manifest.compute_manifest_hash()
                if actual_manifest_hash != fin_record.execution_manifest_hash:
                    raise ValueError(
                        f"ManifestHashMismatch: finalization record manifest_hash "
                        f"'{fin_record.execution_manifest_hash}' does not match actual "
                        f"execution manifest hash '{actual_manifest_hash}'"
                    )

                # Semantic cross-binding (P0-4 Fix)
                if exec_manifest.scenario_id != fin_record.scenario_id:
                    raise ValueError(
                        f"ManifestScenarioIdMismatch: manifest scenario_id "
                        f"'{exec_manifest.scenario_id}' does not match finalization record "
                        f"scenario_id '{fin_record.scenario_id}'"
                    )
                if exec_manifest.scenario_version != fin_record.scenario_version:
                    raise ValueError(
                        f"ManifestScenarioVersionMismatch: manifest scenario_version "
                        f"'{exec_manifest.scenario_version}' does not match finalization record "
                        f"scenario_version '{fin_record.scenario_version}'"
                    )
                if exec_manifest.scenario_hash != fin_record.scenario_hash:
                    raise ValueError(
                        f"ManifestScenarioHashMismatch: manifest scenario_hash "
                        f"'{exec_manifest.scenario_hash}' does not match finalization record "
                        f"scenario_hash '{fin_record.scenario_hash}'"
                    )
                manifest_mode = exec_manifest.runtime_config.get(
                    "execution_mode"
                ) or exec_manifest.metadata.get("execution_mode")
                if manifest_mode and clean_mode and manifest_mode != clean_mode:
                    raise ValueError(
                        f"ManifestExecutionModeMismatch: manifest execution_mode '{manifest_mode}' "
                        f"does not match certified execution mode '{clean_mode}'"
                    )
                manifest_eval_cfg = exec_manifest.runtime_config.get(
                    "evaluator_config_hash"
                ) or exec_manifest.metadata.get("evaluator_config_hash")
                if (
                    manifest_eval_cfg
                    and fin_record.evaluator_config_hash
                    and manifest_eval_cfg != fin_record.evaluator_config_hash
                ):
                    raise ValueError(
                        f"ManifestEvaluatorConfigHashMismatch: manifest evaluator_config_hash "
                        f"'{manifest_eval_cfg}' does not match finalization record "
                        f"evaluator_config_hash '{fin_record.evaluator_config_hash}'"
                    )
                manifest_reqs = set(
                    exec_manifest.metadata.get("required_oracle_ids")
                    or exec_manifest.runtime_config.get("required_oracle_ids")
                    or []
                )
                fin_reqs = set(fin_record.required_oracle_ids or [])
                from eval_runner.runner import compile_required_oracle_ids

                scenario_reqs = set(
                    compile_required_oracle_ids(effective_scenario_data)
                    if isinstance(effective_scenario_data, dict)
                    else []
                )
                # Empty is meaningful: a manifest/finalization disagreement must
                # never erase mandatory evidence by intersection.
                if manifest_reqs != fin_reqs:
                    raise ValueError(
                        "ManifestRequiredOracleMismatch: execution manifest and "
                        f"finalization inventories differ: manifest={sorted(manifest_reqs)}, "
                        f"finalization={sorted(fin_reqs)}"
                    )
                if not (scenario_reqs == manifest_reqs == fin_reqs):
                    raise ValueError(
                        "RequiredOracleInventoryMismatch: scenario, execution manifest, and "
                        f"finalization inventories differ: scenario={sorted(scenario_reqs)}, "
                        f"manifest={sorted(manifest_reqs)}, finalization={sorted(fin_reqs)}"
                    )

                # Only evaluate evidence completeness after the independently
                # resolved scenario, physical manifest, and signed finalization
                # agree on the full mandatory inventory.
                if effective_status == "pass":
                    if not ev_graph.get("has_substantive_evidence", False):
                        raise ValueError(
                            f"Run {run_id} has zero assertion or evidence nodes "
                            "(decision-only trace); "
                            "cannot issue authoritative certification."
                        )
                    if not ev_graph.get("has_all_required", True):
                        missing_oracles = ev_graph.get("missing_required_oracles", [])
                        raise ValueError(
                            "MissingRequiredOracles: trace missing required oracles: "
                            f"{missing_oracles}"
                        )
            except ValueError:
                raise
            except Exception as e:
                raise ValueError(f"Invalid execution manifest in {manifest_file}: {e}") from e

            # Re-verify lock ownership prior to signing and sealing mutations
            lock.verify_active()

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
                execution_mode=clean_mode,
                provisional=provisional,
                behavioral_fingerprint_id=behavioral_fingerprint_id,
                scenario_data=effective_scenario_data,
                require_finalization=True,
                artifact_store=artifact_store,
            )

            lock.verify_active()
            manifest_path = vault_dir / "run_manifest.json"
            if not manifest_path.exists() and manifest:
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2)

            is_pass = effective_status == "pass"
            # Defect T1 Invariant: never certified=True when provisional=True;
            # live execution strictly required
            is_certified = bool(is_pass and not provisional and clean_mode == "live")
            return {
                "status": "certified" if is_certified else "attested_failed",
                "compliance_status": effective_status,
                "certified": is_certified,
                "certificate_issued": is_certified,
                "run_id": run_id,
                "score": effective_score,
                "manifest": manifest,
                "package_hash": manifest.get("package_hash"),
                "verification_package": manifest.get("verification_package"),
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
    trace_path: str | Path | None = None,
    artifact_store: Any | None = None,
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
        trace_path=trace_path,
        artifact_store=artifact_store,
    )
