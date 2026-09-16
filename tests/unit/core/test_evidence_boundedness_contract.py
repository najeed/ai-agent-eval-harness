"""
tests/unit/core/test_evidence_boundedness_contract.py
Comprehensive test suite verifying the Evidence Boundedness Contract (P0 Runtime Contract).

AgentV must never materialize an unbounded external system state
merely to establish verification evidence.
This suite verifies:
1. EvidenceReference primitive definition, serialization, and deterministic hashing.
2. BoundedStateProvider contract enforcement (fail-closed on get_all_state).
3. DatabaseSimulator compliance with BoundedStateProvider.
4. Forensic list diff boundedness (no unbounded dump fallback for unkeyed/large lists).
5. Forensic snapshot bounding for oversized states (>512 KB).
6. Forensic raw interaction payload bounding (>64 KB) with SHA3 digest commitment.
7. EvidenceGraph linking assertions to EvidenceReference nodes.
8. ToolSandbox get_full_state handling of external vs. controlled simulation state.
"""

import json

import pytest

from agentv_runtime.canonical import compute_reference_hash
from agentv_runtime.contracts import (
    EvidenceBoundednessLimits,
    EvidenceBoundednessViolationError,
    EvidenceReference,
)
from agentv_runtime.evidence_graph import link_assertion
from agentv_runtime.interfaces import BoundedStateProvider
from eval_runner.forensics import ForensicCollector, list_diff
from eval_runner.simulators import BaseSimulator, DatabaseSimulator
from eval_runner.tool_sandbox import ToolSandbox


class MockExternalEnterpriseProvider(BoundedStateProvider):
    """A mock enterprise provider representing an external CRM/ERP/Snowflake system."""

    def __init__(self, name: str = "snowflake_dw"):
        self.name = name
        self.is_external = True

    def query_bounded_reference(
        self,
        scope: str,
        selector: dict | str,
        max_items: int | None = None,
        max_bytes: int | None = None,
        **kwargs,
    ) -> EvidenceReference:
        return EvidenceReference(
            source_id=f"{self.name}://{scope}",
            scope=scope,
            selector_hash="0123456789abcdef",
            query_or_operation_hash="abcdef0123456789",
            result_hash="fedcba9876543210",
            result_count=42,
            sampled_result=[{"id": 1, "metric": "valid"}],
            provenance={"provider": self.name},
        )

    def commit_state_transition(
        self,
        scope: str,
        operation: str,
        delta: dict | None = None,
        **kwargs,
    ) -> EvidenceReference:
        return EvidenceReference(
            source_id=f"{self.name}://{scope}",
            scope=scope,
            selector_hash="op_hash",
            query_or_operation_hash="op_hash",
            result_hash="res_hash",
            result_count=1,
            sampled_result=delta,
            provenance={"provider": self.name, "operation": operation},
        )


def test_evidence_reference_instantiation_and_canonicalization():
    """Verify EvidenceReference dataclass fields, dict conversion, and deterministic hashing."""
    ref1 = EvidenceReference(
        source_id="salesforce://accounts",
        source_version="v2.1",
        scope="enterprise_crm",
        selector_hash="sel_hash_1",
        query_or_operation_hash="query_hash_1",
        result_hash="res_hash_1",
        result_count=5,
        sampled_result=[{"id": "A101", "name": "Acme"}],
        provenance={"system": "salesforce", "region": "us-east"},
    )

    d = ref1.to_dict()
    assert d["source_id"] == "salesforce://accounts"
    assert d["result_count"] == 5
    assert d["sampled_result"] == [{"id": "A101", "name": "Acme"}]

    ref2 = EvidenceReference.from_dict(d)
    assert ref2.source_id == ref1.source_id
    assert ref2.selector_hash == ref1.selector_hash

    # Deterministic hash test
    h1 = compute_reference_hash(ref1)
    h2 = compute_reference_hash(ref2)
    assert h1 == h2
    assert h1.startswith("sha3_256:")
    assert len(h1) == 73  # sha3_256: prefix + 64 hex characters


