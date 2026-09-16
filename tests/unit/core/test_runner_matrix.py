"""
Branch coverage matrix for eval_runner/runner.py.

Statement and branch coverage for DefaultRunner,
dependency graphs, cancellation, pass@k calculation, node/oracle verdict
gating, run_scenario synchronous orchestrator, and error handlers.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
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


@pytest.mark.asyncio
async def test_default_runner_manifest_persistence_failure(tmp_path, monkeypatch):
    import json

    runner = DefaultRunner()
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)
    scenario = {"id": "test_scen_fail", "version": "1.0.0"}
    with patch("eval_runner.session.SessionManager") as mock_session:
        mock_session.return_value.execute_tasks = AsyncMock(return_value=[])
        original_dump = json.dump

        def _failing_dump(obj, fp, *args, **kwargs):
            if "execution_manifest.json" in getattr(fp, "name", ""):
                raise OSError("Simulated disk error writing manifest")
            return original_dump(obj, fp, *args, **kwargs)

        with patch("json.dump", side_effect=_failing_dump):
            res = await runner.run(scenario, attempts=1)
            assert res is not None


@pytest.mark.asyncio
async def test_default_runner_trace_read_failure_and_assertion_fallbacks(tmp_path, monkeypatch):
    runner = DefaultRunner()
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)
    scenario = {"id": "test_scen_assertions"}

    run_dir = tmp_path / "run_assertions_test"
    run_dir.mkdir(parents=True, exist_ok=True)
    # Bad JSON line triggers JSONDecodeError on read
    (run_dir / "run.jsonl").write_text("invalid json line\n", encoding="utf-8")

    sample_attempt = [
        123,  # non-dict inner row to hit line 380
        {
            "workflow_verdict": {"status": "completed"},
            "oracle_results": [
                "oracle_str_id",
                {"oracle_id": "oracle_dict_id", "passed": True},
            ],
            "metrics": [
                "metric_str_id",
                {"name": "metric_dict_name", "passed": True},
            ],
        },
    ]

    with patch("eval_runner.session.SessionManager") as mock_session:
        mock_session.return_value.execute_tasks = AsyncMock(return_value=sample_attempt)
        res = await runner.run(scenario, attempts=1, run_id="run_assertions_test")
        assert res is not None


@pytest.mark.asyncio
async def test_default_runner_evaluator_signing_none_key_and_exception(tmp_path, monkeypatch):
    runner = DefaultRunner()
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)
    scenario = {"id": "test_scen_sign_exc"}

    # 1. IdentityService returns None -> fallback self-signing
    with patch("eval_runner.session.SessionManager") as mock_session:
        mock_session.return_value.execute_tasks = AsyncMock(return_value=[])
        with patch("eval_runner.identity.IdentityService.get_private_key", return_value=None):
            res_none = await runner.run(scenario, attempts=1)
            assert res_none is not None

    # 2. IdentityService raises exception -> caught and logged
    with patch("eval_runner.session.SessionManager") as mock_session:
        mock_session.return_value.execute_tasks = AsyncMock(return_value=[])
        with patch(
            "eval_runner.identity.IdentityService.get_private_key",
            side_effect=RuntimeError("KMS unavailable"),
        ):
            res_exc = await runner.run(scenario, attempts=1)
            assert res_exc is not None


@pytest.mark.asyncio
async def test_runner_compile_required_oracle_ids_matrix():
    from eval_runner.runner import compile_required_oracle_ids

    # 1. Explicit declaration or-chain
    assert compile_required_oracle_ids({"required_oracles": ["o1"]}) == ["o1"]
    assert compile_required_oracle_ids({"required_oracle_ids": ["o2"]}) == ["o2"]
    assert compile_required_oracle_ids({"metadata": {"required_oracles": ["o3"]}}) == ["o3"]
    assert compile_required_oracle_ids({"metadata": {"required_oracle_ids": ["o4"]}}) == ["o4"]
    assert compile_required_oracle_ids({"required_oracles": ["dup", "dup", "  "]}) == ["dup"]

    # 2. Plan compilation exception
    with patch(
        "eval_runner.execution_ir.compile_evaluation_plan", side_effect=ValueError("Plan parse err")
    ):
        assert compile_required_oracle_ids({"id": "err_scen"}) == []

    # 3. Plan compilation with required and non-required oracles and duplicates
    mock_plan = MagicMock()
    mock_plan.oracles = {
        "req_oracle": MagicMock(required=True),
        "opt_oracle": MagicMock(required=False),
        "req_oracle_dup": MagicMock(required=True),
    }
    with patch("eval_runner.execution_ir.compile_evaluation_plan", return_value=mock_plan):
        compiled_plan = compile_required_oracle_ids(
            {"id": "plan_scen", "required_oracles": ["req_oracle_dup"]}
        )
        assert "req_oracle" in compiled_plan
        assert "opt_oracle" not in compiled_plan
        assert "req_oracle_dup" in compiled_plan

    # 4. success_criteria, expected_outcome, and oracles
    scen_criteria = {
        "id": "crit_scen",
        "success_criteria": [
            {"oracle_id": "sc_req", "required": True},
            {"id": "sc_opt", "required": False},
            {"oracle_id": "sc_dup", "required": True},
            "sc_str",
            "sc_str",
        ],
        "expected_outcome": [
            {"name": "eo_name", "required": True},
            "eo_str",
        ],
        "oracles": [
            {"oracle_id": "or_req", "required": True},
            "or_str",
        ],
    }
    compiled_crit = compile_required_oracle_ids(scen_criteria)
    assert "sc_req" in compiled_crit
    assert "sc_opt" not in compiled_crit
    assert "sc_str" in compiled_crit
    assert "eo_name" in compiled_crit
    assert "eo_str" in compiled_crit
    assert "or_req" in compiled_crit
    assert "or_str" in compiled_crit


@pytest.mark.asyncio
async def test_runner_otel_and_seeding_branches(tmp_path, monkeypatch):
    runner = DefaultRunner()
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)

    # 1. Metadata traceparent
    with patch("eval_runner.session.SessionManager") as mock_session:
        mock_session.return_value.execute_tasks = AsyncMock(return_value=[])
        res_tp = await runner.run(
            {"id": "otel_scen"},
            metadata={"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"},
        )
        assert res_tp is not None

    # 2. Scenario span_context
    with patch("eval_runner.session.SessionManager") as mock_session:
        mock_session.return_value.execute_tasks = AsyncMock(return_value=[])
        res_sc = await runner.run(
            {
                "id": "otel_scen_2",
                "span_context": {
                    "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
                },
            },
        )
        assert res_sc is not None

    # 3. OTel init exception
    with patch("eval_runner.session.SessionManager") as mock_session:
        mock_session.return_value.execute_tasks = AsyncMock(return_value=[])
        with patch("opentelemetry.trace.get_tracer", side_effect=RuntimeError("OTel init err")):
            res_otel_err = await runner.run({"id": "otel_err_scen"})
            assert res_otel_err is not None

    # 4. OTel cleanup exception where span.end() raises
    mock_span = MagicMock()
    mock_span.end.side_effect = RuntimeError("OTel span end err")
    mock_tracer = MagicMock()
    mock_tracer.start_span.return_value = mock_span
    with patch("eval_runner.session.SessionManager") as mock_session:
        mock_session.return_value.execute_tasks = AsyncMock(return_value=[])
        with patch("opentelemetry.trace.get_tracer", return_value=mock_tracer):
            with patch("opentelemetry.trace.get_current_span", return_value=mock_span):
                res_otel_clean_err = await runner.run({"id": "otel_clean_err_scen"})
                assert res_otel_clean_err is not None

    # 5. Deterministic seeding (ctx.seed is not None with multiple attempts)
    with patch("eval_runner.session.SessionManager") as mock_session:
        mock_session.return_value.execute_tasks = AsyncMock(return_value=[])
        res_seed = await runner.run({"id": "seed_scen"}, attempts=2, seed=12345)
        assert res_seed is not None


@pytest.mark.asyncio
async def test_runner_trace_and_assertion_branches(tmp_path, monkeypatch):
    import json

    runner = DefaultRunner()
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)

    # 1. Trace reading with blank lines, non-dict/non-string metric (12345),
    # and consistency_score metric filtering
    run_dir = tmp_path / "run_blank_lines"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text(
        "\n  \n" + json.dumps({"event": "node_started", "node_id": "n1"}) + "\n\n",
        encoding="utf-8",
    )
    sample_attempt_with_metrics = [
        {
            "workflow_verdict": {"status": "workflow_completed"},
            "metrics": [
                {"metric": "consistency_score"},
                {"oracle_id": "consistency_score"},
                "consistency_score",
                "regular_metric",
                12345,  # non-dict, non-str to cover branch 530->522
            ],
        }
    ]
    with patch("eval_runner.session.SessionManager") as mock_session:
        mock_session.return_value.execute_tasks = AsyncMock(
            return_value=sample_attempt_with_metrics
        )
        res_blank = await runner.run({"id": "scen_blank"}, run_id="run_blank_lines")
        assert res_blank is not None

    # 2. Trace file does not exist (covers 541->551)
    orig_exists = Path.exists

    def _fake_exists(p):
        if str(p).endswith("run.jsonl"):
            return False
        return orig_exists(p)

    with patch("eval_runner.session.SessionManager") as mock_session:
        mock_session.return_value.execute_tasks = AsyncMock(
            return_value=sample_attempt_with_metrics
        )
        with patch.object(Path, "exists", _fake_exists):
            res_no_trace = await runner.run({"id": "scen_no_trace"}, run_id="run_no_trace_dir")
            assert res_no_trace is not None

    # 3. Missing signature branch after signing attempt
    with patch("eval_runner.session.SessionManager") as mock_session:
        mock_session.return_value.execute_tasks = AsyncMock(return_value=[])
        mock_fin = MagicMock()
        mock_fin.evaluator_signature = None
        mock_fin.signature = None
        mock_fin.sign.return_value = mock_fin
        with patch(
            "agentv_runtime.finalization.EvaluatorFinalizationRecord", return_value=mock_fin
        ):
            res_nosig = await runner.run({"id": "scen_nosig"})
            assert res_nosig is not None


def test_runner_is_attempt_successful_branches():
    runner = DefaultRunner()

    # 1. Empty attempt results
    assert runner._is_attempt_successful([]) is False

    # 2. No verdict rows
    assert runner._is_attempt_successful([{"no_verdict": 1}]) is False

    # 3. Status not completed
    assert runner._is_attempt_successful([{"workflow_verdict": {"status": "failed"}}]) is False

    # 4. Successful attempt with all branches
    successful_attempt = [
        "not_a_dict_row",
        {
            "workflow_verdict": {"status": "workflow_completed"},
            "evaluation_valid": True,
            "node_verdict": {
                "verification": "success",
                "policy": "allowed",
                "parity": "success",
                "overall": "success",
            },
            "oracle_results": [
                {"requiredness": "OPTIONAL", "outcome": "FAIL"},
                {"requiredness": "REQUIRED", "outcome": "PASS"},
            ],
            "metrics": [
                {"severity": "informational", "outcome": "FAIL"},
                {"requiredness": "OPTIONAL", "outcome": "FAIL"},
                {"metric": "m1", "success": True, "outcome": "PASS"},
            ],
            "state_hygiene": [
                {"requiredness": "OPTIONAL", "outcome": "FAIL"},
                {"check": "h1", "success": True, "outcome": "PASS"},
            ],
            "state_parity": [
                {"requiredness": "OPTIONAL", "outcome": "FAIL"},
                {"check": "p1", "success": True, "outcome": "PASS"},
            ],
            "policy_checks": [
                {"check": "pc1", "decision": "allowed"},
            ],
        },
    ]
    assert runner._is_attempt_successful(successful_attempt) is True

    # 5. Branch failures
    base_success = {
        "workflow_verdict": {"status": "workflow_completed"},
        "evaluation_valid": True,
    }
    assert (
        runner._is_attempt_successful([{**base_success, "triage_tag": "EVALUATION_INVALID"}])
        is False
    )
    assert runner._is_attempt_successful([{**base_success, "evaluation_valid": False}]) is False
    assert (
        runner._is_attempt_successful([{**base_success, "node_verdict": {"verification": "fail"}}])
        is False
    )
    assert (
        runner._is_attempt_successful([{**base_success, "node_verdict": {"policy": "denied"}}])
        is False
    )
    assert (
        runner._is_attempt_successful([{**base_success, "node_verdict": {"parity": "fail"}}])
        is False
    )
    assert (
        runner._is_attempt_successful([{**base_success, "node_verdict": {"overall": "fail"}}])
        is False
    )
    assert (
        runner._is_attempt_successful(
            [{**base_success, "oracle_results": [{"requiredness": "REQUIRED", "outcome": "FAIL"}]}]
        )
        is False
    )
    assert (
        runner._is_attempt_successful([{**base_success, "metrics": [{"success": False}]}]) is False
    )
    assert (
        runner._is_attempt_successful([{**base_success, "state_hygiene": [{"invalid": True}]}])
        is False
    )
    assert (
        runner._is_attempt_successful([{**base_success, "state_hygiene": [{"success": False}]}])
        is False
    )
    assert (
        runner._is_attempt_successful([{**base_success, "state_parity": [{"invalid": True}]}])
        is False
    )
    assert (
        runner._is_attempt_successful([{**base_success, "state_parity": [{"success": False}]}])
        is False
    )
    assert (
        runner._is_attempt_successful([{**base_success, "policy_checks": [{"decision": "denied"}]}])
        is False
    )
