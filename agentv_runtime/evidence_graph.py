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
from typing import Any

EVIDENCE_GRAPH_VERSION = "1.0.0"


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
    return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)


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
    node: dict[str, Any] = {
        "kind": assertion.get("source", "metric"),
        "label": assertion.get("metric") or assertion.get("assertion") or "unnamed",
        "node_id": assertion.get("node"),
        "passed": bool(assertion.get("passed", False)),
        "severity": assertion.get("severity", "required"),
        "invalid": bool(assertion.get("invalid", False)),
    }

    artifact_name = assertion.get("artifact")
    if artifact_name and artifact_hashes and artifact_name in artifact_hashes:
        node.update(
            {
                "source_type": "artifact",
                "source_ref": str(artifact_name),
                "content_hash": artifact_hashes[artifact_name],
                "resolved": True,
            }
        )
        node["row_hash"] = _sha3_hex(_canonical_row({**node, "assertion": assertion}).encode())
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
        node["row_hash"] = _sha3_hex(_canonical_row({**node, "assertion": assertion}).encode())
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
        node["row_hash"] = _sha3_hex(_canonical_row({**node, "assertion": assertion}).encode())
        return node

    node.update(
        {
            "source_type": "unresolved",
            "source_ref": None,
            "content_hash": None,
            "resolved": False,
            "is_direct_provenance": False,
            "row_hash": _sha3_hex(_canonical_row({**node, "assertion": assertion}).encode()),
        }
    )
    return node


def build_evidence_graph(
    events_with_lines: list[tuple[dict[str, Any], str]],
    assertions: list[dict[str, Any]],
    *,
    carrier_seq: int | None = None,
    artifact_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Builds the Evidence Graph v1 document.

    ``carrier_seq``: the `_seq` of the terminal event that carried the
    assertion set (typically the run_end event), used as fallback provenance.
    """
    seq_index = index_events_by_seq(events_with_lines)

    nodes = [
        link_assertion(a, seq_index, fallback_seq=carrier_seq, artifact_hashes=artifact_hashes)
        for a in assertions
    ]

    node_hashes = sorted(n["row_hash"] for n in nodes)
    root_payload = json.dumps(
        {"graph_version": EVIDENCE_GRAPH_VERSION, "node_hashes": node_hashes},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    all_direct = (
        all(
            n.get("is_direct_provenance", False) or n.get("source_type") == "artifact"
            for n in nodes
        )
        if nodes
        else True
    )

    return {
        "graph_version": EVIDENCE_GRAPH_VERSION,
        "root_hash": _sha3_hex(root_payload),
        "evidence_root_hash": _sha3_hex(root_payload),
        "total_nodes": len(nodes),
        "node_count": len(nodes),
        "resolved_nodes": sum(1 for n in nodes if n.get("resolved")),
        "resolved_count": sum(1 for n in nodes if n.get("resolved")),
        "unresolved_count": sum(1 for n in nodes if not n.get("resolved")),
        "direct_provenance_nodes": sum(1 for n in nodes if n.get("is_direct_provenance")),
        "is_complete_provenance": all_direct,
        "nodes": nodes,
    }


def decision_evidence_root_hash(decision_assertions: list[dict[str, Any]]) -> str:
    """
    Single-commit hash over the verification decision's assertion set.
    Computed over canonical assertion rows so ANY change flips the root.
    """
    rows = sorted(_canonical_row(a) for a in decision_assertions)
    payload = json.dumps({"assertions": rows}, sort_keys=True, separators=(",", ":")).encode()
    return _sha3_hex(payload)


def build_evidence_graph_from_events(
    events: list[dict[str, Any] | tuple[dict[str, Any], str]],
) -> dict[str, Any]:
    """Reconstructs the Evidence Graph directly from a stream of parsed trace events."""
    events_with_lines: list[tuple[dict[str, Any], str]] = []
    assertions: list[dict[str, Any]] = []
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
            line = json.dumps(evt, sort_keys=True, separators=(",", ":"))
        events_with_lines.append((evt, line))

        seq_val = evt.get("_seq") if has_explicit_seq else idx

        if evt.get("event") in ("metric_evaluated", "assertion_evaluated", "node_execution_end"):
            assertions.append(
                {
                    "source": "trace_event",
                    "metric": evt.get("metric") or evt.get("assertion") or evt.get("name"),
                    "node": evt.get("node_id") or evt.get("task_id"),
                    "passed": bool(evt.get("passed", evt.get("success", False))),
                    "event_seq": seq_val,
                }
            )
        if evt.get("event") in ("run_end", "verification_decision"):
            carrier_seq = seq_val

    return build_evidence_graph(events_with_lines, assertions, carrier_seq=carrier_seq)


def compute_evidence_graph_root(graph: dict[str, Any]) -> str:
    """Returns the single-commit root hash from an Evidence Graph dictionary."""
    return str(graph.get("evidence_root_hash") or graph.get("root_hash") or "")
