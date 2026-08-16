"""
tests/unit/test_phase1_extension_families.py
Validation for Phase 1 Public Extension Families and Reference Implementations.
"""

from pathlib import Path

from eval_runner.reference import (
    BasicFieldPolicyEvaluator,
    InProcessExecutionBackend,
    LocalFileArtifactStore,
    SQLiteCheckpointStore,
)


def test_agentv_runtime_metadata_and_exports():
    import agentv_runtime.interfaces
    import agentv_runtime.reference
    import agentv_runtime.session_components

    assert agentv_runtime.__version__ == "1.9.0-rc1"
    assert agentv_runtime.__runtime_api_version__ == "1.9"
    assert agentv_runtime.__plugin_api_version__ == "1.0"
    assert agentv_runtime.__config_schema_version__ == "1.0"
    assert agentv_runtime.__aes_schema_version__ == "1.4"
    assert issubclass(
        agentv_runtime.reference.InProcessExecutionBackend,
        agentv_runtime.interfaces.ExecutionBackend,
    )
    assert issubclass(
        agentv_runtime.reference.SQLiteCheckpointStore, agentv_runtime.interfaces.CheckpointStore
    )
    assert issubclass(
        agentv_runtime.reference.LocalFileArtifactStore, agentv_runtime.interfaces.ArtifactStore
    )
    assert issubclass(
        agentv_runtime.reference.BasicFieldPolicyEvaluator,
        agentv_runtime.interfaces.PolicyEvaluator,
    )
    assert agentv_runtime.session_components.TurnStateManager is not None
    assert agentv_runtime.session_components.ToolExecutionCoordinator is not None
    assert agentv_runtime.session_components.SessionCheckpointManager is not None
    assert agentv_runtime.session_components.SessionApprovalManager is not None


def test_sqlite_checkpoint_store_lifecycle(tmp_path):
    db_file = str(tmp_path / "test_checkpoints.db")
    store = SQLiteCheckpointStore(db_path=db_file)

    run_id = "run_test_001"
    state_data = {"turn": 3, "step": "transfer_funds", "account": "1234"}
    meta = {"user": "qa_tester"}

    uri = store.save(run_id, "chk_001", state_data, metadata=meta)
    assert "sqlite://" in uri

    loaded = store.load(run_id, "chk_001")
    assert loaded == state_data

    # Load latest
    state_data_2 = {"turn": 4, "step": "complete"}
    store.save(run_id, "chk_002", state_data_2)
    latest = store.load(run_id)
    assert latest == state_data_2

    # List
    chks = store.list_checkpoints(run_id)
    assert len(chks) == 2
    assert chks[0]["checkpoint_id"] == "chk_001"

    # Delete
    assert store.delete(run_id, "chk_001") is True
    assert store.load(run_id, "chk_001") is None
    assert len(store.list_checkpoints(run_id)) == 1


def test_local_file_artifact_store(tmp_path):
    store = LocalFileArtifactStore(base_dir=str(tmp_path))
    run_id = "run_art_100"

    # Store text
    p1 = store.store_artifact(run_id, "summary.json", '{"status": "ok"}', metadata={"type": "json"})
    assert Path(p1).exists()
    assert store.exists(run_id, "summary.json") is True

    # Get bytes
    content = store.get_artifact(run_id, "summary.json")
    assert content == b'{"status": "ok"}'

    # List
    arts = store.list_artifacts(run_id)
    assert len(arts) == 1
    assert arts[0]["name"] == "summary.json"


def test_basic_field_policy_evaluator():
    evaluator = BasicFieldPolicyEvaluator()
    assert evaluator.validate_policy({"id": "p1", "max_value": 1000}) is True

    # Passing evaluation
    res_pass = evaluator.evaluate_policy(
        {"id": "p1", "param_key": "amount", "max_value": 500},
        {"amount": 250, "account": "acc_01"},
    )
    assert res_pass.allowed is True
    assert len(res_pass.violations) == 0

    # Failing evaluation
    res_fail = evaluator.evaluate_policy(
        {"id": "p1", "param_key": "amount", "max_value": 500},
        {"amount": 1000, "account": "acc_01"},
    )
    assert res_fail.allowed is False
    assert len(res_fail.violations) == 1
    assert "exceeds" in res_fail.violations[0]["message"]


def test_inprocess_execution_backend_lifecycle():
    backend = InProcessExecutionBackend()
    assert backend.status("unknown") == {"status": "UNKNOWN"}

    # Mock submission state
    backend._active_runs["run_sim_1"] = {"status": "RUNNING"}
    assert backend.status("run_sim_1")["status"] == "RUNNING"

    # Cancel
    assert backend.cancel("run_sim_1", "Test cancellation") is True
    assert backend.status("run_sim_1")["status"] == "ABORTED"

    # Resume
    res = backend.resume("run_sim_1", "tok_123")
    assert res["status"] == "RUNNING"
    assert res["resumption_token"] == "tok_123"
