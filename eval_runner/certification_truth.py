"""Claim-specific authority checks shared by issuance and detached verification."""

import hashlib
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from agentv_runtime.canonical import canonical_json_encode
from eval_runner.utils.path_resolver import PathResolver

DEFAULT_PERMITTED_CLOCK_SKEW_SECONDS: float = 60.0


def _digest(value):
    return "sha3_256:" + hashlib.sha3_256(canonical_json_encode(value)).hexdigest()


def capture_receipt_failures(receipt, raw_trace, events, *, require_complete=True):
    """Compare the producer's acknowledged emission count with exact durable bytes."""
    if not isinstance(receipt, Mapping):
        return ["EvidenceCaptureReceiptMissing"]
    if require_complete and receipt.get("complete") is not True:
        return ["EvidenceCaptureIncomplete"]
    if not isinstance(raw_trace, bytes) or not events:
        return ["EvidenceCaptureBytesMissing"]
    count = receipt.get("event_count")
    if (
        type(count) is not int
        or count != len(events)
        or type(receipt.get("terminal_seq")) is not int
        or receipt.get("terminal_seq") != count
    ):
        return ["EvidenceCaptureCountMismatch"]
    if any(
        not isinstance(row, Mapping) or type(row.get("_seq")) is not int or row["_seq"] != index
        for index, row in enumerate(events, 1)
    ):
        return ["EvidenceCaptureSequenceMismatch"]
    if receipt.get("trace_hash") != "sha3_256:" + hashlib.sha3_256(raw_trace).hexdigest():
        return ["EvidenceCaptureDigestMismatch"]
    if require_complete and events[-1].get("event") not in {
        "run_end",
        "end",
        "evaluator_finalization",
    }:
        return ["EvidenceCaptureTerminalMissing"]
    return []


def _extract_scenario_nodes(scenario: Mapping) -> list[dict]:
    if not isinstance(scenario, Mapping):
        return []
    wf = scenario.get("workflow")
    if isinstance(wf, list):
        return [n for n in wf if isinstance(n, Mapping)]
    if isinstance(wf, Mapping):
        nodes = wf.get("nodes", [])
        if isinstance(nodes, list):
            return [n for n in nodes if isinstance(n, Mapping)]
    return []


def authority_is_independent(url, scenario, execution_manifest=None):
    """An evaluated agent endpoint cannot serve as its own state authority.

    Fails closed: when verifying external state claims, the evaluated agent
    endpoint must be explicitly declared and distinct from the authority origin.
    """

    def origin(value):
        parsed = urlparse(value)
        return (
            parsed.scheme.lower(),
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )

    raw_agents = [(scenario.get("metadata") or {}).get("agent"), scenario.get("agent")]
    raw_agents.extend(node.get("agent") for node in _extract_scenario_nodes(scenario))
    exec_manifest = execution_manifest or scenario.get("execution_manifest") or {}
    if hasattr(exec_manifest, "to_dict"):
        exec_manifest = exec_manifest.to_dict()
    if isinstance(exec_manifest, Mapping):
        raw_agents.append(exec_manifest.get("agent_config"))
        raw_agents.append(exec_manifest.get("agent"))
        rc = exec_manifest.get("runtime_config")
        if isinstance(rc, Mapping):
            raw_agents.append(rc.get("agent_config"))
            raw_agents.append(rc.get("agent"))
    meta = scenario.get("metadata") or {}
    if isinstance(meta, Mapping):
        raw_agents.append(meta.get("agent_config"))
    raw_agents.append(scenario.get("agent_config"))

    declared_endpoints = []
    for agent in raw_agents:
        if isinstance(agent, Mapping):
            ep = agent.get("endpoint") or agent.get("url")
            if isinstance(ep, str) and ep.strip():
                declared_endpoints.append(ep.strip())
        elif isinstance(agent, str) and agent.startswith(("http://", "https://")):
            declared_endpoints.append(agent.strip())

    if not declared_endpoints:
        return False

    auth_origin = origin(url)
    return all(origin(ep) != auth_origin for ep in declared_endpoints)


