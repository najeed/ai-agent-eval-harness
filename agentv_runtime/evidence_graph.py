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
    Fails closed if duplicate sequence numbers are encountered in trace.
    """
    index: dict[int, str] = {}
    for event, raw_line in events_with_lines:
        seq = event.get("_seq")
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

    seq = assertion.get("event_seq", assertion.get("_seq", fallback_seq))
    if isinstance(seq, int) and seq in seq_index:
        node.update(
            {
                "source_type": "trace_event",
                "source_ref": f"run.jsonl#seq={seq}",
                "content_hash": seq_index[seq],
                "resolved": True,
            }
        )
        # Commit to this node's own canonical row as well.
        node["row_hash"] = _sha3_hex(_canonical_row({**node, "assertion": assertion}).encode())
        return node

    node.update(
        {
            "source_type": "unresolved",
            "source_ref": None,
            "content_hash": None,
            "resolved": False,
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

    return {
        "graph_version": EVIDENCE_GRAPH_VERSION,
        "node_count": len(nodes),
        "resolved_count": sum(1 for n in nodes if n["resolved"]),
        "unresolved_count": sum(1 for n in nodes if not n["resolved"]),
        "nodes": nodes,
        "evidence_root_hash": _sha3_hex(root_payload),
    }


def decision_evidence_root_hash(decision_assertions: list[dict[str, Any]]) -> str:
    """
    Single-commit hash over the verification decision's assertion set.
    Computed over canonical assertion rows so ANY change flips the root.
    """
    rows = sorted(_canonical_row(a) for a in decision_assertions)
    payload = json.dumps({"assertions": rows}, sort_keys=True, separators=(",", ":")).encode()
    return _sha3_hex(payload)
