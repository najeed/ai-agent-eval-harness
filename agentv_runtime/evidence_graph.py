"""
agentv_runtime.evidence_graph — Evidence Graph v1 (E1/E2).

Every recorded assertion is linked to its evidentiary source: either a trace
event (by server-assigned `_seq`, hashed over the EXACT raw JSONL line) or an
artifact (name + content hash). An assertion whose source cannot be resolved
is reported UNRESOLVED — the graph never fabricates provenance.

`evidence_root_hash` commits to the full node set: canonical JSON over sorted
per-node digests. Any change to any assertion or its provenance changes the
root (Merkle-style single-commit summary).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from agentv_runtime.canonical import canonical_json_dumps, canonical_json_encode

EVIDENCE_GRAPH_VERSION = "1.0.0"
# These are the evaluator's declared result states.  Keeping the complete enum
# here is strict schema validation, not permissive string coercion.
_DECLARED_OUTCOMES = frozenset(
    {"PASS", "FAIL", "INVALID", "SKIPPED", "ERROR", "NOT_APPLICABLE", "NOT_EVALUATED"}
)


def _strict_result_value(result: Mapping[str, Any]) -> bool:
    """Validate an evaluator result at the evidence trust boundary.

    Evidence must preserve schema semantics; Python truthiness (notably
    ``bool('false')``) is not an evaluator result.
    """
    has_passed = "passed" in result or "success" in result
    if has_passed:
        value = result.get("passed") if "passed" in result else result.get("success")
        if not isinstance(value, bool):
            raise ValueError("EvidenceResultTypeError: passed/success must be a boolean")
    else:
        value = None
    if "outcome" in result and result.get("outcome") is not None:
        outcome = result["outcome"]
        if not isinstance(outcome, str) or outcome.upper() not in _DECLARED_OUTCOMES:
            raise ValueError(
                f"EvidenceResultTypeError: outcome must be one of {sorted(_DECLARED_OUTCOMES)}"
            )
        outcome_passed = outcome.upper() == "PASS"
        if value is not None and value != outcome_passed:
            raise ValueError("EvidenceResultTypeError: passed/success conflicts with outcome")
        return outcome_passed
    return bool(value) if value is not None else False


def _sha3_hex(data: bytes) -> str:
    return f"sha3_256:{hashlib.sha3_256(data).hexdigest()}"


def hash_source_line(raw_line: str | bytes) -> str:
    """Content hash of the exact raw JSONL line (without trailing newline)."""
    if isinstance(raw_line, str):
        raw_line = raw_line.encode("utf-8")
    return _sha3_hex(raw_line.rstrip(b"\r\n"))


def index_events_by_seq(events_with_lines: list[tuple[dict[str, Any], str]]) -> dict[int, str]:
    """Maps `_seq` -> content hash for every event carrying a sequence id.
    If no events carry explicit `_seq`, defaults to 1-based stream position.
    Fails closed if duplicate sequence numbers are encountered in trace.
    """
    has_explicit_seq = any(isinstance(event.get("_seq"), int) for event, _ in events_with_lines)
    index: dict[int, str] = {}
    for idx, (event, raw_line) in enumerate(events_with_lines, start=1):
        seq = event.get("_seq") if has_explicit_seq else idx
        if isinstance(seq, int):
            if seq in index:
                raise ValueError(
                    f"Evidence trace integrity violation: "
                    f"Duplicate sequence number _seq={seq} detected."
                )
            index[seq] = hash_source_line(raw_line)
    return index


def _canonical_row(row: Any) -> str:
    return canonical_json_dumps(row)


def link_assertion(
    assertion: dict[str, Any],
    seq_index: dict[int, str],
    fallback_seq: int | None = None,
    artifact_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Attaches evidentiary provenance to one assertion row.

    Resolution order:
      1. explicit ``assertion["event_seq"]`` / ``assertion["_seq"]``
      2. ``fallback_seq`` (the terminal event that carried the assertion set)
    If nothing resolves, the node reports ``resolved: false`` — no invented
    provenance. Artifact references win only when explicitly declared via
    ``assertion["artifact"]``.
    """
    oracle_id = (
        assertion.get("oracle_id")
        or assertion.get("metric")
        or assertion.get("assertion")
        or "unnamed"
    )
    has_res = bool(
        assertion.get("has_result", False)
        or "passed" in assertion
        or "success" in assertion
        or "outcome" in assertion
        or "score" in assertion
        or "status" in assertion
    )
    raw_outcome = (
        assertion.get("outcome")
        or assertion.get("status")
        or ("PASS" if assertion.get("passed") is True or assertion.get("success") is True else None)
    )
    if raw_outcome is not None:
        raw_upper = str(raw_outcome).strip().upper()
        if raw_upper in ("PASS", "PASSED", "SUCCESS", "TRUE"):
            outcome_state = "PASS"
        elif raw_upper in ("FAIL", "FAILED", "FAILURE", "FALSE"):
            outcome_state = "FAIL"
        elif raw_upper in ("INVALID", "EVALUATION_INVALID"):
            outcome_state = "INVALID"
        elif raw_upper in ("SKIPPED", "SKIP"):
            outcome_state = "SKIPPED"
        elif raw_upper in ("ERROR", "EXCEPTION"):
            outcome_state = "ERROR"
        else:
            outcome_state = "UNKNOWN"
    else:
        outcome_state = "PASS" if bool(assertion.get("passed", False)) else "FAIL"

    is_invalid = bool(assertion.get("invalid", False) or outcome_state in ("INVALID", "ERROR"))
    is_passed = bool(outcome_state == "PASS" and not is_invalid)
    has_res = bool(has_res and outcome_state in ("PASS", "FAIL", "INVALID", "SKIPPED", "ERROR"))

    raw_sev = str(assertion.get("severity") or assertion.get("requiredness") or "required").lower()
    sev = "informational" if raw_sev in ("informational", "optional") else "required"
    node_id_val = (
        assertion.get("node") or assertion.get("scenario_node_id") or assertion.get("task_id")
    )
    node: dict[str, Any] = {
        "oracle_id": str(oracle_id),
        "kind": assertion.get("source", "metric"),
        "label": assertion.get("metric") or assertion.get("assertion") or "unnamed",
        "node": node_id_val,
        "node_id": node_id_val,
        "outcome": outcome_state,
        "passed": is_passed,
        "severity": sev,
        "invalid": is_invalid,
        "has_result": has_res,
    }
    if "expected" in assertion:
        node["expected"] = assertion["expected"]
    if "actual" in assertion:
        node["actual"] = assertion["actual"]
    elif "actual_after" in assertion:
        node["actual"] = assertion["actual_after"]

    ref = assertion.get("evidence_reference") or assertion.get("reference")
    if ref:
        ref_dict = ref.to_dict() if hasattr(ref, "to_dict") else ref
        if isinstance(ref_dict, dict) and "result_hash" in ref_dict and "source_id" in ref_dict:
            node.update(
                {
                    "source_type": "evidence_reference",
                    "source_ref": f"{ref_dict.get('source_id')}#{ref_dict.get('scope', '')}",
                    "content_hash": ref_dict.get("result_hash"),
                    "reference": ref_dict,
                    "resolved": True,
                    "is_direct_provenance": True,
                }
            )
            node["row_hash"] = _sha3_hex(canonical_json_encode({**node, "assertion": assertion}))
            return node

    artifact_name = assertion.get("artifact")
    if artifact_name and artifact_hashes and artifact_name in artifact_hashes:
        node.update(
            {
                "source_type": "artifact",
                "source_ref": str(artifact_name),
                "content_hash": artifact_hashes[artifact_name],
                "resolved": True,
                "is_direct_provenance": False,
            }
        )
        node["row_hash"] = _sha3_hex(canonical_json_encode({**node, "assertion": assertion}))
        return node

    explicit_seq = assertion.get("event_seq", assertion.get("_seq"))
    if isinstance(explicit_seq, int) and explicit_seq in seq_index:
        node.update(
            {
                "source_type": "trace_event",
                "source_ref": f"run.jsonl#seq={explicit_seq}",
                "content_hash": seq_index[explicit_seq],
                "resolved": True,
                "is_direct_provenance": True,
            }
        )
        node["row_hash"] = _sha3_hex(canonical_json_encode({**node, "assertion": assertion}))
        return node

    if isinstance(fallback_seq, int) and fallback_seq in seq_index:
        node.update(
            {
                "source_type": "carrier_fallback",
                "source_ref": f"run.jsonl#seq={fallback_seq}",
                "content_hash": seq_index[fallback_seq],
                "resolved": True,
                "is_direct_provenance": False,
            }
        )
        node["row_hash"] = _sha3_hex(canonical_json_encode({**node, "assertion": assertion}))
        return node

    node.update(
        {
            "source_type": "unresolved",
            "source_ref": None,
            "content_hash": None,
            "resolved": False,
            "is_direct_provenance": False,
            "row_hash": _sha3_hex(canonical_json_encode({**node, "assertion": assertion})),
        }
    )
    return node


