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
from eval_runner.events import CoreEvents
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
            with pytest.raises(OSError, match="Simulated disk error writing manifest"):
                await runner.run(scenario, attempts=1)


@pytest.mark.asyncio
async def test_default_runner_trace_read_failure_and_assertion_fallbacks(tmp_path, monkeypatch):
    runner = DefaultRunner()
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)
    scenario = {"id": "test_scen_assertions"}

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

    runner = DefaultRunner()
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)

    # 1. Trace reading with blank lines, non-dict/non-string metric (12345),
    # and consistency_score metric filtering
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


def test_default_runner_resolve_source_commit(monkeypatch):
    """Test all branches of _resolve_source_commit."""
    # 1. From adapter_meta
    meta = {"source_commit": "sha-from-meta"}
    assert DefaultRunner._resolve_source_commit(meta) == "sha-from-meta"
    val, src, ver = DefaultRunner._resolve_source_commit_attribution(meta)
    assert val == "sha-from-meta"
    assert src == "declared"
    assert ver is False

    # 2. From AGENT_SOURCE_COMMIT env
    monkeypatch.setenv("AGENT_SOURCE_COMMIT", "sha-from-env")
    assert DefaultRunner._resolve_source_commit({}) == "sha-from-env"
    val, src, ver = DefaultRunner._resolve_source_commit_attribution({})
    assert val == "sha-from-env"
    assert src == "declared"
    monkeypatch.delenv("AGENT_SOURCE_COMMIT")

    # 3. From GITHUB_SHA env (with declared source_repository)
    monkeypatch.setenv("GITHUB_SHA", "sha-from-github")
    assert (
        DefaultRunner._resolve_source_commit({"source_repository": "agent-org/agent"})
        == "sha-from-github"
    )
    val, src, ver = DefaultRunner._resolve_source_commit_attribution(
        {"source_repository": "agent-org/agent"}
    )
    assert val == "sha-from-github"
    assert src == "declared"

    # 4. Without source_repository, GITHUB_SHA is ignored (unknown must remain unknown)
    assert DefaultRunner._resolve_source_commit({}) == "unknown"
    val, src, ver = DefaultRunner._resolve_source_commit_attribution({})
    assert val == "unknown"
    assert src == "unknown"
    assert ver is False
    monkeypatch.delenv("GITHUB_SHA")


def test_default_runner_resolve_model_provider():
    """Test all branches of _resolve_model_provider and attribution."""
    # 1. Explicit provider in adapter_meta
    prov_meta = {"provider": "my-provider"}
    assert DefaultRunner._resolve_model_provider("foo", prov_meta) == "my-provider"
    val, src, ver = DefaultRunner._resolve_model_provider_attribution("foo", prov_meta)
    assert val == "my-provider"
    assert src == "declared"
    assert ver is True

    # 1b. model_provider in adapter_meta
    mp_meta = {"model_provider": "alt-provider"}
    assert DefaultRunner._resolve_model_provider("foo", mp_meta) == "alt-provider"
    val, src, ver = DefaultRunner._resolve_model_provider_attribution("foo", mp_meta)
    assert val == "alt-provider"
    assert src == "declared"
    assert ver is True

    # 2. Model keyword inferences (derived, unverified)
    assert DefaultRunner._resolve_model_provider("gpt-4o-mini", {}) == "openai"
    val, src, ver = DefaultRunner._resolve_model_provider_attribution("gpt-4o-mini", {})
    assert val == "openai"
    assert src == "derived"
    assert ver is False

    assert DefaultRunner._resolve_model_provider("o1-preview", {}) == "openai"
    assert DefaultRunner._resolve_model_provider("claude-3-5-sonnet", {}) == "anthropic"
    assert DefaultRunner._resolve_model_provider("gemini-2.5-pro", {}) == "google"
    assert DefaultRunner._resolve_model_provider("llama-3.3-70b", {}) == "local"
    assert DefaultRunner._resolve_model_provider("ollama-qwen", {}) == "local"

    # 3. Framework fallback and unknown (never manufactured 'custom')
    fw_meta = {"framework": "crewai"}
    assert DefaultRunner._resolve_model_provider("unknown-model", fw_meta) == "crewai"
    val, src, ver = DefaultRunner._resolve_model_provider_attribution("unknown-model", fw_meta)
    assert val == "crewai"
    assert src == "declared"

    assert DefaultRunner._resolve_model_provider("unknown-model", {}) == "unknown"
    val, src, ver = DefaultRunner._resolve_model_provider_attribution("unknown-model", {})
    assert val == "unknown"
    assert src == "unknown"
    assert ver is False


