"""Provider-native certification transaction.

Certification consumes only evidence returned by the execution owner's
``RunStorageProvider``.  It intentionally has no run-directory, trace-path,
temporary-vault, or resolver fallback API.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from agentv_runtime.finalization import EvaluatorFinalizationRecord
from eval_runner import config
from eval_runner.certification_lock import PerRunCertificationLock
from eval_runner.verifier import TraceVerifier

logger = logging.getLogger(__name__)


class CertificationService:
    """Issue an immutable certificate from scoped, provider-owned evidence."""

    @staticmethod
    def parse_trace_bytes(trace_bytes: bytes, run_id: str) -> list[dict[str, Any]]:
        """Validate the exact signed serialization without recreating it."""
        try:
            lines = bytes(trace_bytes).decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise ValueError("MalformedProviderTraceBytes") from exc
        events: list[dict[str, Any]] = []
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"MalformedTraceRecord:{number}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"InvalidTraceRecord:{number}: expected object")
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            event_run_id = event.get("run_id") or data.get("run_id")
            if event_run_id and str(event_run_id) != run_id:
                raise ValueError(f"ForeignTraceRecord:{number}: run_id mismatch")
            events.append(event)
        if not events:
            raise ValueError("IncompleteProviderStream: no trace events")
        return events

    @staticmethod
    def _execution_truth(events: list[dict[str, Any]]) -> tuple[str, bool]:
        start = next((e for e in events if e.get("event") in {"run_start", "start"}), None)
        if start is None:
            raise ValueError("IncompleteProviderStream: missing run_start event")
        data = start.get("data") if isinstance(start.get("data"), dict) else {}
        metadata = data.get("metadata") or start.get("metadata") or {}
        mode = str(
            data.get("execution_mode")
            or metadata.get("execution_mode")
            or start.get("execution_mode")
            or "unknown"
        ).lower()
        provisional = bool(
            data.get("provisional") or metadata.get("provisional") or start.get("provisional")
        )
        return mode, provisional or mode != "live"

    @staticmethod
    def _finalization(events: list[dict[str, Any]], run_id: str) -> EvaluatorFinalizationRecord:
        for event in reversed(events):
            event_name = event.get("event")
            event_data = event.get("data") if isinstance(event.get("data"), dict) else event
            payload: Any | None = None
            if event_name == "evaluator_finalization":
                payload = event_data
            elif event_name in {"run_end", "end"}:
                if isinstance(event_data.get("finalization"), Mapping):
                    payload = event_data["finalization"]
                elif isinstance(event.get("finalization"), Mapping):
                    payload = event["finalization"]
            if not isinstance(payload, Mapping):
                continue
            evaluator_id = payload.get("evaluator_identity")
            if evaluator_id:
                pub = None
                try:
                    from eval_runner.identity import IdentityService

                    pub = IdentityService.get_public_key(evaluator_id, auto_provision=False)
                except Exception:
                    pub = None
                if pub is None:
                    continue
            try:
                finalization = EvaluatorFinalizationRecord.from_dict(
                    payload, require_authoritative=True, trust_root=config.TRUST_ROOT
                )
            except Exception as e:
                if isinstance(e, ValueError) and "FinalizationRunIdMismatch" in str(e):
                    raise
                continue
            if finalization.run_id != run_id:
                raise ValueError("FinalizationRunIdMismatch")
            return finalization
        raise ValueError(
            "inconclusive outcome: missing mandatory authoritative EvaluatorFinalizationRecord"
        )

    @staticmethod
    def read_run_truth_level(
        run_id: str,
        *,
        run_store: Any | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> tuple[str | None, bool]:
        """Read execution truth from the owning provider's exact trace bytes."""
        if not run_id or not isinstance(run_id, str) or any(x in run_id for x in ("..", "/", "\\")):
            return None, False
        if run_store is None:
            return None, False
        try:
            run = run_store.get_run(run_id, context=context)
            trace_bytes = run_store.get_trace_bytes(run_id, context=context)
        except Exception:
            return None, False
        if run is None:
            return None, False
        if trace_bytes is None:
            return "unknown", True
        try:
            events = CertificationService.parse_trace_bytes(bytes(trace_bytes), run_id)
        except ValueError:
            return "unknown", True

        for ev in events:
            if ev.get("event") in ("run_start", "start"):
                data = ev.get("data", {}) if isinstance(ev.get("data"), dict) else {}
                meta = data.get("metadata") or ev.get("metadata") or {}
                mode = (
                    data.get("execution_mode")
                    or meta.get("execution_mode")
                    or ev.get("execution_mode")
                )
                is_prov = bool(
                    data.get("provisional") or meta.get("provisional") or ev.get("provisional")
                )
                if is_prov or not mode or mode not in ("live", "hybrid"):
                    return mode or "unknown", True
                return mode, False
        return "unknown", True

    @staticmethod
    def extract_computed_run_outcome(
        *, events: list[dict[str, Any]] | None = None
    ) -> tuple[str, float]:
        """Extract the computed outcome from provider-returned events."""

        events = events or []

        finalization_events: list[dict[str, Any]] = []
        terminal_events: list[dict[str, Any]] = []
        has_post_finalization_events = False

        for idx, ev in enumerate(events):
            ev_name = ev.get("event")
            data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
            has_fin = ev_name == "evaluator_finalization" or (
                ev_name in {"run_end", "end"}
                and (
                    isinstance(data.get("finalization"), Mapping)
                    or isinstance(ev.get("finalization"), Mapping)
                )
            )
            if has_fin:
                finalization_events.append(ev)
                if idx < len(events) - 1:
                    has_post_finalization_events = True
            elif ev_name in (
                "session_decision",
                "evaluation_result",
                "evaluation_verdict",
            ) or (
                ev_name in {"run_end", "end"}
                and bool(
                    data.get("status")
                    or data.get("decision")
                    or ev.get("status")
                    or ev.get("decision")
                )
            ):
                terminal_events.append(ev)

        if len(finalization_events) > 1 or has_post_finalization_events:
            return ("inconclusive", 0.0)

        if finalization_events:
            ev = finalization_events[0]
            ev_name = ev.get("event")
            data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
            if ev_name == "evaluator_finalization":
                payload = data or ev
            else:
                payload = data.get("finalization") or ev.get("finalization")
            try:
                fin_rec = EvaluatorFinalizationRecord.from_dict(
                    payload, require_authoritative=True, trust_root=config.TRUST_ROOT
                )
            except Exception:
                return ("inconclusive", 0.0)

            for term_ev in terminal_events:
                t_data = term_ev.get("data") if isinstance(term_ev.get("data"), dict) else term_ev
                t_status = str(t_data.get("status") or t_data.get("decision") or "").lower()
                if t_status and t_status != fin_rec.outcome.lower():
                    return ("inconclusive", 0.0)

            return (fin_rec.outcome.lower(), float(fin_rec.score))

        # When no valid authoritative finalization is present:
        for ev in events:
            d = ev.get("data") if isinstance(ev.get("data"), dict) else ev
            if (
                str(d.get("status") or d.get("decision") or "").lower() == "evaluation_invalid"
                or str(ev.get("status") or ev.get("decision") or "").lower() == "evaluation_invalid"
            ):
                return ("fail", 0.0)

        if len(terminal_events) > 1:
            return ("inconclusive", 0.0)

        if len(terminal_events) == 1:
            term_ev = terminal_events[0]
            t_data = term_ev.get("data") if isinstance(term_ev.get("data"), dict) else term_ev
            raw_status = str(t_data.get("status") or t_data.get("decision") or "").lower()
            verdict = str(t_data.get("verdict") or "").lower()
            if verdict == "fail" or raw_status in {
                "policy_breach",
                "denied",
                "rejected",
            }:
                return ("fail", float(t_data.get("score") or 0.0))
            if raw_status in ("pass", "fail"):
                score = float(
                    t_data.get("score")
                    if t_data.get("score") is not None
                    else (1.0 if raw_status == "pass" else 0.0)
                )
                return (raw_status, score)

        return ("inconclusive", 0.0)

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
        artifact_store: Any | None = None,
        signing_backend: Any | None = None,
        run_store: Any = None,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically sign and seal provider-owned run evidence."""
        del artifact_store, status, score
        if not run_id or not isinstance(run_id, str) or any(x in run_id for x in ("..", "/", "\\")):
            raise ValueError(f"Invalid or unsafe run_id: {run_id}")

        if run_store is None:
            raise ValueError(
                "RunStorageProviderBindingRequired: certification requires "
                "the execution owner's provider."
            )

        from eval_runner.run_lifecycle import (
            RunLifecycleState,
            get_run_lifecycle_state,
            rollback_run_lifecycle_to_open,
        )

        scoped_context = dict(context) if context is not None else None
        run = run_store.get_run(run_id, context=scoped_context)
        if run is None:
            raise FileNotFoundError(f"Run vault not found for {run_id}")

        provider_manifest = run_store.get_manifest(run_id, context=scoped_context) or {}
        trace_bytes = run_store.get_trace_bytes(run_id, context=scoped_context)
        provider_events = run_store.get_events(
            run_id, offset=0, limit=10_000_000, context=scoped_context
        )

        lifecycle = get_run_lifecycle_state(run_id, run_store=run_store, context=scoped_context)
        if lifecycle == RunLifecycleState.SEALED:
            if not provider_manifest or not TraceVerifier.verify_trace(
                bytes(trace_bytes) if trace_bytes is not None else b"",
                provider_manifest,
                run_store=run_store,
                context=scoped_context,
            ):
                raise ValueError("SealedRunCertificateInvalid")
            compliance = provider_manifest.get("compliance") or {}
            is_pass = str(compliance.get("status", "")).lower() == "pass"
            certified = bool(
                is_pass
                and provider_manifest.get("execution_mode") == "live"
                and not provider_manifest.get("provisional")
            )
            return {
                "status": "certified" if certified else "attested_failed",
                "compliance_status": str(compliance.get("status", "")),
                "certified": certified,
                "certificate_issued": True,
                "run_id": run_id,
                "score": float(compliance.get("score") or 0.0),
                "manifest": provider_manifest,
                "package_hash": provider_manifest.get("package_hash"),
                "verification_package": provider_manifest.get("verification_package"),
            }
        if lifecycle in {RunLifecycleState.INVALID, RunLifecycleState.UNKNOWN}:
            raise ValueError(f"InvalidLifecycleState: {lifecycle.value}")

        if trace_bytes is None:
            raise ValueError(
                "ProviderOwnedEvidenceRequired: run, events, and exact trace bytes are required."
            )

        events = cls.parse_trace_bytes(bytes(trace_bytes), run_id)
        if provider_events is not None and events != provider_events:
            raise ValueError("ProviderEventByteDivergence: events do not match exact trace bytes.")

        if run.get("run_id") not in (None, run_id) or provider_manifest.get("run_id") not in (
            None,
            run_id,
        ):
            raise ValueError("ProviderScopeViolation: provider returned another run's evidence.")

        mode, provisional = cls._execution_truth(events)
        if provisional:
            raise ValueError(
                f"ProviderTruthLevelNotLive: run '{run_id}' is provisional (mode={mode!r}); "
                "authoritative certification requires live evidence."
            )

        for ev in events:
            assertion = ev.get("assertion") or (ev.get("data") or {}).get("assertion")
            target = None
            if isinstance(assertion, Mapping):
                target = assertion.get("target")
            elif isinstance(assertion, str):
                target = assertion
            if target and str(target).startswith("shim:"):
                raise ValueError(
                    "SimulatedStateEvidenceProhibited: live certification cannot "
                    "contain simulated state evidence"
                )

        finalization = cls._finalization(events, run_id)

        computed_status, computed_score = cls.extract_computed_run_outcome(events=events)
        if computed_status == "inconclusive":
            raise ValueError(
                f"Run {run_id} has inconclusive outcome: missing terminal evaluation events; "
                "multiple distinct terminal decisions; or event appended after finalization."
            )

        # Validate terminal_seq
        fin_event_idx = next(
            (
                i
                for i, ev in enumerate(events)
                if (
                    ev.get("event") == "evaluator_finalization"
                    and (
                        ev.get("finalization_hash") == finalization.finalization_hash
                        or (
                            isinstance(ev.get("data"), Mapping)
                            and ev["data"].get("finalization_hash")
                            == finalization.finalization_hash
                        )
                    )
                )
                or (
                    ev.get("event") in {"run_end", "end"}
                    and (
                        (
                            isinstance(ev.get("data"), Mapping)
                            and isinstance(ev["data"].get("finalization"), Mapping)
                            and ev["data"]["finalization"].get("finalization_hash")
                            == finalization.finalization_hash
                        )
                        or (
                            isinstance(ev.get("finalization"), Mapping)
                            and ev["finalization"].get("finalization_hash")
                            == finalization.finalization_hash
                        )
                    )
                )
            )
        )
        prior_seqs = [
            e.get("_seq") for e in events[:fin_event_idx] if isinstance(e.get("_seq"), int)
        ]
        if prior_seqs and finalization.terminal_seq not in (prior_seqs[-1], 0):
            raise ValueError(
                "TerminalSequenceMismatch: finalization "
                f"terminal_seq={finalization.terminal_seq} trace={prior_seqs[-1]}"
            )

        # Evidence graph validation
        from agentv_runtime.evidence_graph import build_evidence_graph_from_events

        raw_events: list[tuple[dict[str, Any], str]] = []

        for line in bytes(trace_bytes).decode("utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            ev_name = rec.get("event")
            rec_data = rec.get("data") if isinstance(rec.get("data"), dict) else {}
            if not (
                ev_name == "evaluator_finalization"
                or (
                    ev_name in ("run_end", "verification_decision", "session_decision")
                    and isinstance(rec.get("finalization") or rec_data.get("finalization"), dict)
                )
            ):
                raw_events.append((rec, line))

        ev_graph = build_evidence_graph_from_events(
            raw_events, required_oracle_ids=finalization.required_oracle_ids
        )
        if ev_graph.get("evidence_root_hash") != finalization.evidence_root_hash:
            raise ValueError(
                f"EvidenceRootMismatch: declared={finalization.evidence_root_hash} "
                f"computed={ev_graph.get('evidence_root_hash')}"
            )
        if not ev_graph.get("is_complete_provenance", True):
            raise ValueError(
                "DirectProvenanceViolation: Evidence graph contains unresolved "
                "or carrier fallback provenance."
            )
        if ev_graph.get("total_nodes", 0) == 0:
            raise ValueError(
                "DecisionOnlyTrace: trace contains zero assertion or evidence nodes; "
                "hand-authored or empty traces cannot be certified."
            )

        # Scenario resolution & validation
        effective_scenario = scenario_data
        if effective_scenario and isinstance(effective_scenario, Mapping):
            scen_id_in_arg = effective_scenario.get("id") or effective_scenario.get("scenario_id")
            if scen_id_in_arg and scen_id_in_arg != finalization.scenario_id:
                raise ValueError(
                    f"ScenarioIdMismatch: scenario_data id '{scen_id_in_arg}' does not match "
                    f"finalization record scenario_id '{finalization.scenario_id}'"
                )
        if effective_scenario is None:
            effective_scenario = provider_manifest.get("scenario_data")
        if effective_scenario is None:
            for ev in events:
                if ev.get("event") in ("run_start", "start"):
                    data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
                    if isinstance(data.get("scenario_data"), Mapping):
                        effective_scenario = data["scenario_data"]
                        break
                    if isinstance(ev.get("scenario_data"), Mapping):
                        effective_scenario = ev["scenario_data"]
                        break
        if effective_scenario is None:
            try:
                from eval_runner import loader

                loaded = loader.load_scenario(finalization.scenario_id)
                if isinstance(loaded, Mapping):
                    effective_scenario = loaded
                elif (
                    isinstance(loaded, list) and len(loaded) > 0 and isinstance(loaded[0], Mapping)
                ):
                    effective_scenario = loaded[0]
            except Exception:
                effective_scenario = None

        if not isinstance(effective_scenario, Mapping) or not effective_scenario:
            raise ValueError(
                f"Run {run_id} cannot resolve authoritative scenario "
                f"definition for '{finalization.scenario_id}'."
            )

        from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash

        canonical_scen_hash = compute_scenario_hash(dict(effective_scenario))
        if finalization.scenario_hash != canonical_scen_hash:
            raise ValueError(
                f"ScenarioHashMismatch: trace claimed scenario_hash '{finalization.scenario_hash}' "
                f"does not match actual computed scenario hash '{canonical_scen_hash}'"
            )

        # ExecutionManifest resolution & validation
        execution_manifest_dict = provider_manifest.get("execution_manifest")

        if not isinstance(execution_manifest_dict, Mapping) or not execution_manifest_dict:
            raise ValueError(
                f"ExecutionManifestMissing: Run {run_id} missing "
                "authoritative execution manifest binding."
            )

        try:
            execution = ExecutionManifest.from_dict(dict(execution_manifest_dict))
            actual_manifest_hash = execution.compute_manifest_hash()
        except ValueError:
            raise
        except Exception as e:
            raise ValueError("Invalid provider execution manifest") from e

        if (
            execution.scenario_id
            and finalization.scenario_id
            and execution.scenario_id != finalization.scenario_id
        ):
            raise ValueError(
                f"ManifestScenarioIdMismatch: manifest={execution.scenario_id} "
                f"finalization={finalization.scenario_id}"
            )
        if (
            execution.scenario_version
            and finalization.scenario_version
            and execution.scenario_version != finalization.scenario_version
        ):
            raise ValueError(
                f"ManifestScenarioVersionMismatch: manifest={execution.scenario_version} "
                f"finalization={finalization.scenario_version}"
            )
        if (
            execution.scenario_hash
            and finalization.scenario_hash
            and execution.scenario_hash != finalization.scenario_hash
        ):
            raise ValueError(
                f"ManifestScenarioHashMismatch: manifest={execution.scenario_hash} "
                f"finalization={finalization.scenario_hash}"
            )

        manifest_runtime_cfg = (
            execution_manifest_dict.get("runtime_config")
            or getattr(execution, "runtime_config", {})
            or {}
        )
        manifest_exec_mode = (
            manifest_runtime_cfg.get("execution_mode")
            if isinstance(manifest_runtime_cfg, Mapping)
            else None
        )
        if manifest_exec_mode and manifest_exec_mode != mode:
            raise ValueError(
                f"ManifestExecutionModeMismatch: manifest={manifest_exec_mode} run={mode}"
            )

        manifest_eval_cfg_hash = (
            manifest_runtime_cfg.get("evaluator_config_hash")
            if isinstance(manifest_runtime_cfg, Mapping)
            else None
        )
        if manifest_eval_cfg_hash and manifest_eval_cfg_hash != finalization.evaluator_config_hash:
            raise ValueError(
                f"ManifestEvaluatorConfigHashMismatch: manifest={manifest_eval_cfg_hash} "
                f"finalization={finalization.evaluator_config_hash}"
            )

        if actual_manifest_hash != finalization.execution_manifest_hash:
            raise ValueError(
                f"ManifestHashMismatch: finalization record manifest_hash "
                f"'{finalization.execution_manifest_hash}' does not "
                f"match actual execution manifest hash '{actual_manifest_hash}'"
            )

        # Required oracle inventory checks
        manifest_reqs = set(
            execution_manifest_dict.get("metadata", {}).get("required_oracle_ids")
            or getattr(execution, "required_oracle_ids", [])
            or []
        )
        fin_reqs = set(finalization.required_oracle_ids)
        explicit_scen_reqs = (
            effective_scenario.get("required_oracle_ids")
            or effective_scenario.get("required_oracles")
            or (
                effective_scenario.get("metadata", {}).get("required_oracle_ids")
                if isinstance(effective_scenario.get("metadata"), Mapping)
                else None
            )
            or (
                effective_scenario.get("metadata", {}).get("required_oracles")
                if isinstance(effective_scenario.get("metadata"), Mapping)
                else None
            )
        )
        if explicit_scen_reqs is not None:
            scen_reqs = set(explicit_scen_reqs)
        else:
            from eval_runner.runner import compile_required_oracle_ids

            scen_reqs = set(compile_required_oracle_ids(effective_scenario))

        if manifest_reqs != fin_reqs:
            raise ValueError(
                "ManifestRequiredOracleMismatch: execution manifest "
                "and finalization inventories differ: "
                f"manifest={sorted(manifest_reqs)}, finalization={sorted(fin_reqs)}"
            )
        if scen_reqs != fin_reqs or scen_reqs != manifest_reqs:
            raise ValueError(
                "RequiredOracleInventoryMismatch: scenario, execution manifest, "
                "and finalization inventories differ"
            )

        executed_oracle_ids: set[str] = set()
        for ev in events:
            data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
            for key in ("oracle_results", "executed_oracle_results"):
                results = data.get(key) or ev.get(key)
                if isinstance(results, list):
                    for res in results:
                        if isinstance(res, dict):
                            o_id = res.get("oracle_id") or res.get("metric") or res.get("assertion")
                            if o_id:
                                executed_oracle_ids.add(str(o_id))
            if ev.get("event") in (
                "oracle_result",
                "executed_oracle_result",
                "assertion_evaluated",
                "metric_evaluated",
            ):
                o_id = (
                    data.get("oracle_id")
                    or data.get("metric")
                    or data.get("assertion")
                    or ev.get("oracle_id")
                    or ev.get("metric")
                    or ev.get("assertion")
                )
                if o_id:
                    executed_oracle_ids.add(str(o_id))

        missing_oracles = sorted(fin_reqs - executed_oracle_ids)
        if missing_oracles:
            raise ValueError(
                f"MissingRequiredOracles: required oracles {missing_oracles} were not executed"
            )

        # Reconcile positive finalization against individual assertion failures
        if str(finalization.outcome).lower() in ("pass", "success"):
            for ev in events:
                if ev.get("event") in (
                    "assertion_evaluated",
                    "metric_evaluated",
                    "oracle_result",
                    "executed_oracle_result",
                ):
                    data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
                    is_failed = (
                        ev.get("passed") is False
                        or ev.get("success") is False
                        or str(ev.get("outcome", "")).upper() in ("FAIL", "FAILED")
                        or str(ev.get("status", "")).upper() in ("FAIL", "FAILED")
                        or data.get("passed") is False
                        or data.get("success") is False
                        or str(data.get("outcome", "")).upper() in ("FAIL", "FAILED")
                        or str(data.get("status", "")).upper() in ("FAIL", "FAILED")
                    )
                    if is_failed:
                        assertion_name = (
                            ev.get("assertion")
                            or ev.get("oracle_id")
                            or ev.get("metric")
                            or data.get("assertion")
                            or data.get("oracle_id")
                            or data.get("metric")
                            or "unknown"
                        )
                        raise ValueError(
                            f"BlockingAssertionOutcomeMismatch: assertion '{assertion_name}' "
                            f"failed but finalization declared positive outcome "
                            f"'{finalization.outcome}'"
                        )

        metadata = {
            "scenario_id": finalization.scenario_id,
            "scenario_version": finalization.scenario_version,
            "scenario_hash": finalization.scenario_hash,
            "execution_manifest_hash": finalization.execution_manifest_hash,
            "evaluator_config_hash": finalization.evaluator_config_hash,
            "evaluator_finalization_id": finalization.finalization_id,
            "evaluator_finalization_hash": finalization.finalization_hash,
            "evaluator_identity": finalization.evaluator_identity,
            "required_oracle_ids": list(finalization.required_oracle_ids),
        }
        for ev in events:
            if ev.get("event") in ("run_start", "start"):
                agent_id = ev.get("agent_id") or (ev.get("data") or {}).get("agent_id")
                if agent_id:
                    metadata["agent_id"] = agent_id
                model = ev.get("model") or (ev.get("data") or {}).get("model")
                if model:
                    metadata["model"] = model

        with PerRunCertificationLock(run_id, run_store=run_store, context=scoped_context) as lock:
            try:
                manifest = TraceVerifier.sign_trace_bytes(
                    bytes(trace_bytes),
                    run_id=run_id,
                    run_store=run_store,
                    context=scoped_context,
                    identity_id=identity_id,
                    compliance_status="pass" if finalization.outcome.lower() == "pass" else "fail",
                    compliance_score=float(finalization.score),
                    policy_ref=policy_ref,
                    ttl_days=ttl or config.GOVERNANCE_TTL_DAYS,
                    metadata=metadata,
                    behavioral_fingerprint_id=behavioral_fingerprint_id,
                    execution_mode=mode,
                    provisional=False,
                    scenario_data=effective_scenario,
                    execution_manifest=execution_manifest_dict,
                    signing_backend=signing_backend,
                    evidence_root_hash=finalization.evidence_root_hash,
                )
                lock.verify_active()
                committed = run_store.commit_certification(
                    run_id,
                    manifest,
                    owner_id=lock.owner_id,
                    fencing_token=lock.fencing_token,
                    context=scoped_context,
                )
                if not committed:
                    raise RuntimeError("RunStorageProvider rejected atomic certification commit")
            except Exception:
                state = get_run_lifecycle_state(run_id, run_store=run_store, context=scoped_context)
                if state != RunLifecycleState.SEALED:
                    rollback_run_lifecycle_to_open(
                        run_id, run_store=run_store, context=scoped_context
                    )
                raise

        from eval_runner.flight_recorder import FlightRecorderPlugin

        FlightRecorderPlugin.release_active_recorder(run_id, run_store)
        is_pass = finalization.outcome.lower() == "pass"
        return {
            "status": "certified" if is_pass else "attested_failed",
            "compliance_status": "pass" if is_pass else "fail",
            "certified": is_pass,
            "certificate_issued": is_pass,
            "run_id": run_id,
            "score": float(finalization.score),
            "manifest": manifest,
            "package_hash": manifest.get("package_hash"),
            "verification_package": manifest.get("verification_package"),
        }

    @classmethod
    def issue_certification(cls, run_id: str, **kwargs: Any) -> dict[str, Any]:
        return cls.execute_industrial_certification(run_id=run_id, **kwargs)


def execute_industrial_certification(run_id: str, **kwargs: Any) -> dict[str, Any]:
    """Provider-native convenience entry point."""
    if "trace_path" in kwargs:  # provider-boundary: reject legacy input
        raise ValueError(
            "TracePathCertificationUnsupported: certification requires the "
            "execution owner's provider bytes."
        )
    return CertificationService.execute_industrial_certification(run_id, **kwargs)


def issue_certification(run_id: str, **kwargs: Any) -> dict[str, Any]:
    """Provider-native convenience entry point."""
    return CertificationService.issue_certification(run_id, **kwargs)


__all__ = ["CertificationService", "execute_industrial_certification", "issue_certification"]
