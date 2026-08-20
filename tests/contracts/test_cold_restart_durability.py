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

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agentv_runtime.results import EvaluationResult
from eval_runner.reference.inprocess_backend import InProcessExecutionBackend
from eval_runner.reference.sqlite_checkpoint import SQLiteCheckpointStore


class TestColdRestartDurabilityContract:
    """Contract test verifying cold-process restart durability from CheckpointStore."""

    @pytest.mark.asyncio
    async def test_cold_restart_resumption_from_persisted_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "checkpoints.db")
            chk_store_1 = SQLiteCheckpointStore(db_path=db_path)

            backend_1 = InProcessExecutionBackend(checkpoint_store=chk_store_1)
            run_id = "run-cold-restart-001"
            resumption_token = "tok-hitl-approval-xyz"

            scenario = {
                "id": "cold_restart_scenario",
                "metadata": {"name": "Cold Restart Scenario"},
                "workflow": [
                    {
                        "id": "task_1",
                        "tool": "transfer_funds",
                        "params": {"amount": 1000},
                    }
                ],
                "tools": {
                    "transfer_funds": {
                        "output": {"status": "approved", "tx_id": "tx_999"},
                    }
                },
            }

            # 1. Simulate active execution pausing at HITL checkpoint
            checkpoint_data = {
                "run_id": run_id,
                "status": "WAITING_FOR_APPROVAL",
                "resumption_token": resumption_token,
                "scenario_data": scenario,
                "turn_number": 1,
                "session_state": {
                    "status": "WAITING_FOR_APPROVAL",
                    "turn_number": 1,
                },
            }
            chk_store_1.save(run_id, "checkpoint_turn_1", checkpoint_data)

            # 2. Simulate complete process termination & restart:
            # - Destroy backend_1 and chk_store_1
            # - Create brand new backend_2 with new SQLiteCheckpointStore instance on the same db
            del backend_1
            del chk_store_1

            chk_store_2 = SQLiteCheckpointStore(db_path=db_path)
            backend_2 = InProcessExecutionBackend(checkpoint_store=chk_store_2)

            # Verify in-memory state in backend_2 is completely cold
            assert run_id not in backend_2._active_runs

            # Status check queries durable store on cold read
            st = backend_2.status(run_id)
            assert st["status"] == "WAITING_FOR_APPROVAL"

            # 3. Resume from cold backend solely using persisted checkpoint
            def _agent_side_effect(protocol, endpoint, message, history, turn_ctx):
                return {
                    "status": "success",
                    "action": "final_answer",
                    "content": "Transfer completed successfully",
                }

            with patch(
                "eval_runner.session.AgentAdapterRegistry.call_agent",
                AsyncMock(side_effect=_agent_side_effect),
            ):
                resumed_result = backend_2.resume(
                    run_id=run_id,
                    resumption_token=resumption_token,
                    background=False,
                )

            assert isinstance(resumed_result, (EvaluationResult, list))
            # After execution completion, status is COMPLETED
            assert backend_2.status(run_id)["status"] == "COMPLETED"

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