def test_default_runner_resolve_tool_versions():
    """Test all branches of _resolve_tool_versions and attribution."""
    scenario = {
        "tools": [
            {"name": "search", "version": "2.1.0"},
            {"version": "1.2.0"},  # fallback to tool_1
            "calculator",
        ]
    }
    adapter_meta = {"tools": {"adapter_tool": "3.0.0"}}
    t_vers, t_prov = DefaultRunner._resolve_tool_versions_attribution(scenario, adapter_meta)
    assert t_vers["search"] == "2.1.0"
    assert t_prov["search"] == {"value": "2.1.0", "source": "declared", "verified": False}
    assert t_vers["tool_1"] == "1.2.0"
    assert t_prov["tool_1"] == {"value": "1.2.0", "source": "declared", "verified": False}
    # Unversioned tool must remain unknown, never defaulted to 1.0.0
    assert t_vers["calculator"] == "unknown"
    assert t_prov["calculator"] == {"value": "unknown", "source": "unknown", "verified": False}
    assert t_vers["adapter_tool"] == "3.0.0"
    assert t_prov["adapter_tool"] == {"value": "3.0.0", "source": "declared", "verified": False}
    assert DefaultRunner._resolve_tool_versions(scenario, adapter_meta) == t_vers


@pytest.mark.asyncio
async def test_default_runner_run_scenario_rich_provenance(tmp_path, monkeypatch):
    """Test run_scenario generates and persists complete rich provenance in ExecutionManifest."""
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", tmp_path)

    runner = DefaultRunner()
    scenario = {
        "id": "provenance_test_scen",
        "version": "1.5.0",
        "prompt": "You are a helpful test assistant.",
        "config": {"temperature": 0.2},
        "policy": [{"rule": "safety_first"}],
        "tools": [{"name": "web_search", "version": "1.0.0"}],
        "workflow": {
            "nodes": [
                {
                    "id": "start",
                    "task_description": "Initial task",
                    "success_criteria": [{"metric": "exact_match", "required": True}],
                }
            ]
        },
    }

    mock_exec_backend = MagicMock()
    mock_exec_backend.run = AsyncMock(
        return_value=MagicMock(
            pass_at_k=1.0,
            all_results=[[{"workflow_verdict": {"status": "COMPLETED"}, "evaluation_valid": True}]],
            metadata={},
        )
    )
    runner.execution_backend = mock_exec_backend

    res = await runner.run(
        scenario,
        attempts=1,
        metadata={"source_commit": "commit_123", "provider": "openai", "model": "gpt-4o"},
    )
    assert res is not None

    manifest_p = tmp_path / "runs" / res.run_id / "execution_manifest.json"
    assert manifest_p.exists()
    import json

    data = json.loads(manifest_p.read_text(encoding="utf-8"))

    agent_cfg = data["agent_config"]
    assert agent_cfg["source_commit"] == "commit_123"
    assert agent_cfg["model_provider"] == "openai"
    assert agent_cfg["configured_model_id"] == "gpt-4o"
    assert agent_cfg["tool_versions"] == {"web_search": "1.0.0"}
    assert agent_cfg["prompt_revision"].startswith("sha3_256:")
    assert agent_cfg["config_revision"].startswith("sha3_256:")
    assert "provenance" in agent_cfg
    prov = agent_cfg["provenance"]
    assert prov["source_commit"]["source"] == "declared"
    assert prov["model_provider"]["source"] == "declared"
    assert prov["prompt_revision"]["source"] == "observed"

    rt_cfg = data["runtime_config"]
    assert rt_cfg["scenario_hash"].startswith("sha3_256:")
    assert rt_cfg["policy_hash"].startswith("sha3_256:")
    assert rt_cfg["oracle_hash"].startswith("sha3_256:")
    assert "runtime_version" in rt_cfg

    env = data["environment"]
    assert "runtime_version" in env
    assert env["environment_fingerprint"].startswith("sha3_256:")


@pytest.mark.asyncio
async def test_certification_run_fails_closed_on_missing_provenance_identity(tmp_path, monkeypatch):
    """[Item 1: P0 Provenance] Certification runs fail closed on missing required identity."""
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", tmp_path)

    runner = DefaultRunner()
    scenario = {
        "id": "cert_provenance_fail_scen",
        "version": "1.0.0",
        "execution_mode": "live",
        "adapter": {"name": "openai"},
        "workflow": {"nodes": [{"id": "n1"}]},
        # Omit model, provider, adapter_version
    }

    emitted = []

    def mock_emit(ev, payload, *args, **kwargs):
        emitted.append((ev, payload))

    monkeypatch.setattr("eval_runner.events.emit", mock_emit)

    res = await runner.run(scenario, attempts=1)
    assert res is not None
    assert res.metadata.get("uncertifiable") is True
    assert res.pass_at_k == 0.0

    ev_names = [e[0] for e in emitted]
    assert CoreEvents.CERTIFICATION_FAILED in ev_names
    assert CoreEvents.RUN_END in ev_names
    run_end_payload = next(p for e, p in emitted if e == CoreEvents.RUN_END)
    assert run_end_payload["status"] == "certification_failed"
    assert run_end_payload["finalization"] is None


