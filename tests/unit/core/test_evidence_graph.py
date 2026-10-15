"""
E1/E2: Evidence Graph v1 — provenance-linked assertions and root commitments.
"""

from agentv_runtime.evidence_graph import (
    _strict_result_value,
    build_evidence_graph,
    compute_evidence_graph_root,
    hash_source_line,
    index_events_by_seq,
    link_assertion,
)


def test_strict_result_value_rejects_invalid_types():
    import pytest

    assert _strict_result_value({"passed": True}) is True
    assert _strict_result_value({"outcome": "FAIL"}) is False
    assert _strict_result_value({}) is False
    assert _strict_result_value({"outcome": None}) is False
    with pytest.raises(ValueError, match="passed/success must be a boolean"):
        _strict_result_value({"passed": "true"})
    with pytest.raises(ValueError, match="outcome must be one of"):
        _strict_result_value({"outcome": "uncertain"})


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


def test_incomplete_evidence_references_and_artifacts_remain_unresolved():
    incomplete_reference = link_assertion(
        {"reference": {"source_id": "source-only"}},
        {},
    )
    missing_artifact = link_assertion(
        {"artifact": "missing.pdf", "passed": True},
        {},
        artifact_hashes={"other.pdf": "sha3_256:other"},
    )

    assert incomplete_reference["resolved"] is False
    assert incomplete_reference["source_type"] == "unresolved"
    assert incomplete_reference["is_direct_provenance"] is False
    assert missing_artifact["resolved"] is False
    assert missing_artifact["source_type"] == "unresolved"
    assert missing_artifact["is_direct_provenance"] is False


def test_link_assertion_preserves_direct_and_fallback_provenance_semantics():
    seq_index = {2: "sha3_256:two"}
    direct_reference = link_assertion(
        {"reference": {"source_id": "source", "result_hash": "sha3_256:ref"}},
        seq_index,
    )
    artifact = link_assertion(
        {"artifact": "report.pdf"},
        seq_index,
        artifact_hashes={"report.pdf": "sha3_256:artifact"},
    )
    malformed_explicit = link_assertion({"event_seq": 1}, seq_index)
    malformed_fallback = link_assertion({}, seq_index, fallback_seq=1)
    fallback = link_assertion({}, seq_index, fallback_seq=2)

    assert direct_reference["resolved"] is True
    assert direct_reference["is_direct_provenance"] is True
    assert artifact["resolved"] is True
    assert artifact["is_direct_provenance"] is False
    assert malformed_explicit["resolved"] is False
    assert malformed_fallback["resolved"] is False
    assert fallback["resolved"] is True
    assert fallback["is_direct_provenance"] is False
    assert fallback["has_result"] is False
    assert fallback["outcome"] == "FAIL"


def test_evidence_completeness_ignores_informational_and_rejects_invalid_results():
    informational_only = build_evidence_graph(
        [],
        [{"oracle_id": "notice", "passed": False, "severity": "informational"}],
    )
    invalid_required = build_evidence_graph(
        [({"_seq": 1}, '{"_seq": 1}')],
        [
            {
                "oracle_id": "required",
                "passed": False,
                "invalid": True,
                "event_seq": 1,
            }
        ],
        required_oracle_ids=["required"],
    )

    assert informational_only["is_complete_provenance"] is True
    assert invalid_required["has_all_required"] is False
    assert invalid_required["missing_required_oracles"] == ["required"]


def test_empty_evidence_graph_has_complete_vacuous_provenance():
    graph = build_evidence_graph([], [])

    assert graph["is_complete_provenance"] is True
    assert graph["has_all_required"] is True


def test_required_direct_trace_result_is_complete():
    graph = build_evidence_graph(
        [({"_seq": 1}, '{"_seq": 1}')],
        [{"oracle_id": "required", "passed": True, "event_seq": 1}],
        required_oracle_ids=["required"],
    )

    assert graph["has_all_required"] is True
    assert graph["missing_required_oracles"] == []


def test_artifact_evidence_counts_as_complete_provenance():
    graph = build_evidence_graph(
        [],
        [{"oracle_id": "artifact", "artifact": "report.pdf", "passed": True}],
        artifact_hashes={"report.pdf": "sha3_256:artifact"},
        required_oracle_ids=["artifact"],
    )

    assert graph["is_complete_provenance"] is True
    assert graph["has_all_required"] is True
    assert graph["missing_required_oracles"] == []


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


def test_evidence_root_commitment_semantics():
    leaves = ["sha3_256:aaa", "sha3_256:bbb"]
    r1 = compute_evidence_graph_root(leaves)
    r2 = compute_evidence_graph_root(list(reversed(leaves)))
    r3 = compute_evidence_graph_root(["sha3_256:aaa", "sha3_256:bbb", "sha3_256:ccc"])
    assert r1 == r2  # order-independent commitment
    assert r1 != r3  # any assertion change flips the root