def build_evidence_graph(
    events_with_lines: list[tuple[dict[str, Any], str]],
    assertions: list[dict[str, Any]],
    *,
    carrier_seq: int | None = None,
    artifact_hashes: dict[str, str] | None = None,
    required_oracle_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Builds the Evidence Graph v1 document.

    ``carrier_seq``: the `_seq` of the terminal event that carried the
    assertion set (typically the run_end event), used as fallback provenance.
    ``required_oracle_ids``: authoritative inventory of compiled required oracles.
    """
    seq_index = index_events_by_seq(events_with_lines)

    nodes = [
        link_assertion(a, seq_index, fallback_seq=carrier_seq, artifact_hashes=artifact_hashes)
        for a in assertions
    ]

    node_hashes = sorted(n["row_hash"] for n in nodes)
    root_payload = canonical_json_encode(
        {"graph_version": EVIDENCE_GRAPH_VERSION, "node_hashes": node_hashes}
    )

    all_direct = (
        all(
            n.get("is_direct_provenance", False) or n.get("source_type") == "artifact"
            for n in nodes
            if n.get("severity") != "informational"
        )
        if nodes
        else True
    )

    valid_direct_oracle_ids = {
        str(n.get("oracle_id") or n.get("label") or "")
        for n in nodes
        if n.get("resolved")
        and (n.get("is_direct_provenance") or n.get("source_type") == "artifact")
        and not n.get("invalid")
        and n.get("has_result")
        and n.get("passed") is True
        and n.get("outcome") == "PASS"
    }

    missing_required_oracles: list[str] = []
    if required_oracle_ids:
        for req in required_oracle_ids:
            if str(req) not in valid_direct_oracle_ids:
                missing_required_oracles.append(str(req))
        has_all_required = len(missing_required_oracles) == 0
    else:
        has_all_required = True

    has_substantive_evidence = bool(
        nodes and any(n.get("has_result") and not n.get("invalid") for n in nodes)
    )

    is_complete_provenance = bool(all_direct)

    return {
        "graph_version": EVIDENCE_GRAPH_VERSION,
        "root_hash": _sha3_hex(root_payload),
        "evidence_root_hash": _sha3_hex(root_payload),
        "total_nodes": len(nodes),
        "node_count": len(nodes),
        "evidence_count": len(nodes),
        "resolved_nodes": sum(1 for n in nodes if n.get("resolved")),
        "resolved_count": sum(1 for n in nodes if n.get("resolved")),
        "unresolved_count": sum(1 for n in nodes if not n.get("resolved")),
        "direct_provenance_nodes": sum(1 for n in nodes if n.get("is_direct_provenance")),
        "has_all_required": has_all_required,
        "missing_required_oracles": missing_required_oracles,
        "has_substantive_evidence": has_substantive_evidence,
        "is_complete_provenance": is_complete_provenance,
        "nodes": nodes,
    }


def build_evidence_graph_from_events(
    events: list[dict[str, Any] | tuple[dict[str, Any], str]],
    required_oracle_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Reconstructs the Evidence Graph directly from a stream of parsed trace events."""
    events_with_lines: list[tuple[dict[str, Any], str]] = []
    raw_assertions: list[dict[str, Any]] = []
    carrier_seq = None

    has_explicit_seq = any(
        isinstance(
            (item[0] if isinstance(item, tuple) else item).get("_seq"),
            int,
        )
        for item in events
    )

    for idx, item in enumerate(events, start=1):
        if isinstance(item, tuple):
            evt, line = item
        else:
            evt = item
            # This draft-only convenience path mirrors the runtime JSONL writer.
            # Certification verification never reaches it when raw trace bytes
            # are available; it always supplies (event, exact_raw_line) tuples.
            line = json.dumps(evt)
        events_with_lines.append((evt, line))

        seq_val = evt.get("_seq") if has_explicit_seq else idx
        ev_name = evt.get("event")

        # 1. Authoritative oracle / metric / assertion events
        if ev_name in (
            "metric_evaluated",
            "assertion_evaluated",
            "node_execution_end",
            "oracle_evaluated",
            "oracle_result",
            "assertion",
            "metric",
        ):
            ev_data = evt.get("data") if isinstance(evt.get("data"), dict) else {}
            oid = (
                evt.get("oracle_id")
                or evt.get("metric")
                or evt.get("assertion")
                or evt.get("name")
                or ev_data.get("oracle_id")
                or ev_data.get("metric")
                or ev_data.get("assertion")
            )
            (
                evt.get("passed")
                if evt.get("passed") is not None
                else (
                    evt.get("success")
                    if evt.get("success") is not None
                    else ev_data.get("passed", ev_data.get("success", False))
                )
            )
            has_res = (
                "passed" in evt
                or "success" in evt
                or "score" in evt
                or "outcome" in evt
                or "status" in evt
                or any(k in ev_data for k in ("passed", "success", "score", "outcome", "status"))
            )
            result_fields = dict(ev_data)
            result_fields.update({k: evt[k] for k in ("passed", "success", "outcome") if k in evt})
            raw_assertions.append(
                {
                    "source": "trace_event",
                    "oracle_id": oid,
                    "metric": evt.get("metric") or evt.get("assertion") or evt.get("name"),
                    "node": (
                        evt.get("node")
                        or evt.get("scenario_node_id")
                        or evt.get("node_id")
                        or evt.get("task_id")
                        or ev_data.get("node")
                        or ev_data.get("node_id")
                    ),
                    "passed": _strict_result_value(result_fields),
                    "event_seq": seq_val,
                    "has_result": has_res,
                }
            )

        # 2. Authoritative workflow interpreter execution graph events
        elif ev_name == "execution_graph_node":
            data = evt.get("data") if isinstance(evt.get("data"), dict) else evt
            node_id = evt.get("scenario_node_id") or evt.get("node_id") or data.get("node_id")
            for m in data.get("metrics", []):
                if isinstance(m, dict):
                    raw_assertions.append(
                        {
                            "source": "execution_graph_node",
                            "oracle_id": m.get("oracle_id") or m.get("metric") or m.get("name"),
                            "metric": m.get("metric") or m.get("name"),
                            "node": node_id,
                            "passed": _strict_result_value(m),
                            "event_seq": seq_val,
                            "has_result": (
                                "outcome" in m
                                or "success" in m
                                or "passed" in m
                                or "score" in m
                                or "status" in m
                            ),
                            "invalid": bool(m.get("invalid", False))
                            or (m.get("status") == "EVALUATION_INVALID")
                            or (m.get("outcome") == "INVALID"),
                        }
                    )
            for or_res in data.get("oracle_results", []):
                if isinstance(or_res, dict):
                    raw_assertions.append(
                        {
                            "source": "execution_graph_node",
                            "oracle_id": or_res.get("oracle_id") or or_res.get("id"),
                            "metric": or_res.get("metric") or or_res.get("name"),
                            "node": node_id,
                            "passed": _strict_result_value(or_res),
                            "event_seq": seq_val,
                            "has_result": (
                                "outcome" in or_res
                                or "success" in or_res
                                or "passed" in or_res
                                or "score" in or_res
                                or "status" in or_res
                            ),
                            "invalid": bool(or_res.get("invalid", False))
                            or (or_res.get("outcome") == "INVALID"),
                        }
                    )

        # 3. Terminal/decision carrier events
        elif ev_name in ("run_end", "verification_decision", "session_decision"):
            carrier_seq = seq_val
            data = evt.get("data") if isinstance(evt.get("data"), dict) else evt
            for a in data.get("assertions", []):
                if isinstance(a, dict):
                    _strict_result_value(a)
                    raw_assertions.append(
                        {
                            **a,
                            "event_seq": a.get("event_seq"),
                        }
                    )

    # Deduplicate assertions while preserving distinct node executions
    # and upgrading carrier fallbacks
    assertions: list[dict[str, Any]] = []
    seen_assertions: dict[tuple[str, str], dict[str, Any]] = {}
    for a in raw_assertions:
        oid = str(a.get("oracle_id") or a.get("metric") or a.get("assertion") or "unnamed")
        nid = str(a.get("node") or a.get("scenario_node_id") or a.get("task_id") or "")
        eseq = a.get("event_seq")
        key = (oid, nid)
        if key not in seen_assertions:
            seen_assertions[key] = a
            assertions.append(a)
        else:
            prev = seen_assertions[key]
            prev_seq = prev.get("event_seq")
            # Distinct sequential executions on the same node: retain both
            if eseq is not None and prev_seq is not None and eseq != prev_seq:
                assertions.append(a)
            # Upgrade previous carrier fallback (unsequenced) to direct sequenced event
            elif not prev_seq and eseq:
                idx = assertions.index(prev)
                assertions[idx] = a
                seen_assertions[key] = a

    return build_evidence_graph(
        events_with_lines,
        assertions,
        carrier_seq=carrier_seq,
        required_oracle_ids=required_oracle_ids,
    )


def compute_evidence_graph_root(graph: Mapping[str, Any] | Sequence[Any]) -> str:
    """Returns the single-commit root hash from an Evidence Graph dict or leaves."""
    if isinstance(graph, Mapping):
        return str(graph.get("evidence_root_hash") or graph.get("root_hash") or "")
    leaves: list[str] = []
    for item in graph:
        if isinstance(item, str):
            leaves.append(item)
        elif isinstance(item, Mapping):
            leaves.append(
                str(
                    item.get("row_hash")
                    or item.get("content_hash")
                    or canonical_json_dumps(dict(item))
                )
            )
    leaves.sort()
    h = hashlib.sha3_256()
    for leaf in leaves:
        h.update(leaf.encode("utf-8"))
        h.update(b"\n")
    return f"sha3_256:{h.hexdigest()}"


__all__ = [
    "EVIDENCE_GRAPH_VERSION",
    "build_evidence_graph",
    "build_evidence_graph_from_events",
    "compute_evidence_graph_root",
    "hash_source_line",
    "index_events_by_seq",
    "link_assertion",
]