@pytest.mark.asyncio
async def test_certification_run_fails_closed_on_missing_or_corrupt_trace(tmp_path, monkeypatch):
    """[Item 2: P0 Evidence] Certification runs fail closed if trace is unreadable or missing."""
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", tmp_path)

    runner = DefaultRunner()
    scenario = {
        "id": "cert_trace_fail_scen",
        "version": "1.0.0",
        "execution_mode": "live",
        "adapter": {"endpoint": "http://localhost:8000", "protocol": "http_rest"},
        "tools": [{"name": "tool1", "version": "1.0.0"}],
        "workflow": {"nodes": [{"id": "n1"}]},
    }
    meta = {
        "model": "gpt-4o",
        "provider": "openai",
        "adapter_version": "1.0.0",
        "source_commit": "abc1234",
    }

    emitted = []

    def mock_emit(ev, payload, *args, **kwargs):
        emitted.append((ev, payload))

    monkeypatch.setattr("eval_runner.events.emit", mock_emit)

    # Mock SessionManager.execute_tasks to not write any trace events
    async def mock_exec(*args, **kwargs):
        return [
            {
                "workflow_verdict": {"status": "COMPLETED"},
                "oracle_results": [{"oracle_id": "or1", "passed": True}],
            }
        ]

    monkeypatch.setattr("eval_runner.session.SessionManager.execute_tasks", mock_exec)

    res = await runner.run(scenario, attempts=1, metadata=meta)
    assert res is not None
    assert res.metadata.get("uncertifiable") is True
    assert res.pass_at_k == 0.0

    ev_names = [e[0] for e in emitted]
    assert CoreEvents.CERTIFICATION_FAILED in ev_names
    run_end = next(p for e, p in emitted if e == CoreEvents.RUN_END)
    assert run_end["status"] == "certification_failed"
    assert run_end["finalization"] is None


@pytest.mark.asyncio
async def test_evaluator_post_processing_exception_fails_closed_to_evaluation_invalid(
    tmp_path, monkeypatch
):
    """[Item 3: P0 Evaluation] Upstream errors fail closed to EVALUATION_INVALID."""
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", tmp_path)

    runner = DefaultRunner()
    scenario = {
        "id": "post_process_fail_scen",
        "version": "1.0.0",
        "workflow": {"nodes": [{"id": "n1"}]},
    }

    # Mock compute_attempt_statistics to raise RuntimeError
    def failing_stats(*args, **kwargs):
        raise RuntimeError("Math domain error during statistics computation")

    monkeypatch.setattr("eval_runner.runner.compute_attempt_statistics", failing_stats)

    emitted = []

    def mock_emit(ev, payload, *args, **kwargs):
        emitted.append((ev, payload))

    monkeypatch.setattr("eval_runner.events.emit", mock_emit)

    async def mock_exec(*args, **kwargs):
        return [{"workflow_verdict": {"status": "COMPLETED"}}]

    monkeypatch.setattr("eval_runner.session.SessionManager.execute_tasks", mock_exec)

    res = await runner.run(scenario, attempts=1)
    assert res is not None
    assert res.metadata.get("outcome") == "EVALUATION_INVALID"
    assert res.metadata.get("evaluation_valid") is False
    assert res.metadata.get("certifiable") is False
    assert res.pass_at_k == 0.0

    ev_names = [e[0] for e in emitted]
    assert CoreEvents.EVALUATION_INVALID in ev_names
    run_end = next(p for e, p in emitted if e == CoreEvents.RUN_END)
    assert run_end["status"] == "evaluation_invalid"
    assert run_end["outcome"] == "EVALUATION_INVALID"
    assert run_end["evaluation_valid"] is False
    assert run_end["finalization"] is None