def test_index_events_by_seq_duplicate_raises():
    import pytest

    pairs = [
        ({"event": "run_start", "_seq": 1}, '{"event": "run_start", "_seq": 1}'),
        ({"event": "step_1", "_seq": 1}, '{"event": "step_1", "_seq": 1}'),
    ]
    with pytest.raises(ValueError, match="Duplicate sequence number _seq=1 detected"):
        index_events_by_seq(pairs)


def test_canonical_row():
    from agentv_runtime.evidence_graph import _canonical_row

    row = {"z": 1, "a": "hello", "m": [3, 2, 1]}
    assert _canonical_row(row) == '{"a":"hello","m":[3,2,1],"z":1}'


def test_link_assertion_all_outcome_states():
    from agentv_runtime.evidence_graph import link_assertion

    seq_idx = {1: "sha3_256:1111"}

    # PASS
    r_pass = link_assertion({"oracle_id": "o1", "outcome": "PASS", "event_seq": 1}, seq_idx)
    assert r_pass["outcome"] == "PASS"
    assert r_pass["passed"] is True

    # FAIL
    r_fail = link_assertion({"oracle_id": "o2", "outcome": "FAILED", "event_seq": 1}, seq_idx)
    assert r_fail["outcome"] == "FAIL"
    assert r_fail["passed"] is False

    # INVALID
    r_inv = link_assertion({"oracle_id": "o3", "outcome": "INVALID", "event_seq": 1}, seq_idx)
    assert r_inv["outcome"] == "INVALID"
    assert r_inv["invalid"] is True

    # SKIPPED
    r_skip = link_assertion({"oracle_id": "o4", "outcome": "SKIP", "event_seq": 1}, seq_idx)
    assert r_skip["outcome"] == "SKIPPED"
    assert r_skip["passed"] is False

    # ERROR
    r_err = link_assertion({"oracle_id": "o5", "outcome": "EXCEPTION", "event_seq": 1}, seq_idx)
    assert r_err["outcome"] == "ERROR"
    assert r_err["invalid"] is True

    # UNKNOWN
    bad_item = {"oracle_id": "o6", "outcome": "SOMETHING_ELSE", "event_seq": 1}
    r_unk = link_assertion(bad_item, seq_idx)
    assert r_unk["outcome"] == "UNKNOWN"
    assert r_unk["passed"] is False

    # Fallback to boolean passed=True
    r_bool_t = link_assertion({"oracle_id": "o7", "passed": True, "event_seq": 1}, seq_idx)
    assert r_bool_t["outcome"] == "PASS"

    # Fallback to boolean passed=False
    r_bool_f = link_assertion({"oracle_id": "o8", "passed": False, "event_seq": 1}, seq_idx)
    assert r_bool_f["outcome"] == "FAIL"

    r_success = link_assertion(
        {"oracle_id": "o9", "passed": False, "success": True, "event_seq": 1},
        seq_idx,
    )
    assert r_success["outcome"] == "PASS"


def test_build_evidence_graph_from_events_with_tuples_and_carrier_upgrade():
    from agentv_runtime.evidence_graph import build_evidence_graph_from_events

    # Test tuple items (evt, line), terminal carrier with assertions, and carrier upgrade
    events = [
        ({"event": "run_start", "_seq": 1}, '{"event": "run_start", "_seq": 1}'),
        (
            {
                "event": "run_end",
                "_seq": 2,
                "data": {
                    "assertions": [{"oracle_id": "check_latency", "passed": True, "node": "n1"}]
                },
            },
            '{"event": "run_end", "_seq": 2}',
        ),
        (
            {
                "event": "assertion_evaluated",
                "_seq": 3,
                "oracle_id": "check_latency",
                "passed": True,
                "node": "n1",
                "event_seq": 3,
            },
            '{"event": "assertion_evaluated", "_seq": 3}',
        ),
    ]

    graph = build_evidence_graph_from_events(events, required_oracle_ids=["check_latency"])
    assert graph["evidence_count"] == 1
    node = graph["nodes"][0]
    # Upgraded from carrier to direct event seq 3
    assert node["source_ref"] == "run.jsonl#seq=3"
    assert node["is_direct_provenance"] is True
    assert graph["is_complete_provenance"] is True


def test_build_evidence_graph_ignores_unknown_events_and_keeps_first_unsequenced_assertion():
    from agentv_runtime.evidence_graph import build_evidence_graph_from_events

    graph = build_evidence_graph_from_events(
        [
            {"event": "unknown", "_seq": 1, "passed": True},
            {
                "event": "run_end",
                "_seq": 2,
                "data": {
                    "assertions": [
                        {"oracle_id": "duplicate", "node": "n", "passed": True},
                        {"oracle_id": "duplicate", "node": "n", "passed": False},
                    ]
                },
            },
        ]
    )

    assert graph["evidence_count"] == 1
    assert graph["nodes"][0]["oracle_id"] == "duplicate"
    assert graph["nodes"][0]["passed"] is True


