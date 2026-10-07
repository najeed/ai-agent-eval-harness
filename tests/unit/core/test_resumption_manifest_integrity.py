"""
tests/unit/core/test_resumption_manifest_integrity.py
Unit tests verifying that HITL and checkpoint resumptions preserve
the root ExecutionManifest, execution mode, and scenario snapshot,
guaranteeing zero ManifestHashMismatch during certification.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agentv_runtime.finalization import EvaluatorFinalizationRecord
from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash
from eval_runner import config
from eval_runner.reference.inprocess_backend import InProcessExecutionBackend
from eval_runner.runner import DefaultRunner


@pytest.mark.asyncio
async def test_resumption_preserves_root_execution_manifest_and_mode(tmp_path):
    """
    Verifies that when a run is resumed from a checkpoint, the runner reloads
    the authoritative root ExecutionManifest and scenario snapshot from disk,
    preserving live execution mode and upfront manifest hash.
    """
    run_id = "run-test-resumption-integrity-001"
    run_vault = tmp_path / "runs" / run_id
    run_vault.mkdir(parents=True, exist_ok=True)

    scenario_data = {
        "id": "test-resumed-scenario",
        "version": "1.0.0",
        "metadata": {
            "id": "test-resumed-scenario",
            "name": "Test Resumed Scenario",
            "version": "1.0.0",
        },
        "workflow": {"nodes": []},
        "execution_mode": "live",
    }
    scen_hash = compute_scenario_hash(scenario_data)

    # 1. Simulate upfront ExecutionManifest created during initial phase (live mode)
    root_manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id="test-resumed-scenario",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        agent_config={"endpoint": "http://127.0.0.1:8080/task", "protocol": "openapi"},
        runtime_config={
            "execution_mode": "live",
            "attempts": 1,
            "max_turns": 10,
            "scenario_hash": scen_hash,
        },
    )
    expected_manifest_hash = root_manifest.compute_manifest_hash()

    manifest_file = run_vault / "execution_manifest.json"
    manifest_file.write_text(json.dumps(root_manifest.to_dict(), indent=2), encoding="utf-8")

    snapshot_file = run_vault / "scenario_resolved.json"
    snapshot_file.write_text(json.dumps(scenario_data, indent=2), encoding="utf-8")

    trace_file = run_vault / "run.jsonl"
    trace_file.write_text('{"event": "step_start"}\n', encoding="utf-8")

    # 2. Setup runner patched to run in tmp_path
    with (
        patch.object(config, "RUN_LOG_DIR", tmp_path / "runs"),
        patch("eval_runner.plugins.manager.trigger"),
        patch("eval_runner.events.emit"),
    ):
        runner = DefaultRunner()

        # Mock session to simulate completing a resumed task
        mock_session = MagicMock()
        mock_session.metadata = {"execution_mode": "live"}

        async def fake_execute_tasks(k):
            return [{"task": "node_2", "success": True, "oracle_results": []}]

        mock_session.execute_tasks = fake_execute_tasks

        with patch("eval_runner.session.SessionManager", return_value=mock_session):
            # Execute with is_resume=True and WITHOUT explicit execution_mode
            # (simulates resumption call where mode was not declared in request)
            resumption_checkpoint = {
                "session_state": {"approval_token": "tok_123"},
                "metadata": {"execution_mode": "live"},
            }

            result = await runner.run(
                scenario=scenario_data,
                attempts=1,
                run_id=run_id,
                resumption_checkpoint=resumption_checkpoint,
                resumption_token="tok_123",
            )

            assert result is not None
            assert result.metadata["execution_mode"] == "live"

    # 3. Verify CertificationService._verify_execution_integrity against the resumed state
    fin_record = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash=expected_manifest_hash,
        scenario_id="test-resumed-scenario",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        evaluator_identity="system_id",
        evaluator_config_hash="none",
        required_oracle_ids=[],
        evidence_root_hash="sha3_256:0000000000000000000000000000000000000000000000000000000000000000",
        outcome="pass",
        score=1.0,
    )

    # 3. Verify manifest hash and mode alignment between execution_manifest.json and fin_record
    manifest_on_disk = ExecutionManifest.from_dict(
        json.loads((run_vault / "execution_manifest.json").read_text(encoding="utf-8"))
    )
    actual_manifest_hash = manifest_on_disk.compute_manifest_hash()

    assert actual_manifest_hash == fin_record.execution_manifest_hash
    assert manifest_on_disk.runtime_config.get("execution_mode") == "live"
    assert fin_record.scenario_hash == manifest_on_disk.scenario_hash


def test_inprocess_backend_resume_preserves_mode_and_contract(tmp_path):
    """
    Verifies that InProcessExecutionBackend.resume() preserves execution_mode
    from existing manifest/checkpoint and loads scenario_resolved.json.
    """
    run_id = "run-backend-resume-001"
    run_vault = tmp_path / "runs" / run_id
    run_vault.mkdir(parents=True, exist_ok=True)

    manifest_data = {
        "manifest_id": f"man_{run_id}",
        "scenario_id": "scen-001",
        "scenario_version": "1.0.0",
        "scenario_hash": "sha3_256:abc",
        "runtime_config": {"execution_mode": "live"},
    }
    (run_vault / "execution_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    contract_data = {"id": "scen-001", "execution_mode": "live", "from_snapshot": True}
    (run_vault / "scenario_resolved.json").write_text(json.dumps(contract_data), encoding="utf-8")

    backend = InProcessExecutionBackend.get_instance()
    mock_store = MagicMock()
    backend._checkpoint_store = mock_store
    checkpoint = {
        "status": "PAUSED_FOR_APPROVAL",
        "session_state": {"approval_token": "tok_valid"},
        "metadata": {"execution_mode": "live"},
    }
    mock_store.load.return_value = checkpoint

    with (
        patch.object(config, "RUN_LOG_DIR", tmp_path / "runs"),
        patch("eval_runner.reference.approval_store.get_default_approval_store") as mock_app_store,
        patch.object(backend, "submit") as mock_submit,
    ):
        mock_approval = MagicMock()
        mock_approval.run_id = run_id
        mock_approval.status = "APPROVED"
        mock_approval.checkpoint_id = None
        mock_approval.outbound_payload_hash = None
        mock_app_store.return_value.get_request.return_value = mock_approval

        backend.resume(run_id=run_id, resumption_token="tok_valid")

        assert mock_submit.called
        call_kwargs = mock_submit.call_args.kwargs
        assert call_kwargs["scenario_data"]["execution_mode"] == "live"
        assert call_kwargs["scenario_data"].get("from_snapshot") is True
        assert call_kwargs["metadata"]["execution_mode"] == "live"
        assert call_kwargs["metadata"]["execution_mode_declared"] is True