@pytest.mark.asyncio
async def test_evaluator_signing_auto_provision_prohibited_for_certification(tmp_path, monkeypatch):
    """[Item 4: P0 Trust] Key cannot be dynamically auto-provisioned during certification."""
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", tmp_path)

    runner = DefaultRunner()
    scenario = {
        "id": "cert_key_fail_scen",
        "version": "1.0.0",
        "execution_mode": "live",
        "adapter": {"endpoint": "http://localhost:8000", "protocol": "http_rest"},
        "tools": [{"name": "tool1", "version": "1.0.0"}],
        "workflow": {"nodes": [{"id": "n1"}]},
    }
    meta = {
        "model": "gpt-4o",
        "provider": "openai",
        "adapter_version": "1.0.0",
        "source_commit": "abc1234",
    }

    emitted = []

    def mock_emit(ev, payload, *args, **kwargs):
        emitted.append((ev, payload))

    monkeypatch.setattr("eval_runner.events.emit", mock_emit)

    # Create dummy trace file so trace read succeeds
    async def mock_exec(*args, **kwargs):
        vault = tmp_path / "runs" / runner_run_id / "run.jsonl"
        vault.parent.mkdir(parents=True, exist_ok=True)
        vault.write_text('{"event": "task_completed", "_seq": 1}\n', encoding="utf-8")
        return [{"workflow_verdict": {"status": "COMPLETED"}}]

    runner_run_id = "test_run_cert_key"
    monkeypatch.setattr("eval_runner.session.SessionManager.execute_tasks", mock_exec)

    # Force IdentityService.get_private_key to return None when auto_provision=False
    from eval_runner.identity import IdentityService

    orig_get_key = IdentityService.get_private_key

    def mock_get_key(id_id, auto_provision=True):
        if not auto_provision:
            return None
        return orig_get_key(id_id, auto_provision=auto_provision)

    monkeypatch.setattr(IdentityService, "get_private_key", mock_get_key)

    res = await runner.run(scenario, attempts=1, run_id=runner_run_id, metadata=meta)
    assert res is not None
    assert res.metadata.get("uncertifiable") is True
    assert res.pass_at_k == 0.0

    ev_names = [e[0] for e in emitted]
    assert CoreEvents.CERTIFICATION_FAILED in ev_names
    run_end = next(p for e, p in emitted if e == CoreEvents.RUN_END)
    assert run_end["status"] == "certification_failed"
    assert run_end["finalization"] is None


@pytest.mark.asyncio
async def test_certification_run_fails_closed_on_corrupt_trace_content(tmp_path, monkeypatch):
    """[Item 2: P0 Evidence] Corrupted trace lines fail closed in certification mode."""
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", tmp_path)

    runner = DefaultRunner()
    scenario = {
        "id": "cert_corrupt_trace_scen",
        "version": "1.0.0",
        "execution_mode": "live",
        "adapter": {"endpoint": "http://localhost:8000", "protocol": "http_rest"},
        "tools": [{"name": "tool1", "version": "1.0.0"}],
        "workflow": {"nodes": [{"id": "n1"}]},
    }
    meta = {
        "model": "gpt-4o",
        "provider": "openai",
        "adapter_version": "1.0.0",
        "source_commit": "abc1234",
    }
    emitted = []
    monkeypatch.setattr(
        "eval_runner.events.emit",
        lambda ev, payload, *a, **k: emitted.append((ev, payload)),
    )

    async def mock_exec(*args, **kwargs):
        t_file = tmp_path / "runs" / "test_corrupt_run" / "run.jsonl"
        t_file.parent.mkdir(parents=True, exist_ok=True)
        t_file.write_text("invalid corrupt { json\n", encoding="utf-8")
        return [{"workflow_verdict": {"status": "COMPLETED"}}]

    monkeypatch.setattr("eval_runner.session.SessionManager.execute_tasks", mock_exec)
    res = await runner.run(scenario, attempts=1, run_id="test_corrupt_run", metadata=meta)
    assert res.metadata.get("uncertifiable") is True
    assert CoreEvents.CERTIFICATION_FAILED in [e[0] for e in emitted]


@pytest.mark.asyncio
async def test_certification_fails_closed_on_missing_hashes_or_tools(tmp_path, monkeypatch):
    """Missing scenario_hash, policy_hash, or unresolved tool versions fail closed."""
    runner = DefaultRunner()
    scenario = {
        "id": "cert_missing_hash_scen",
        "version": "1.0.0",
        "execution_mode": "live",
        "adapter": {"endpoint": "http://localhost:8000", "protocol": "http_rest"},
        "tools": [{"name": "tool1"}],  # missing version -> unknown
        "workflow": {"nodes": [{"id": "n1"}]},
    }
    meta = {
        "model": "gpt-4o",
        "provider": "openai",
        "adapter_version": "1.0.0",
        "source_commit": "abc1234",
    }
    # Mock resolved_config.config_hash to 'none'
    monkeypatch.setattr(runner.resolved_config, "config_hash", "none")
    res = await runner.run(scenario, metadata=meta)
    assert res.metadata.get("uncertifiable") is True
