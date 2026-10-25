"""
tests/contracts/test_cold_restart_durability.py
Cold Process Restart & Checkpoint Durability Contract Tests (Runtime 2.0.0 GA).

Proves that:
  1. A paused/HITL-awaiting run creates a durable checkpoint in CheckpointStore.
  2. Complete process death / restart (simulated by destroying in-memory backend state)
     does not lose execution viability.
  3. A freshly instantiated backend can resume solely from the persisted checkpoint.
  4. Resumption strictly enforces state machine guards and resumption token validity.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agentv_runtime.interfaces import ApprovalRequest
from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash
from agentv_runtime.results import EvaluationResult
from eval_runner.reference.approval_store import FileApprovalStore
from eval_runner.reference.inprocess_backend import InProcessExecutionBackend
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.reference.sqlite_checkpoint import SQLiteCheckpointStore


class TestColdRestartDurabilityContract:
    """Contract test verifying cold-process restart durability from CheckpointStore."""

    @pytest.mark.asyncio
    async def test_cold_restart_resumption_from_persisted_checkpoint(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
            runs_dir = Path(tmp_dir) / "runs"
            runs_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(Path(tmp_dir) / "checkpoints.db")

            with (
                patch.dict(os.environ, {"RUN_LOG_DIR": str(runs_dir)}),
                patch("eval_runner.config.RUN_LOG_DIR", runs_dir),
            ):
                chk_store_1 = SQLiteCheckpointStore(db_path=db_path)
                scope_a = {"tenant_id": "scope-a", "org_id": "org_corp_fin"}
                scope_b = {"tenant_id": "scope-b", "org_id": "org_corp_fin"}

                run_store_1 = LocalFileRunStore(runs_dir)
                backend_1 = InProcessExecutionBackend(
                    checkpoint_store=chk_store_1, run_store=run_store_1
                )
                run_id = "run-cold-restart-001"
                resumption_token = "tok-hitl-approval-xyz"

                from eval_runner.runner import compile_required_oracle_ids

                scenario = {
                    "id": "cold_restart_scenario",
                    "metadata": {"name": "Cold Restart Scenario", "org_id": "org_corp_fin"},
                    "workflow": [
                        {
                            "id": "step_1",
                            "tool": "noop",
                            "params": {"amount": 1000},
                            "success_criteria": [
                                {
                                    "metric": "generic_accuracy",
                                    "threshold": 1.0,
                                }
                            ],
                        }
                    ],
                }
                manifest = ExecutionManifest(
                    manifest_id=f"man_{run_id}",
                    scenario_id="cold_restart_scenario",
                    scenario_version="1.0.0",
                    scenario_hash=compute_scenario_hash(scenario),
                    scope=scope_a,
                    metadata={"required_oracle_ids": compile_required_oracle_ids(scenario)},
                )
                run_store_1.create_run(run_id, scenario["id"], context=scope_a)
                run_store_1.save_run_manifest(
                    run_id,
                    {
                        "execution_manifest": manifest.to_dict(),
                        "scenario_data": scenario,
                        "context": scope_a,
                        "status": "PAUSED_FOR_APPROVAL",
                    },
                    context=scope_a,
                )
                run_store_1.update_run_status(run_id, "PAUSED_FOR_APPROVAL", context=scope_a)

                # 1. Simulate active execution pausing at HITL checkpoint
                checkpoint_data = {
                    "run_id": run_id,
                    "status": "PAUSED_FOR_APPROVAL",
                    "resumption_token": resumption_token,
                    "scenario_data": scenario,
                    "turn_number": 1,
                    "session_state": {
                        "status": "PAUSED_FOR_APPROVAL",
                        "turn_number": 1,
                        "approval_token": resumption_token,
                        "completed_node_results": {},
                    },
                }
                chk_store_1.save(run_id, "checkpoint_turn_1", checkpoint_data)
                approval_store = FileApprovalStore(base_dir=Path(tmp_dir) / "approvals")
                approval_store.create_request(
                    ApprovalRequest(
                        approval_token=resumption_token,
                        run_id=run_id,
                        turn_index=1,
                        outbound_payload_hash="sha256:fedcba",
                        checkpoint_id="checkpoint_turn_1",
                        status="APPROVED",
                        scope=scope_a,
                        metadata={"org_id": "org_corp_fin", "task_id": "step_1"},
                    )
                )

                # 2. Simulate complete process termination & restart:
                # - Destroy backend_1, chk_store_1, and run_store_1
                # - Create brand new backend_2 with new SQLiteCheckpointStore AND new run_store_2
                del backend_1
                del chk_store_1
                del run_store_1

                chk_store_2 = SQLiteCheckpointStore(db_path=db_path)
                run_store_2 = LocalFileRunStore(runs_dir)
                backend_2 = InProcessExecutionBackend(
                    checkpoint_store=chk_store_2, run_store=run_store_2
                )

                # Verify in-memory state in backend_2 is completely cold
                assert run_id not in backend_2._active_runs

                # Status check queries durable store on cold read
                st = backend_2.status(run_id)
                assert st["status"] == "PAUSED_FOR_APPROVAL"

                # Scope-B denial assertion: run_store_2 denies scope-b
                assert run_store_2.get_run(run_id, context=scope_b) is None

                # Scope-B denial assertion: backend_2 denies resumption fail-closed
                with pytest.raises((RuntimeError, PermissionError)):
                    backend_2.resume(
                        run_id=run_id,
                        resumption_token=resumption_token,
                        context=scope_b,
                    )

                # 3. Resume from cold backend solely using persisted checkpoint under scope-a
                def _agent_side_effect(protocol, endpoint, message, history, turn_ctx):
                    return {
                        "status": "success",
                        "action": "final_answer",
                        "content": "Disbursed",
                    }

                with (
                    patch(
                        "eval_runner.session.AgentAdapterRegistry.call_agent",
                        AsyncMock(side_effect=_agent_side_effect),
                    ),
                    patch(
                        "eval_runner.reference.approval_store.get_default_approval_store",
                        return_value=approval_store,
                    ),
                ):
                    resumed_result = backend_2.resume(
                        run_id=run_id,
                        resumption_token=resumption_token,
                        context=scope_a,
                        metadata={"runtime_context": scope_a},
                        background=False,
                    )

                assert isinstance(resumed_result, (EvaluationResult, list))
                assert backend_2.status(run_id)["status"] == "COMPLETED"
                assert run_store_2.get_run(run_id, context=scope_a)["status"] == "COMPLETED"

    def test_cold_restart_rejects_resumption_of_terminal_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "checkpoints.db")
            chk_store = SQLiteCheckpointStore(db_path=db_path)
            run_id = "run-terminal-checkpoint"

            # Save completed/terminal checkpoint
            chk_store.save(
                run_id,
                "checkpoint_final",
                {
                    "run_id": run_id,
                    "status": "COMPLETED",
                    "scenario_data": {"id": "scen_term"},
                },
            )

            backend = InProcessExecutionBackend(checkpoint_store=chk_store)

            # Attempting to resume a completed run on cold restart must fail-closed
            with pytest.raises(RuntimeError, match="reached terminal state 'COMPLETED'"):
                backend.resume(run_id, "token_123")
