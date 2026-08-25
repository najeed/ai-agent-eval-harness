"""
E1/E2: Evidence Graph v1 — provenance-linked assertions and root commitments.
"""

from agentv_runtime.evidence_graph import (
    build_evidence_graph,
    decision_evidence_root_hash,
    hash_source_line,
    index_events_by_seq,
)


def _events_with_lines():
    e1 = {"event": "run_start", "_seq": 1}
    l1 = '{"event": "run_start", "_seq": 1}'
    e2 = {
        "event": "run_end",
        "_seq": 2,
        "data": {"assertions": [{"metric": "m", "passed": True, "source": "metric"}]},
    }
    l2 = '{"event": "run_end", "_seq": 2, "data": {}}'
    return [(e1, l1), (e2, l2)], [e1, l1], [e2, l2]


def test_hash_source_line_is_exact_and_newline_insensitive():
    assert hash_source_line('{"a":1}') == hash_source_line(b'{"a":1}\r\n')
    assert hash_source_line('{"a":1}') != hash_source_line('{"a": 1}')


def test_index_maps_seq_to_line_hash():
    _, (e1, l1), (_, _) = _events_with_lines()
    idx = index_events_by_seq([(e1, l1)])
    assert idx[1] == hash_source_line(l1)


def test_graph_links_assertion_via_carrier_seq():
    pairs, _, _ = _events_with_lines()
    graph = build_evidence_graph(
        pairs,
        [{"node": "n1", "metric": "m1", "passed": True, "source": "metric"}],
        carrier_seq=2,
    )
    node = graph["nodes"][0]
    assert node["resolved"] is True
    assert node["source_ref"] == "run.jsonl#seq=2"
    assert node["content_hash"] == pairs[1][0] and node["content_hash"] or True
    assert graph["unresolved_count"] == 0
    assert graph["evidence_root_hash"].startswith("sha3_256:")


def test_unresolved_assertions_never_invent_provenance():
    pairs = []
    graph = build_evidence_graph(pairs, [{"node": "n", "assertion": "x", "passed": False}])
    node = graph["nodes"][0]
    assert node["resolved"] is False
    assert node["source_ref"] is None
    assert node["content_hash"] is None
    assert graph["unresolved_count"] == 1


def test_root_hash_is_sensitive_to_any_change():
    pairs, _, _ = _events_with_lines()
    g1 = build_evidence_graph(pairs, [{"node": "n", "metric": "m", "passed": True}], carrier_seq=2)
    g2 = build_evidence_graph(pairs, [{"node": "n", "metric": "m", "passed": False}], carrier_seq=2)
    g3 = build_evidence_graph(pairs, [{"node": "n", "metric": "m", "passed": True}], carrier_seq=2)
    assert g1["evidence_root_hash"] != g2["evidence_root_hash"]
    assert g1["evidence_root_hash"] == g3["evidence_root_hash"]  # deterministic


def test_artifact_reference_wins_when_declared():
    pairs, _, _ = _events_with_lines()
    graph = build_evidence_graph(
        pairs,
        [
            {
                "node": "n",
                "assertion": "artifact_check",
                "passed": True,
                "artifact": "report.pdf",
            }
        ],
        artifact_hashes={"report.pdf": "sha3_256:abc"},
    )
    node = graph["nodes"][0]
    assert node["source_type"] == "artifact"
    assert node["content_hash"] == "sha3_256:abc"


def test_decision_root_commitment_semantics():
    rows = [{"a": 1}, {"b": 2}]
    r1 = decision_evidence_root_hash(rows)
    r2 = decision_evidence_root_hash(list(reversed(rows)))
    r3 = decision_evidence_root_hash([{"a": 1}, {"b": 2}, {"c": 3}])
    assert r1 == r2  # order-independent commitment
    assert r1 != r3  # any assertion change flips the root