def state_claim_failures(
    scenario,
    events,
    execution_manifest=None,
    run_id=None,
    *,
    require_temporal_bounds: bool = False,
    permitted_clock_skew_seconds: float = DEFAULT_PERMITTED_CLOCK_SKEW_SECONDS,
):
    """Require source-bound, authenticated pre/post observations for business state.

    Sandbox assertions remain useful diagnostics; they cannot establish an
    external business-state claim. Message-only verification has its own scope.
    """
    if not isinstance(scenario, Mapping):
        return ["StateClaimScenarioMissing"]
    expected_run_id = (
        run_id
        or (getattr(execution_manifest, "run_id", None) if execution_manifest else None)
        or (execution_manifest.get("run_id") if isinstance(execution_manifest, Mapping) else None)
    )
    expected_run_id = str(expected_run_id).strip() if expected_run_id else None
    authorities = (
        (scenario.get("metadata") or {}).get("state_authorities")
        or (scenario.get("metadata") or {}).get("state_authority")
        or {}
    )
    if isinstance(authorities, Mapping) and "url" in authorities:
        authorities = {"default": authorities}
    failures = []
    for node in _extract_scenario_nodes(scenario):
        node_id = node.get("id") or node.get("node_id")
        assertions = node.get("expected_outcome") or []
        external_assertions = []
        for assertion in assertions:
            if not isinstance(assertion, Mapping):
                failures.append(f"InvalidStateAssertion:{node_id}")
                continue
            target = str(assertion.get("target", "message"))
            if target == "state" or target.startswith("shim:"):
                failures.append(f"NonAuthoritativeSandboxState:{node_id}:{target}")
            elif target.startswith("policy:"):
                policy = ((scenario.get("metadata") or {}).get("policies") or {}).get(
                    target[7:], {}
                )
                source = policy.get("evidence_target", "")
                if not (source.startswith("authority:") or source.startswith("external:")):
                    failures.append(f"IndependentPolicyEvidenceRequired:{node_id}:{target}")
                else:
                    external_assertions.append((assertion, source))
            elif target.startswith(("authority:", "external:")) or target in {
                "external_state",
                "state_authority",
            }:
                external_assertions.append((assertion, target))
        for change in node.get("expected_state_changes") or []:
            if not any(
                assertion.get("property") == change.get("path")
                and assertion.get("expected") == change.get("value")
                for assertion, _ in external_assertions
            ):
                failures.append(f"IndependentStateAuthorityRequired:{node_id}:{change.get('path')}")
        if not external_assertions:
            continue
        if not expected_run_id:
            failures.append(f"AuthoritativeRunIdentityRequired:{node_id}")
            continue
        carriers = {}
        for event in events or []:
            if event.get("event") != "execution_graph_node":
                continue
            data = event.get("data") if isinstance(event.get("data"), Mapping) else event
            if (data.get("scenario_node_id") or data.get("node_id")) != node_id:
                continue
            if data.get("status") not in {"completed", "failed", "success", "failure"}:
                continue
            execution_id = data.get("execution_instance_id")
            if not isinstance(execution_id, str) or not execution_id:
                failures.append(f"StateObservationExecutionIdentityMissing:{node_id}")
                continue
            carriers.setdefault(execution_id, [])
            for row in data.get("transition_evidence", []) or []:
                if isinstance(row, Mapping):
                    carriers.setdefault(data.get("execution_instance_id"), []).append(row)
        for assertion, source in external_assertions:
            name = source.split(":", 1)[1].split(".", 1)[0] if ":" in source else "default"
            declaration = authorities.get(name) if isinstance(authorities, Mapping) else None
            url = (
                (declaration.get("url") or declaration.get("endpoint"))
                if isinstance(declaration, Mapping)
                else None
            )
            if not isinstance(url, str) or urlparse(url).scheme != "https":
                failures.append(f"AuthenticatedStateAuthorityUndeclared:{node_id}:{name}")
                continue
            expected_source = "sha3_256:" + hashlib.sha3_256(url.rstrip("/").encode()).hexdigest()
            if not authority_is_independent(url, scenario, execution_manifest=execution_manifest):
                failures.append(f"AgentCannotBeItsOwnStateAuthority:{node_id}:{name}")
                continue
            if not carriers:
                failures.append(f"IndependentStateObservationMissing:{node_id}:{source}")
            for execution_id, rows in carriers.items():
                matching = [row for row in rows if row.get("assertion") == assertion]
                if not matching:
                    failures.append(f"IndependentStateObservationMissing:{execution_id}:{source}")
                for row in matching:
                    try:
                        for phase in ("pre", "post"):
                            identity = row.get(f"{phase}_observation_identity") or {}
                            if (
                                not isinstance(identity, Mapping)
                                or identity.get("authenticated") is not True
                                or identity.get("source_id") != expected_source
                            ):
                                raise ValueError("Unbound or unauthenticated source")
                            connector_id = identity.get("connector_id")
                            receipt = identity.get("connector_receipt") or row.get(
                                f"{phase}_connector_receipt"
                            )
                            if not connector_id or not isinstance(connector_id, str):
                                raise ValueError("Missing trusted connector identity")
                            if not isinstance(receipt, Mapping):
                                raise ValueError(
                                    "Missing authenticated connector retrieval receipt"
                                )
                            if (
                                receipt.get("source_id") != expected_source
                                or receipt.get("connector_id") != connector_id
                            ):
                                raise ValueError("Connector receipt source or connector mismatch")
                            if receipt.get("authenticated") is not True:
                                raise ValueError("Connector receipt unauthenticated")

                            # Profile & encoding validation: require unambiguous
                            # v2 receipts in certification.
                            # Reject legacy v1 receipts or mixed v1/v2 downgrade attempts.
                            profile = str(receipt.get("profile") or "").strip()
                            enc_ver = str(receipt.get("encoding_version") or "").strip()
                            ver = str(receipt.get("version") or "").strip()
                            if profile not in ("2", "v2", "agentv.connector-receipt.v2"):
                                raise ValueError(
                                    "Connector receipt legacy profile v1 rejected in "
                                    "certification; v2 required"
                                )
                            if enc_ver and enc_ver not in (
                                "2",
                                "v2",
                                "agentv.connector-receipt.v2",
                            ):
                                raise ValueError(
                                    f"Connector receipt ambiguous encoding_version {enc_ver!r}; "
                                    "v2 required in certification"
                                )
                            if ver and ver not in ("2", "v2", "agentv.connector-receipt.v2"):
                                raise ValueError(
                                    f"Connector receipt ambiguous version {ver!r}; "
                                    "v2 required in certification"
                                )

                            # Instance binding: receipt must match execution instance ID
                            receipt_exec_id = str(receipt.get("execution_id") or "")
                            if not receipt_exec_id or receipt_exec_id != str(execution_id):
                                raise ValueError("Connector receipt execution_id mismatch")

                            # Phase binding: mandatory exact pre/post phase match
                            receipt_phase = receipt.get("phase")
                            if not receipt_phase or str(receipt_phase) not in ("pre", "post"):
                                raise ValueError(
                                    "Connector receipt missing or invalid phase; "
                                    "must be 'pre' or 'post'"
                                )
                            if str(receipt_phase) != str(phase):
                                raise ValueError(
                                    f"Connector receipt phase mismatch: expected {phase!r}, "
                                    f"got {receipt_phase!r}"
                                )

                            # Run ID binding: mandatory nonempty run_id matching
                            # authoritative provider
                            receipt_run_id = str(receipt.get("run_id") or "").strip()
                            if not receipt_run_id:
                                raise ValueError("Connector receipt missing mandatory run_id")
                            if receipt_run_id != str(expected_run_id):
                                raise ValueError(
                                    f"Connector receipt run_id mismatch ({receipt_run_id} "
                                    f"!= {expected_run_id})"
                                )

                            # Temporal binding: receipt must have a valid
                            # non-empty timezone-aware ISO timestamp
                            receipt_ts = str(receipt.get("timestamp") or "")
                            if not receipt_ts:
                                raise ValueError("Connector receipt missing timestamp")
                            try:
                                dt = datetime.fromisoformat(receipt_ts)
                            except (ValueError, TypeError):
                                raise ValueError(
                                    "Connector receipt invalid timestamp format"
                                ) from None
                            if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
                                raise ValueError(
                                    "Connector receipt timestamp missing timezone offset; "
                                    "UTC-normalizable ISO format required"
                                )
                            dt_utc = dt.astimezone(UTC)

                            # Authenticated run interval bounded check:
                            # If authenticated execution window is required or provided,
                            # enforce strictly bounded pre/post windows fail-closed,
                            # define permitted clock skew, and reject
                            # missing/naive/out-of-bound bounds.
                            enforce_bounds = require_temporal_bounds
                            run_start_raw = None
                            run_end_raw = None
                            if isinstance(execution_manifest, Mapping):
                                explicit_start = execution_manifest.get("started_at") or (
                                    execution_manifest.get("metadata") or {}
                                ).get("started_at")
                                explicit_end = execution_manifest.get("completed_at") or (
                                    execution_manifest.get("metadata") or {}
                                ).get("completed_at")
                                if explicit_start or explicit_end:
                                    enforce_bounds = True
                                    run_start_raw = explicit_start
                                    run_end_raw = explicit_end
                                elif require_temporal_bounds:
                                    run_start_raw = explicit_start or execution_manifest.get(
                                        "created_at"
                                    )
                                    run_end_raw = explicit_end

                            if enforce_bounds:
                                if not run_start_raw:
                                    raise ValueError(
                                        "Execution manifest missing required started_at "
                                        "timestamp for temporal binding"
                                    )
                                if not run_end_raw:
                                    raise ValueError(
                                        "Execution manifest missing required completed_at "
                                        "timestamp for temporal binding"
                                    )

                                try:
                                    s_dt = datetime.fromisoformat(str(run_start_raw))
                                except (ValueError, TypeError):
                                    raise ValueError(
                                        "Execution manifest started_at invalid timestamp format"
                                    ) from None
                                if s_dt.tzinfo is None or s_dt.tzinfo.utcoffset(s_dt) is None:
                                    raise ValueError(
                                        "Execution manifest started_at timestamp missing "
                                        "timezone offset; UTC-normalizable ISO format required"
                                    )

                                try:
                                    e_dt = datetime.fromisoformat(str(run_end_raw))
                                except (ValueError, TypeError):
                                    raise ValueError(
                                        "Execution manifest completed_at invalid timestamp format"
                                    ) from None
                                if e_dt.tzinfo is None or e_dt.tzinfo.utcoffset(e_dt) is None:
                                    raise ValueError(
                                        "Execution manifest completed_at timestamp missing "
                                        "timezone offset; UTC-normalizable ISO format required"
                                    )

                                s_utc = s_dt.astimezone(UTC)
                                e_utc = e_dt.astimezone(UTC)
                                if s_utc > e_utc:
                                    raise ValueError(
                                        "Execution manifest started_at postdates completed_at"
                                    )

                                skew = timedelta(
                                    seconds=max(0.0, float(permitted_clock_skew_seconds))
                                )
                                if dt_utc < s_utc - skew:
                                    raise ValueError(
                                        "Connector receipt timestamp predates "
                                        "authenticated run execution window"
                                    )
                                if dt_utc > e_utc + skew:
                                    raise ValueError(
                                        "Connector receipt timestamp postdates "
                                        "authenticated run execution window"
                                    )

                            from eval_runner.state_authority import (
                                verify_connector_receipt_authenticity,
                            )

                            if not verify_connector_receipt_authenticity(receipt):
                                raise ValueError(
                                    "Unverifiable or forged connector receipt signature/MAC"
                                )
                            if f"{phase}_observation" not in row or row.get(
                                f"{phase}_snapshot_hash"
                            ) != _digest(row[f"{phase}_observation"]):
                                raise ValueError("Observation content digest mismatch")
                            resp_digest = receipt.get("response_digest")
                            if not resp_digest:
                                raise ValueError("Missing response digest in connector receipt")
                            if resp_digest != row.get(f"{phase}_snapshot_hash"):
                                raise ValueError(
                                    "Receipt response digest mismatch with observation"
                                )

                        # Pre/Post temporal causal ordering check
                        pre_receipt = (
                            (row.get("pre_observation_identity") or {}).get("connector_receipt")
                            or row.get("pre_connector_receipt")
                            or {}
                        )
                        post_receipt = (
                            (row.get("post_observation_identity") or {}).get("connector_receipt")
                            or row.get("post_connector_receipt")
                            or {}
                        )
                        pre_ts_str = str(pre_receipt.get("timestamp") or "")
                        post_ts_str = str(post_receipt.get("timestamp") or "")
                        if pre_ts_str and post_ts_str:
                            pre_dt = datetime.fromisoformat(pre_ts_str)
                            post_dt = datetime.fromisoformat(post_ts_str)
                            if pre_dt.tzinfo is None or pre_dt.tzinfo.utcoffset(pre_dt) is None:
                                raise ValueError(
                                    "Pre-observation timestamp missing timezone offset"
                                )
                            if post_dt.tzinfo is None or post_dt.tzinfo.utcoffset(post_dt) is None:
                                raise ValueError(
                                    "Post-observation timestamp missing timezone offset"
                                )
                            if pre_dt.astimezone(UTC) > post_dt.astimezone(UTC):
                                raise ValueError(
                                    "Pre-observation timestamp after post-observation timestamp"
                                )
                        pre_ident = row.get("pre_observation_identity") or {}
                        post_ident = row.get("post_observation_identity") or {}
                        if (
                            pre_ident.get("source_id") != post_ident.get("source_id")
                            or pre_ident.get("connector_id") != post_ident.get("connector_id")
                            or pre_ident.get("authenticated") != post_ident.get("authenticated")
                        ):
                            raise ValueError("Observation authority changed")
                        path = assertion.get("property")
                        if str(assertion.get("target", "")).startswith("policy:"):
                            from eval_runner.runtime_services import resolve_policy_evaluator
                            from eval_runner.state_authority import bound_state_snapshot

                            post_obs = row.get("post_observation")
                            if not isinstance(post_obs, Mapping):
                                raise ValueError(
                                    "Policy evidence missing authoritative "
                                    "raw post_observation mapping"
                                )
                            _, recomputed_post_hash = bound_state_snapshot(post_obs)
                            if recomputed_post_hash != row.get("post_snapshot_hash"):
                                raise ValueError(
                                    "Policy raw observation hash does not match post_snapshot_hash"
                                )

                            policy_id = assertion["target"][7:]
                            policy = ((scenario.get("metadata") or {}).get("policies") or {})[
                                policy_id
                            ]
                            evaluated = resolve_policy_evaluator().evaluate_policy(policy, post_obs)
                            actual = (
                                evaluated.violations
                                if path == "violations"
                                else evaluated.reason
                                if path == "reason"
                                else evaluated.allowed
                            )
                            if actual != row.get("actual_after"):
                                raise ValueError(
                                    "Policy decision is not bound to independent observations"
                                )
                        else:
                            raw_source = source.split(":", 1)[1] if ":" in source else "default"
                            if "." in raw_source:
                                suffix = raw_source.split(".", 1)[1]
                                path = f"{suffix}.{path}" if path else suffix
                            for phase, actual in (
                                ("pre", "actual_before"),
                                ("post", "actual_after"),
                            ):
                                observed = row[f"{phase}_observation"]
                                value = PathResolver.resolve(observed, path) if path else observed
                                if phase == "post" and value is None:
                                    raise ValueError("Missing authoritative business-state fact")
                                if row.get(actual) != value:
                                    raise ValueError("Assertion value is not bound to observation")
                        from eval_runner.session_components.state_parity import (
                            SessionStateParityVerifier,
                        )

                        matched = SessionStateParityVerifier._match(
                            row.get("actual_after"),
                            assertion.get("expected"),
                            assertion.get("mode", "exact"),
                            SessionStateParityVerifier._tolerance_for(node, assertion),
                        )
                        if row.get("passed") is not matched:
                            raise ValueError("Assertion outcome does not match observed value")
                    except Exception:
                        logging.getLogger(__name__).debug(
                            "Independent state evidence verification failed", exc_info=True
                        )
                        failures.append(f"InvalidIndependentStateEvidence:{execution_id}:{source}")
    return failures


def certification_claim_scope(scenario):
    if not isinstance(scenario, Mapping):
        return "unverified"
    message_assertions = False
    for node in _extract_scenario_nodes(scenario):
        message_assertions = message_assertions or bool(node.get("expected_outcome"))
        if node.get("expected_state_changes") or any(
            assertion.get("target", "message") != "message"
            for assertion in node.get("expected_outcome", []) or []
            if isinstance(assertion, Mapping)
        ):
            return "external_business_state"
    return "message_only" if message_assertions else "execution_evidence"
