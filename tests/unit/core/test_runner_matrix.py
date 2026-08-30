"""
Branch coverage matrix for eval_runner/runner.py.

Statement and branch coverage for DefaultRunner,
dependency graphs, cancellation, pass@k calculation, node/oracle verdict
gating, run_scenario synchronous orchestrator, and error handlers.
"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentv_runtime.config import ResolvedRuntimeConfig
from eval_runner.execution_ir import WorkflowStatus
from eval_runner.runner import DefaultRunner, run_scenario


@pytest.mark.asyncio
async def test_runner_init_and_dependency_graph():
    # 1. Init with execution_backend supporting set_dependency_graph
    mock_exec_backend = MagicMock()
    runner = DefaultRunner(execution_backend=mock_exec_backend)
    assert mock_exec_backend.set_dependency_graph.called

    # 2. set_dependency_graph method on DefaultRunner with dict
    mock_art = MagicMock()
    mock_ckpt = MagicMock()
    mock_pol = MagicMock()
    mock_sign = MagicMock()
    mock_cfg_res = MagicMock()
    mock_run_store = MagicMock()

    runner.set_dependency_graph(
        artifact_store=mock_art,
        checkpoint_store=mock_ckpt,
        policy_evaluator=mock_pol,
        signing_backend=mock_sign,
        config_resolver=mock_cfg_res,
        run_store=mock_run_store,
        resolved_config={"audit_level": 3},
    )
    assert runner.artifact_store == mock_art
    assert runner.checkpoint_store == mock_ckpt
    assert runner.policy_evaluator == mock_pol
    assert runner.signing_backend == mock_sign
    assert runner.config_resolver == mock_cfg_res
    assert runner.run_store == mock_run_store
    assert isinstance(runner.resolved_config, ResolvedRuntimeConfig)
    assert runner.resolved_config.audit_level == 3

    # Set resolved_config as instance of ResolvedRuntimeConfig
    r_cfg = ResolvedRuntimeConfig(audit_level=1)
    runner.set_dependency_graph(resolved_config=r_cfg)
    assert runner.resolved_config == r_cfg

    # Non-dict, non-ResolvedRuntimeConfig object ignored cleanly
    runner.set_dependency_graph(resolved_config="not_a_valid_config_obj")
    assert runner.resolved_config == r_cfg

    # Set run_store with resolved_config=None
    runner.set_dependency_graph(run_store=MagicMock(), resolved_config=None)
    assert runner.run_store is not None


@pytest.mark.asyncio
async def test_runner_cancellation_and_max_turns(tmp_path):
    # 1. Cancellation before start
    cancel_event = threading.Event()
    cancel_event.set()

    scenario = {
        "id": "scenario-cancel",
        "workflow": {"nodes": [{"id": "n1", "success_criteria": [{"metric": "m1"}]}]},
    }

    runner = DefaultRunner(run_store=None)
    result = await runner.run(
        scenario=scenario,
        attempts=3,
        cancellation_event=cancel_event,
    )
    assert len(result.attempts_results) == 0
    assert result.total_attempts == 3

    # 2. max_turns without cancellation and with run_store=None (covers if self.run_store is None)
    runner.run_store = None
    with patch(
        "eval_runner.session.SessionManager.execute_tasks", new_callable=AsyncMock
    ) as mock_exec:
        mock_exec.return_value = [
            {
                "workflow_verdict": {"status": WorkflowStatus.COMPLETED.value},
                "evaluation_valid": True,
            }
        ]
        res_turns = await runner.run(
            scenario=scenario,
            attempts=1,
            max_turns=5,
        )
        assert res_turns.pass_at_k == 1.0


@pytest.mark.asyncio
async def test_runner_error_handling_in_post_processing():
    scenario = {
        "id": "scenario-err-post",
        "workflow": {"nodes": [{"id": "n1", "success_criteria": [{"metric": "m1"}]}]},
    }

    mock_run_store = MagicMock()
    mock_run_store.save_run_manifest.side_effect = RuntimeError("Manifest save error")
    runner = DefaultRunner(run_store=mock_run_store)

    # Patch compute_attempt_statistics to throw an exception
    with patch(
        "eval_runner.runner.compute_attempt_statistics", side_effect=RuntimeError("Stats error")
    ):
        with patch(
            "eval_runner.session.SessionManager.execute_tasks", new_callable=AsyncMock
        ) as mock_exec:
            mock_exec.return_value = [
                {
                    "workflow_verdict": {"status": WorkflowStatus.COMPLETED.value},
                    "evaluation_valid": True,
                }
            ]
            result = await runner.run(scenario=scenario, attempts=2)
            assert result.pass_at_k == 0.0


def test_is_attempt_successful_full_matrix():
    runner = DefaultRunner()

    # 1. Empty rows
    assert not runner._is_attempt_successful([])

    # 2. No workflow verdict or non-completed status
    assert not runner._is_attempt_successful([{"no_verdict": True}])
    assert not runner._is_attempt_successful(
        [{"workflow_verdict": {"status": WorkflowStatus.FAILED.value}}]
    )

    base_valid = [{"workflow_verdict": {"status": WorkflowStatus.COMPLETED.value}}]

    # 3. triage_tag and evaluation_valid
    assert not runner._is_attempt_successful(base_valid + [{"triage_tag": "EVALUATION_INVALID"}])
    assert not runner._is_attempt_successful(base_valid + [{"evaluation_valid": False}])

    # 4. NodeVerdict checks: verification fail/invalid, policy denied, parity fail, overall invalid
    assert not runner._is_attempt_successful(
        base_valid + [{"node_verdict": {"verification": "fail", "overall": "verification_failed"}}]
    )
    assert not runner._is_attempt_successful(
        base_valid
        + [
            {
                "node_verdict": {
                    "verification": "pass",
                    "policy": "denied",
                    "overall": "policy_denied",
                }
            }
        ]
    )
    assert not runner._is_attempt_successful(
        base_valid
        + [
            {
                "node_verdict": {
                    "verification": "pass",
                    "policy": "pass",
                    "parity": "fail",
                    "overall": "parity_failed",
                }
            }
        ]
    )
    assert not runner._is_attempt_successful(
        base_valid
        + [
            {
                "node_verdict": {
                    "verification": "pass",
                    "policy": "pass",
                    "parity": "pass",
                    "overall": "other_failed",
                }
            }
        ]
    )

    # 5. OracleResult checks: REQUIRED with FAIL / INVALID / NOT_EVALUATED vs OPTIONAL
    assert not runner._is_attempt_successful(
        base_valid + [{"oracle_results": [{"requiredness": "REQUIRED", "outcome": "FAIL"}]}]
    )
    assert not runner._is_attempt_successful(
        base_valid + [{"oracle_results": [{"requiredness": "REQUIRED", "outcome": "INVALID"}]}]
    )
    assert not runner._is_attempt_successful(
        base_valid
        + [{"oracle_results": [{"requiredness": "REQUIRED", "outcome": "NOT_EVALUATED"}]}]
    )
    assert runner._is_attempt_successful(
        base_valid + [{"oracle_results": [{"requiredness": "OPTIONAL", "outcome": "FAIL"}]}]
    )

    # 6. Metrics severity/requiredness
    assert not runner._is_attempt_successful(
        base_valid + [{"metrics": [{"requiredness": "REQUIRED", "outcome": "FAIL"}]}]
    )
    assert runner._is_attempt_successful(
        base_valid + [{"metrics": [{"severity": "informational", "outcome": "FAIL"}]}]
    )

    # 7. State hygiene: invalid, optional, failed
    assert not runner._is_attempt_successful(base_valid + [{"state_hygiene": [{"invalid": True}]}])
    assert not runner._is_attempt_successful(
        base_valid + [{"state_hygiene": [{"status": "EVALUATION_INVALID"}]}]
    )
    assert not runner._is_attempt_successful(
        base_valid + [{"state_hygiene": [{"requiredness": "REQUIRED", "outcome": "FAIL"}]}]
    )
    assert runner._is_attempt_successful(
        base_valid + [{"state_hygiene": [{"requiredness": "OPTIONAL", "outcome": "FAIL"}]}]
    )

    # 8. State parity: invalid, optional, failed, and pass-through
    assert not runner._is_attempt_successful(base_valid + [{"state_parity": [{"invalid": True}]}])
    assert not runner._is_attempt_successful(
        base_valid + [{"state_parity": [{"status": "EVALUATION_INVALID"}]}]
    )
    assert not runner._is_attempt_successful(
        base_valid + [{"state_parity": [{"requiredness": "REQUIRED", "outcome": "FAIL"}]}]
    )
    assert runner._is_attempt_successful(
        base_valid
        + [
            {
                "state_parity": [
                    {"requiredness": "REQUIRED", "outcome": "PASS", "success": True},
                    {"requiredness": "INFORMATIONAL", "outcome": "FAIL", "success": False},
                ]
            }
        ]
    )

    # 9. Policy checks: denied
    assert not runner._is_attempt_successful(
        base_valid + [{"policy_checks": [{"decision": "denied"}]}]
    )


def test_calculate_pass_at_k():
    runner = DefaultRunner()
    all_results = [
        [
            {
                "workflow_verdict": {"status": WorkflowStatus.COMPLETED.value},
                "evaluation_valid": True,
            }
        ],
        [{"workflow_verdict": {"status": WorkflowStatus.FAILED.value}, "evaluation_valid": False}],
    ]
    p_at_1 = runner.calculate_pass_at_k(all_results, 1)
    assert p_at_1 == 0.5


def test_run_scenario_sync_orchestrator():
    scenario = {
        "id": "sync-orch-test",
        "workflow": {"nodes": [{"id": "n1", "success_criteria": [{"metric": "m1"}]}]},
    }

    mock_runner = MagicMock()
    mock_runner.run = AsyncMock()
    mock_runner.run.return_value = MagicMock(pass_at_k=1.0)

    # 1. Injected existing runner with set_dependency_graph
    res1 = run_scenario(scenario, runner=mock_runner, run_store=MagicMock())
    assert res1.pass_at_k == 1.0
    assert mock_runner.set_dependency_graph.called

    # 2. Injected runner without set_dependency_graph
    mock_runner_no_dep = MagicMock(spec=[])
    mock_runner_no_dep.run = AsyncMock(return_value=MagicMock(pass_at_k=1.0))
    res_no_dep = run_scenario(scenario, runner=mock_runner_no_dep)
    assert res_no_dep.pass_at_k == 1.0

    # 3. runner=None, creating DefaultRunner
    with patch("eval_runner.runner.DefaultRunner.run", new_callable=AsyncMock) as mock_default_run:
        mock_default_run.return_value = MagicMock(pass_at_k=1.0)
        res2 = run_scenario(scenario, runner=None)
        assert res2.pass_at_k == 1.0

    # 4. run_scenario in a fresh thread with no event loop (triggers RuntimeError -> new_event_loop)
    import threading

    def _run_in_thread():
        asyncio.set_event_loop(None)
        with patch("eval_runner.runner.DefaultRunner.run", new_callable=AsyncMock) as mock_r:
            mock_r.return_value = MagicMock(pass_at_k=1.0)
            res = run_scenario(scenario, runner=None)
            assert res.pass_at_k == 1.0

    t = threading.Thread(target=_run_in_thread)
    t.start()
    t.join()


@pytest.mark.asyncio
async def test_run_scenario_from_async_context():
    scenario = {
        "id": "sync-orch-from-async",
        "workflow": {"nodes": [{"id": "n1", "success_criteria": [{"metric": "m1"}]}]},
    }
    with patch("eval_runner.runner.DefaultRunner.run", new_callable=AsyncMock) as mock_default_run:
        mock_default_run.return_value = MagicMock(pass_at_k=1.0)
        res = run_scenario(scenario, runner=None)
        assert res.pass_at_k == 1.0