def test_bounded_state_provider_fails_closed_on_get_all_state():
    """Verify BoundedStateProvider strictly forbids get_all_state()."""
    provider = MockExternalEnterpriseProvider()
    with pytest.raises(EvidenceBoundednessViolationError) as excinfo:
        provider.get_all_state()

    assert "Unbounded state materialization prohibited" in str(excinfo.value)
    assert "MockExternalEnterpriseProvider" in str(excinfo.value)


@pytest.mark.asyncio
async def test_database_simulator_bounded_query_and_mutation(tmp_path):
    """Verify DatabaseSimulator conforms to BoundedStateProvider contract."""
    db = DatabaseSimulator()
    db.terminal_jail = tmp_path

    # Verify is_external flag
    assert db.is_external is True
    assert isinstance(db, BoundedStateProvider)

    # Initial query via bounded reference
    ref = db.query_bounded_reference(scope="users", selector="SELECT * FROM users")
    assert isinstance(ref, EvidenceReference)
    assert ref.source_id == "db://users"
    assert ref.result_count >= 1
    assert ref.result_hash is not None
    assert len(ref.result_hash) == 64

    # Seed 150 users to test boundary clamping
    with db._get_engine().connect() as conn:
        from sqlalchemy import text

        for i in range(150):
            conn.execute(
                text("INSERT INTO users (email, role) VALUES (:email, :role)"),
                {"email": f"test_{i}@domain.com", "role": "analyst"},
            )
        conn.commit()

    # Query with default limits
    bounded_ref = db.query_bounded_reference(scope="users", selector="SELECT * FROM users")
    # Result count reflects rows found up to fetch limit,
    # but sampled_result is capped at MAX_INLINE_ITEMS
    assert len(bounded_ref.sampled_result) <= EvidenceBoundednessLimits.MAX_INLINE_ITEMS

    # Mutation state transition
    mut_ref = db.commit_state_transition(
        scope="users",
        operation="INSERT",
        delta={"email": "new_admin@domain.com", "role": "admin"},
    )
    assert isinstance(mut_ref, EvidenceReference)
    assert mut_ref.result_count == 1
    assert mut_ref.sampled_result["email"] == "new_admin@domain.com"

    # Strict failure on get_all_state()
    with pytest.raises(EvidenceBoundednessViolationError):
        db.get_all_state()

    await db.cleanup()


def test_forensics_list_diff_boundedness():
    """
    Verify list_diff bounds unkeyed lists and lists exceeding MAX_INLINE_ITEMS,
    preventing entire table/collection dumps into forensics diffs.
    """
    # 1. Unkeyed list of simple strings exceeding limit
    old_list = [f"item_{i}" for i in range(200)]
    new_list = [f"item_{i}" for i in range(200)] + ["item_200", "item_201"]

    diff = list_diff(old_list, new_list)
    assert isinstance(diff, dict)
    assert "__LIST_DIFF_BOUNDED__" in diff
    bounded_info = diff["__LIST_DIFF_BOUNDED__"]
    assert bounded_info["total_items"] == 202
    assert len(bounded_info["sample"]) <= EvidenceBoundednessLimits.MAX_INLINE_ITEMS
    assert bounded_info["result_hash"].startswith("sha3_256:")

    # 2. Keyed list with items: updates should be keyed
    old_keyed = [{"id": i, "name": f"item_{i}"} for i in range(10)]
    new_keyed = [{"id": i, "name": f"item_{i}"} for i in range(9)] + [{"id": 9, "name": "modified"}]
    keyed_diff = list_diff(old_keyed, new_keyed)
    assert "__LIST_DIFF__" in keyed_diff
    assert len(keyed_diff["__LIST_DIFF__"]["modified"]) == 1