def test_build_evidence_graph_sequential_executions_and_missing_required():
    from agentv_runtime.evidence_graph import build_evidence_graph_from_events

    events = [
        {"event": "run_start", "_seq": 1},
        {
            "event": "assertion_evaluated",
            "_seq": 2,
            "oracle_id": "check_retry",
            "passed": False,
            "node": "step_1",
        },
        {
            "event": "assertion_evaluated",
            "_seq": 3,
            "oracle_id": "check_retry",
            "passed": True,
            "node": "step_1",
        },
        {
            "event": "execution_graph_node",
            "_seq": 4,
            "data": {
                "node_id": "step_2",
                "oracle_results": [
                    {"oracle_id": "check_output", "outcome": "PASS", "passed": True}
                ],
            },
        },
        {"event": "run_end", "_seq": 5},
    ]

    # Required oracle check_nonexistent is missing
    graph = build_evidence_graph_from_events(
        events, required_oracle_ids=["check_output", "check_nonexistent"]
    )
    # 2 sequential check_retry on step_1 + 1 check_output on step_2 = 3 evidence nodes
    assert graph["evidence_count"] == 3
    assert graph["has_all_required"] is False
    assert "check_nonexistent" in graph["missing_required_oracles"]
    output_node = next(node for node in graph["nodes"] if node["oracle_id"] == "check_output")
    assert output_node["invalid"] is False


def test_build_evidence_graph_from_events_dict_stream_and_execution_graph_node_metrics():
    from agentv_runtime.evidence_graph import build_evidence_graph_from_events

    # Events as plain dicts (no tuples), including execution_graph_node with metrics
    events = [
        {"event": "run_start", "_seq": 1},
        {
            "event": "execution_graph_node",
            "_seq": 2,
            "data": {
                "node_id": "node_eval",
                "metrics": [
                    {"metric": "latency_ms", "outcome": "PASS", "oracle_id": "latency_ms"},
                    {"metric": "error_rate", "outcome": "INVALID", "invalid": True},
                ],
            },
        },
        {"event": "run_end", "_seq": 3},
    ]
    graph = build_evidence_graph_from_events(events, required_oracle_ids=["latency_ms"])
    assert graph["evidence_count"] == 2
    assert graph["has_all_required"] is True
    assert graph["missing_required_oracles"] == []
    assert graph["nodes"][0]["invalid"] is False


def test_compute_evidence_graph_root_mapping_and_dicts():
    # 1. Mapping input
    g_dict = {"evidence_root_hash": "sha3_256:abcd1234"}
    assert compute_evidence_graph_root(g_dict) == "sha3_256:abcd1234"

    # 2. Sequence of dicts with row_hash and raw dict
    d1 = {"row_hash": "sha3_256:1111"}
    d2 = {"custom_data": "value"}
    root = compute_evidence_graph_root([d1, d2])
    assert root.startswith("sha3_256:")

    # 3. Sequence with item that is neither str nor Mapping
    root_mixed = compute_evidence_graph_root([d1, 12345, None])
    assert root_mixed.startswith("sha3_256:")


def test_build_evidence_graph_actual_after_and_non_dict_terminal_assertions():
    from agentv_runtime.evidence_graph import build_evidence_graph_from_events

    events = [
        {"event": "run_start", "_seq": 1},
        {
            "event": "run_end",
            "_seq": 2,
            "data": {
                "assertions": [
                    {
                        "oracle_id": "oracle_actual_after",
                        "actual_after": "state_val_after",
                        "outcome": "PASS",
                    },
                    "not_a_dict_assertion",
                ],
            },
        },
    ]
    graph = build_evidence_graph_from_events(events)
    assert graph["evidence_count"] == 1
    node = graph["nodes"][0]
    assert node["actual"] == "state_val_after"


def test_index_events_by_seq_with_mixed_non_int_seq():
    # When explicit sequence numbering is detected, any event missing an integer sequence is skipped
    events_with_lines = [
        ({"event": "run_start", "_seq": 1}, '{"event": "run_start", "_seq": 1}'),
        ({"event": "heartbeat", "_seq": None}, '{"event": "heartbeat"}'),
        ({"event": "run_end", "_seq": 2}, '{"event": "run_end", "_seq": 2}'),
    ]
    index = index_events_by_seq(events_with_lines)
    assert 1 in index
    assert 2 in index
    assert None not in index


def test_link_assertion_with_expected_and_actual_values():
    assertion = {
        "oracle_id": "oracle_expected_actual",
        "expected": "expected_contract_output",
        "actual": "actual_contract_output",
        "outcome": "PASS",
    }
    node = link_assertion(assertion, seq_index={1: "dummy_hash"}, fallback_seq=1)
    assert node["expected"] == "expected_contract_output"
    assert node["actual"] == "actual_contract_output"
