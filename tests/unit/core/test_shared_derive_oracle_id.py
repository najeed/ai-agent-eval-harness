"""
Unit tests for shared derive_oracle_id helper across execution_ir and session.
Asserts that explicit IDs and synthesized fallback IDs match exactly under all input types.
"""

from eval_runner.execution_ir import derive_oracle_id


def test_derive_oracle_id_explicit():
    assert derive_oracle_id("sc", "node_1", {"id": "custom_oracle_id"}) == "custom_oracle_id"
    assert derive_oracle_id("hygiene", "node_1", {"oracle_id": "explicit_sh_1"}) == "explicit_sh_1"
    assert derive_oracle_id("parity", "node_1", {"id": "parity_oid_99"}) == "parity_oid_99"


def test_derive_oracle_id_success_criteria():
    assert (
        derive_oracle_id("sc", "node_1", {"metric": "exact_match"}, idx=0)
        == "node_1:sc:exact_match"
    )
    assert derive_oracle_id("sc", "node_1", {}, idx=2) == "node_1:sc:2"
    assert derive_oracle_id("sc", "node_1", {"metric": ""}, idx=3) == "node_1:sc:3"


def test_derive_oracle_id_state_hygiene():
    assert (
        derive_oracle_id("hygiene", "node_1", {"path": "auth.user"}, idx=0)
        == "node_1:hygiene:auth.user"
    )
    assert derive_oracle_id("hygiene", "node_1", {}, idx=1) == "node_1:hygiene:1"


def test_derive_oracle_id_expected_outcome():
    assert (
        derive_oracle_id("parity", "node_1", {"target": "response.status"}, idx=0)
        == "node_1:parity:response.status"
    )
    assert derive_oracle_id("parity", "node_1", {}, idx=4) == "node_1:parity:4"