def test_forensics_snapshot_state_boundedness(tmp_path):
    """Verify Forensics caps oversized snapshots (>512 KB) and commits SHA3 digest."""
    run_id = "test_bound_snap_run"
    forensics = ForensicCollector(run_id=run_id, run_log_dir=tmp_path)

    # Construct huge state exceeding MAX_SNAPSHOT_BYTES (512 KB)
    huge_state = {
        "world": {"meta": "large"},
        "external_database": {
            "massive_data": "x" * (EvidenceBoundednessLimits.MAX_SNAPSHOT_BYTES + 1000)
        },
    }

    forensics.snapshot_state(huge_state, turn=0)

    # Read the snapshot file
    snap_file = tmp_path / "forensics" / "state_turn_000_full.json"
    assert snap_file.exists()
    content = json.loads(snap_file.read_text(encoding="utf-8"))

    assert "__BOUNDED_SNAPSHOT__" in content
    snap_info = content["__BOUNDED_SNAPSHOT__"]
    assert snap_info["status"] == "BOUNDED_SNAPSHOT"
    assert snap_info["byte_size"] > EvidenceBoundednessLimits.MAX_SNAPSHOT_BYTES
    assert snap_info["snapshot_hash"].startswith("sha3_256:")
    assert snap_info["truncated"] is True


def test_forensics_register_raw_interaction_boundedness(tmp_path):
    """Verify Forensics register_raw_interaction bounds payloads > 64 KB with SHA3 digest."""
    run_id = "test_bound_interact_run"
    forensics = ForensicCollector(run_id=run_id, run_log_dir=tmp_path)

    huge_payload = {"command": "SELECT_ALL", "bloat": "A" * 70000}
    huge_response = {"status": "SUCCESS", "records": "B" * 80000}

    forensics.register_raw_interaction(huge_payload, huge_response)

    trace_file = tmp_path / "forensics" / "adapter_trace.jsonl"
    assert trace_file.exists()
    lines = trace_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1

    entry = json.loads(lines[0])
    assert "__BOUNDED_INTERACTION__" in entry["payload"]
    assert entry["payload"]["__BOUNDED_INTERACTION__"]["content_hash"].startswith("sha3_256:")
    assert "__BOUNDED_INTERACTION__" in entry["response"]
    assert entry["response"]["__BOUNDED_INTERACTION__"]["content_hash"].startswith("sha3_256:")


def test_evidence_graph_link_assertion_with_evidence_reference():
    """Verify EvidenceGraph recognizes and binds EvidenceReference nodes."""
    ref = EvidenceReference(
        source_id="sap://materials",
        scope="inventory",
        selector_hash="sel_hash",
        query_or_operation_hash="q_hash",
        result_hash="res_hash_1234567890",
        result_count=1,
        sampled_result={"part_id": "P-100", "qty": 50},
        provenance={"erp": "sap"},
    )

    assertion = {
        "oracle_id": "assert_inventory_check",
        "metric": "inventory_accuracy",
        "passed": True,
        "evidence_reference": ref,
    }

    linked_node = link_assertion(assertion=assertion, seq_index={})
    assert linked_node["resolved"] is True
    assert linked_node["source_type"] == "evidence_reference"
    assert linked_node["content_hash"] == "res_hash_1234567890"
    assert "sap://materials#inventory" in linked_node["source_ref"]
    assert linked_node["reference"]["result_count"] == 1


@pytest.mark.asyncio
async def test_tool_sandbox_get_full_state_with_external_simulator(tmp_path):
    """Verify ToolSandbox respects external state boundedness during get_full_state()."""
    scenario = {
        "id": "bounded_scenario",
        "run_id": "test_sandbox_bound_run",
        "initial_state": {"agent_mode": "test"},
    }
    sandbox = ToolSandbox(scenario=scenario, jail_root=tmp_path)

    # Attach both an internal shim and an external enterprise provider shim
    internal_shim = BaseSimulator(initial_state={"step": 1})
    external_shim = MockExternalEnterpriseProvider(name="salesforce_crm")

    sandbox._simulator_cache = {
        "internal_worker": internal_shim,
        "external_crm": external_shim,
    }

    full_state = await sandbox.get_full_state()
    assert "world" in full_state
    assert full_state["world"]["agent_mode"] == "test"
    assert "internal_worker" in full_state["shims"]
    assert full_state["shims"]["internal_worker"] == {"step": 1}

    # External CRM should be bounded
    assert "external_crm" in full_state["shims"]
    assert full_state["shims"]["external_crm"].get("status") == "EXTERNAL_BOUNDED"
