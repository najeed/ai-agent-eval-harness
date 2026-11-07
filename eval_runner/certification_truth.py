"""Claim-specific authority checks shared by issuance and detached verification."""

import hashlib
import logging
from collections.abc import Mapping
from urllib.parse import urlparse

from agentv_runtime.canonical import canonical_json_encode
from eval_runner.utils.path_resolver import PathResolver


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


def authority_is_independent(url, scenario):
    """An evaluated agent endpoint cannot serve as its own state authority."""

    def origin(value):
        parsed = urlparse(value)
        return (
            parsed.scheme.lower(),
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )

    agents = [(scenario.get("metadata") or {}).get("agent"), scenario.get("agent")]
    agents.extend(node.get("agent") for node in _extract_scenario_nodes(scenario))
    return all(
        not isinstance(agent, Mapping)
        or not isinstance(agent.get("endpoint"), str)
        or origin(agent["endpoint"]) != origin(url)
        for agent in agents
    )


def state_claim_failures(scenario, events):
    """Require source-bound, authenticated pre/post observations for business state.

    Sandbox assertions remain useful diagnostics; they cannot establish an
    external business-state claim. Message-only verification has its own scope.
    """
    if not isinstance(scenario, Mapping):
        return ["StateClaimScenarioMissing"]
    authorities = (
        scenario.get("state_authorities")
        or scenario.get("state_authority")
        or (scenario.get("metadata") or {}).get("state_authorities")
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
            if not authority_is_independent(url, scenario):
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
                            if f"{phase}_observation" not in row or row.get(
                                f"{phase}_snapshot_hash"
                            ) != _digest(row[f"{phase}_observation"]):
                                raise ValueError("Observation content digest mismatch")
                        if row.get("pre_observation_identity") != row.get(
                            "post_observation_identity"
                        ):
                            raise ValueError("Observation authority changed")
                        path = assertion.get("property")
                        if str(assertion.get("target", "")).startswith("policy:"):
                            from eval_runner.runtime_services import resolve_policy_evaluator

                            policy_id = assertion["target"][7:]
                            policy = ((scenario.get("metadata") or {}).get("policies") or {})[
                                policy_id
                            ]
                            evaluated = resolve_policy_evaluator().evaluate_policy(
                                policy, row["post_observation"]
                            )
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
