"""
tests/unit/core/test_runner_coverage_booster.py

Comprehensive branch and statement coverage for edge cases in eval_runner/runner.py:
- Scoped configuration adoption lifecycle and error handling
- Provider submission validation and collision boundaries
- Resumption artifact validation, identity matching, and oracle inventory checks
- Signing backend resolution and signing failure manifest handling
- Evaluator verdict lattice branches in attempt success determination
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash
from eval_runner.certification_lock import PerRunCertificationLock
from eval_runner.run_lifecycle import RunLifecycleState
from eval_runner.runner import DefaultRunner


@pytest.fixture(autouse=True)
def clean_certification_locks():
    with PerRunCertificationLock._meta_lock:
        PerRunCertificationLock._active_locks.clear()
        PerRunCertificationLock._depth.clear()
        PerRunCertificationLock._thread_locks.clear()
    yield
    with PerRunCertificationLock._meta_lock:
        PerRunCertificationLock._active_locks.clear()
        PerRunCertificationLock._depth.clear()
        PerRunCertificationLock._thread_locks.clear()


# ---------------------------------------------------------------------------
# Attempt Success Determination Lattice Branches
# ---------------------------------------------------------------------------


def test_is_attempt_successful_node_verdict_reconciliation_fail():
    runner = DefaultRunner()
    res = [
        {"workflow_verdict": {"status": "workflow_completed"}},
        {
            "status": "COMPLETED",
            "node_verdict": {
                "policy": "allow",
                "parity": "pass",
                "reconciliation": "fail",
                "overall": "success",
            },
        },
    ]
    assert runner._is_attempt_successful(res) is False


def test_is_attempt_successful_node_verdict_reconciliation_invalid():
    runner = DefaultRunner()
    res = [
        {"workflow_verdict": {"status": "workflow_completed"}},
        {
            "status": "COMPLETED",
            "node_verdict": {
                "policy": "allow",
                "parity": "pass",
                "reconciliation": "invalid",
                "overall": "success",
            },
        },
    ]
    assert runner._is_attempt_successful(res) is False


def test_is_attempt_successful_state_reconciliation_mismatch():
    runner = DefaultRunner()
    res = [
        {"workflow_verdict": {"status": "workflow_completed"}},
        {
            "status": "COMPLETED",
            "reconciliation": {
                "expected_change_checks": True,
                "reconciled": False,
            },
        },
    ]
    assert runner._is_attempt_successful(res) is False


def test_is_attempt_successful_metrics_edge_branches():
    runner = DefaultRunner()

    # Non-dict item in metrics is skipped safely
    res_non_dict = [
        {"workflow_verdict": {"status": "workflow_completed"}},
        {
            "status": "COMPLETED",
            "metrics": ["invalid_metric_string", {"outcome": "PASS", "success": True}],
        },
    ]
    assert runner._is_attempt_successful(res_non_dict) is True

    # Evaluation invalid status
    res_eval_invalid = [
        {"workflow_verdict": {"status": "workflow_completed"}},
        {
            "status": "COMPLETED",
            "metrics": [{"status": "EVALUATION_INVALID", "requiredness": "REQUIRED"}],
        },
    ]
    assert runner._is_attempt_successful(res_eval_invalid) is False

    # Metric marked as invalid
    res_invalid_flag = [
        {"workflow_verdict": {"status": "workflow_completed"}},
        {
            "status": "COMPLETED",
            "metrics": [{"invalid": True, "requiredness": "REQUIRED"}],
        },
    ]
    assert runner._is_attempt_successful(res_invalid_flag) is False

    # Outcome is PASS but explicit success flag is False
    res_pass_with_success_false = [
        {"workflow_verdict": {"status": "workflow_completed"}},
        {
            "status": "COMPLETED",
            "metrics": [{"outcome": "PASS", "success": False}],
        },
    ]
    assert runner._is_attempt_successful(res_pass_with_success_false) is False


def test_is_attempt_successful_state_hygiene_edge_branches():
    runner = DefaultRunner()

    # Non-dict item in state hygiene is skipped safely
    res_non_dict = [
        {"workflow_verdict": {"status": "workflow_completed"}},
        {
            "status": "COMPLETED",
            "state_hygiene": ["skipped_raw_value", {"outcome": "PASS", "success": True}],
        },
    ]
    assert runner._is_attempt_successful(res_non_dict) is True

    # Hygiene outcome is PASS but explicit success flag is False
    res_pass_with_success_false = [
        {"workflow_verdict": {"status": "workflow_completed"}},
        {
            "status": "COMPLETED",
            "state_hygiene": [{"outcome": "PASS", "success": False}],
        },
    ]
    assert runner._is_attempt_successful(res_pass_with_success_false) is False


def test_is_attempt_successful_state_parity_edge_branches():
    runner = DefaultRunner()

    # Non-dict item in state parity is skipped safely
    res_non_dict = [
        {"workflow_verdict": {"status": "workflow_completed"}},
        {
            "status": "COMPLETED",
            "state_parity": [None, {"outcome": "PASS", "success": True}],
        },
    ]
    assert runner._is_attempt_successful(res_non_dict) is True

    # Parity outcome is PASS but explicit success flag is False
    res_pass_with_success_false = [
        {"workflow_verdict": {"status": "workflow_completed"}},
        {
            "status": "COMPLETED",
            "state_parity": [{"outcome": "PASS", "success": False}],
        },
    ]
    assert runner._is_attempt_successful(res_pass_with_success_false) is False


# ---------------------------------------------------------------------------
# Resumption Preflight and Validation Gates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resumption_missing_artifacts_in_provider_manifest(tmp_path):
    runner = DefaultRunner()
    run_id = "run-resumption-missing-artifacts"
    scenario = {"id": "scen-test", "version": "1.0.0"}

    mock_run_store = MagicMock()
    mock_run_store.get_run.return_value = {"run_id": run_id, "status": "OPEN"}
    # Provider manifest missing execution_manifest and scenario_data
    mock_run_store.get_manifest.return_value = {"metadata": {}}

    runner.run_store = mock_run_store
    with patch(
        "eval_runner.run_lifecycle.get_run_lifecycle_state",
        return_value=RunLifecycleState.OPEN,
    ):
        with pytest.raises(RuntimeError, match="ResumptionArtifactMissing"):
            await runner.run(scenario, run_id=run_id, resumption_token="res_tok")


@pytest.mark.asyncio
async def test_resumption_invalid_execution_manifest_structure(tmp_path):
    runner = DefaultRunner()
    run_id = "run-resumption-invalid-manifest"
    scenario = {"id": "scen-test", "version": "1.0.0"}

    mock_run_store = MagicMock()
    mock_run_store.get_run.return_value = {"run_id": run_id, "status": "OPEN"}
    # Malformed execution_manifest dictionary that fails schema conversion
    mock_run_store.get_manifest.return_value = {
        "execution_manifest": {"invalid_manifest_key": True},
        "scenario_data": scenario,
    }

    runner.run_store = mock_run_store
    with patch(
        "eval_runner.run_lifecycle.get_run_lifecycle_state",
        return_value=RunLifecycleState.OPEN,
    ):
        with pytest.raises(RuntimeError, match="ResumptionManifestInvalid"):
            await runner.run(scenario, run_id=run_id, resumption_token="res_tok")


@pytest.mark.asyncio
async def test_resumption_identity_mismatch(tmp_path):
    runner = DefaultRunner()
    run_id = "run-resumption-identity-mismatch"
    authoritative_scenario = {"id": "scen-authoritative", "version": "1.0.0"}
    scen_hash = compute_scenario_hash(authoritative_scenario)

    manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id="scen-authoritative",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
    )

    tampered_id_scenario = {"id": "scen-mismatched", "version": "1.0.0"}
    with patch("agentv_runtime.manifest.compute_scenario_hash", return_value=scen_hash):
        mock_run_store = MagicMock()
        mock_run_store.get_run.return_value = {"run_id": run_id, "status": "OPEN"}
        mock_run_store.get_manifest.return_value = {
            "execution_manifest": manifest.to_dict(),
            "scenario_data": tampered_id_scenario,
        }

        runner.run_store = mock_run_store
        with patch(
            "eval_runner.run_lifecycle.get_run_lifecycle_state",
            return_value=RunLifecycleState.OPEN,
        ):
            with pytest.raises(RuntimeError, match="ResumptionScenarioIdentityMismatch"):
                await runner.run(authoritative_scenario, run_id=run_id, resumption_token="res_tok")


@pytest.mark.asyncio
async def test_resumption_oracle_inventory_mismatch(tmp_path):
    runner = DefaultRunner()
    run_id = "run-resumption-oracle-mismatch"
    scenario = {"id": "scen-test", "version": "1.0.0"}
    scen_hash = compute_scenario_hash(scenario)

    manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id="scen-test",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        metadata={"required_oracle_ids": ["oracle_a", "oracle_b"]},
    )

    mock_run_store = MagicMock()
    mock_run_store.get_run.return_value = {"run_id": run_id, "status": "OPEN"}
    mock_run_store.get_manifest.return_value = {
        "execution_manifest": manifest.to_dict(),
        "scenario_data": scenario,
    }

    runner.run_store = mock_run_store
    with (
        patch(
            "eval_runner.run_lifecycle.get_run_lifecycle_state",
            return_value=RunLifecycleState.OPEN,
        ),
        patch("eval_runner.runner.compile_required_oracle_ids", return_value=["oracle_a"]),
    ):
        with pytest.raises(RuntimeError, match="ResumptionOracleInventoryMismatch"):
            await runner.run(scenario, run_id=run_id, resumption_token="res_tok")


# ---------------------------------------------------------------------------
# Scoped Configuration Adoption and Provider Submission Fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scoped_configuration_adoption_success(tmp_path):
    runner = DefaultRunner()
    run_id = "run-scoped-config-success"
    scenario = {"id": "scen-scoped", "version": "1.0.0"}

    scoped_context = {
        "org_id": "org_1",
        "tenant_id": "tenant_1",
        "workspace_id": "ws_1",
        "active_environment": "production",
    }

    mock_target_rev = MagicMock(revision_id="rev_100")
    mock_adapter = MagicMock()
    mock_adapter.get_pending_or_active_revision.return_value = mock_target_rev
    mock_adapter.report_worker_observation.return_value = MagicMock(revision_id="rev_100")

    mock_rev_service = MagicMock()
    mock_rev_service.get_deployment_adapter.return_value = mock_adapter

    mock_consumer = MagicMock()
    mock_consumer.consume_and_reload.return_value = {"status": "reloaded"}

    mock_run_store = MagicMock()
    mock_run_store.get_run.return_value = None
    runner.run_store = mock_run_store
    runner.revision_service = mock_rev_service

    with (
        patch("agentv_runtime.config.RuntimeWorkerConfigConsumer", return_value=mock_consumer),
        patch("eval_runner.session.SessionManager") as mock_session_cls,
    ):
        mock_sess = MagicMock()
        mock_sess.metadata = {}
        mock_sess.execute_tasks = AsyncMock(
            return_value=[
                {"workflow_verdict": {"status": "workflow_completed"}, "status": "COMPLETED"}
            ]
        )
        mock_session_cls.return_value = mock_sess

        res = await runner.run(
            scenario,
            run_id=run_id,
            metadata={"runtime_context": scoped_context},
            attempts=1,
        )
        assert res.pass_at_k == 1.0
        mock_adapter.report_worker_observation.assert_called_once()


@pytest.mark.asyncio
async def test_scoped_configuration_adoption_failure(tmp_path):
    runner = DefaultRunner()
    run_id = "run-scoped-config-fail"
    scenario = {"id": "scen-scoped", "version": "1.0.0"}

    scoped_context = {
        "org_id": "org_1",
        "tenant_id": "tenant_1",
        "workspace_id": "ws_1",
        "active_environment": "production",
    }

    mock_rev_service = MagicMock()
    mock_rev_service.get_deployment_adapter.side_effect = RuntimeError("Adapter network partition")
    runner.revision_service = mock_rev_service

    with pytest.raises(RuntimeError, match="ScopedConfigurationAdoptionFailed"):
        await runner.run(
            scenario,
            run_id=run_id,
            metadata={"runtime_context": scoped_context},
            attempts=1,
        )


@pytest.mark.asyncio
async def test_runtime_context_loaded_from_provider_submission(tmp_path):
    runner = DefaultRunner()
    run_id = "run-submission-context-fallback"
    scenario = {"id": "scen-idx", "version": "1.0.0"}

    submission_context = {
        "org_id": "org_idx",
        "tenant_id": "tenant_idx",
        "workspace_id": "ws_idx",
        "active_environment": "staging",
    }

    mock_run_store = MagicMock()
    mock_run_store.get_run.return_value = None
    runner.run_store = mock_run_store

    with (
        patch.object(
            mock_run_store,
            "get_submission",
            return_value={"context": submission_context},
        ),
        patch("eval_runner.services.config_revision.ConfigurationRevisionService") as mock_rev_cls,
        patch("eval_runner.session.SessionManager") as mock_session_cls,
    ):
        mock_adapter = MagicMock()
        mock_adapter.get_pending_or_active_revision.return_value = None
        mock_rev_cls.return_value.get_deployment_adapter.return_value = mock_adapter

        mock_sess = MagicMock()
        mock_sess.metadata = {}
        mock_sess.execute_tasks = AsyncMock(
            return_value=[
                {"workflow_verdict": {"status": "workflow_completed"}, "status": "COMPLETED"}
            ]
        )
        mock_session_cls.return_value = mock_sess

        res = await runner.run(
            scenario,
            run_id=run_id,
            metadata=None,
            attempts=1,
        )
        assert res.pass_at_k == 1.0
        mock_adapter.get_pending_or_active_revision.assert_called_once()


# ---------------------------------------------------------------------------
# Provider Submission Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_submission_not_open_collision():
    runner = DefaultRunner()
    run_id = "run-prov-sub-closed"
    scenario = {"id": "scen-test", "version": "1.0.0"}

    mock_run_store = MagicMock()
    mock_run_store.get_run.return_value = {"run_id": run_id, "status": "FINALIZING"}
    runner.run_store = mock_run_store

    with patch(
        "eval_runner.run_lifecycle.get_run_lifecycle_state",
        return_value=RunLifecycleState.FINALIZING,
    ):
        with pytest.raises(RuntimeError, match="RunIdCollision.*is not an empty OPEN record"):
            await runner.run(
                scenario,
                run_id=run_id,
                provider_submission=True,
            )


@pytest.mark.asyncio
async def test_provider_submission_context_mismatch_collision():
    runner = DefaultRunner()
    run_id = "run-prov-sub-ctx-mismatch"
    scenario = {"id": "scen-test", "version": "1.0.0"}

    mock_run_store = MagicMock()
    mock_run_store.get_run.return_value = {
        "run_id": run_id,
        "status": "OPEN",
        "context": {"tenant": "tenant_alpha"},
    }
    mock_run_store.get_events.return_value = []
    mock_run_store.get_manifest.return_value = {}
    runner.run_store = mock_run_store

    with patch(
        "eval_runner.run_lifecycle.get_run_lifecycle_state",
        return_value=RunLifecycleState.OPEN,
    ):
        with pytest.raises(RuntimeError, match="RunIdCollision.*is not an empty OPEN record"):
            await runner.run(
                scenario,
                run_id=run_id,
                provider_submission=True,
                metadata={"runtime_context": {"tenant": "tenant_beta"}},
            )


@pytest.mark.asyncio
async def test_provider_submission_valid_open_record():
    runner = DefaultRunner()
    run_id = "run-prov-sub-valid"
    scenario = {"id": "scen-test", "version": "1.0.0"}

    mock_run_store = MagicMock()
    mock_run_store.get_run.return_value = {
        "run_id": run_id,
        "status": "OPEN",
        "context": {"tenant": "tenant_alpha"},
    }
    mock_run_store.get_events.return_value = []
    mock_run_store.get_manifest.return_value = {}
    runner.run_store = mock_run_store

    with (
        patch(
            "eval_runner.run_lifecycle.get_run_lifecycle_state",
            return_value=RunLifecycleState.OPEN,
        ),
        patch("eval_runner.session.SessionManager") as mock_session_cls,
    ):
        mock_sess = MagicMock()
        mock_sess.metadata = {}
        mock_sess.execute_tasks = AsyncMock(
            return_value=[
                {"workflow_verdict": {"status": "workflow_completed"}, "status": "COMPLETED"}
            ]
        )
        mock_session_cls.return_value = mock_sess

        res = await runner.run(
            scenario,
            run_id=run_id,
            provider_submission=True,
            metadata={"runtime_context": {"tenant": "tenant_alpha"}},
            attempts=1,
        )
        assert res.pass_at_k == 1.0


# ---------------------------------------------------------------------------
# Signing Backend and Signing Failure Branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signing_backend_can_sign():
    runner = DefaultRunner()
    run_id = "run-signing-backend-can-sign"
    scenario = {"id": "scen-test", "version": "1.0.0"}

    mock_signing = MagicMock()
    mock_signing.can_sign.return_value = True
    mock_signing.sign.return_value = "a" * 128
    mock_signing.sign_payload.return_value = "a" * 128
    runner.signing_backend = mock_signing

    mock_run_store = MagicMock()
    mock_run_store.get_run.return_value = None
    runner.run_store = mock_run_store

    with (
        patch("eval_runner.session.SessionManager") as mock_session_cls,
        patch("eval_runner.services.certification.execute_industrial_certification") as mock_cert,
    ):
        mock_sess = MagicMock()
        mock_sess.metadata = {}
        mock_sess.execute_tasks = AsyncMock(
            return_value=[
                {"workflow_verdict": {"status": "workflow_completed"}, "status": "COMPLETED"}
            ]
        )
        mock_session_cls.return_value = mock_sess

        mock_cert.return_value = {
            "status": "certified",
            "signature": "sig123",
            "manifest": {},
        }

        res = await runner.run(
            scenario,
            run_id=run_id,
            attempts=1,
        )
        assert res.pass_at_k == 1.0


@pytest.mark.asyncio
async def test_signing_error_persists_scoped_failed_manifest():
    runner = DefaultRunner()
    run_id = "run-signing-error-scoped"
    scenario = {"id": "scen-test", "version": "1.0.0"}

    scoped_context = {
        "org_id": "org_scope",
        "tenant_id": "tenant_scope",
        "workspace_id": "ws_scope",
        "active_environment": "production",
    }

    mock_target_rev = MagicMock(revision_id="rev_100")
    mock_adapter = MagicMock()
    mock_adapter.get_pending_or_active_revision.return_value = mock_target_rev
    mock_adapter.report_worker_observation.return_value = MagicMock(revision_id="rev_100")

    mock_rev_service = MagicMock()
    mock_rev_service.get_deployment_adapter.return_value = mock_adapter
    runner.revision_service = mock_rev_service

    mock_consumer = MagicMock()
    mock_consumer.consume_and_reload.return_value = {"status": "reloaded"}

    mock_run_store = MagicMock()
    mock_run_store.get_run.return_value = None
    mock_run_store.save_run_manifest.side_effect = [
        None,
        RuntimeError("Disk full writing failed manifest"),
    ]
    runner.run_store = mock_run_store

    with (
        patch("agentv_runtime.config.RuntimeWorkerConfigConsumer", return_value=mock_consumer),
        patch.object(
            mock_run_store,
            "get_submission",
            return_value={"context": scoped_context},
        ),
        patch("eval_runner.session.SessionManager") as mock_session_cls,
        patch(
            "eval_runner.identity.IdentityService.get_private_key",
            side_effect=ValueError("Key unavailable"),
        ),
    ):
        mock_sess = MagicMock()
        mock_sess.metadata = {}
        mock_sess.execute_tasks = AsyncMock(
            return_value=[
                {"workflow_verdict": {"status": "workflow_completed"}, "status": "COMPLETED"}
            ]
        )
        mock_session_cls.return_value = mock_sess

        res = await runner.run(
            scenario,
            run_id=run_id,
            attempts=1,
            metadata={"execution_mode": "certification"},
        )
        assert res.pass_at_k == 0.0
        assert "Evaluator signing failed" in res.metadata.get("error", "")
        assert mock_run_store.save_run_manifest.call_count == 2


@pytest.mark.asyncio
async def test_signing_error_with_declared_runtime_context():
    runner = DefaultRunner()
    run_id = "run-signing-error-declared-ctx"
    scenario = {"id": "scen-test", "version": "1.0.0"}

    scoped_context = {
        "org_id": "org_decl",
        "tenant_id": "tenant_decl",
        "workspace_id": "ws_decl",
        "active_environment": "production",
    }

    mock_run_store = MagicMock()
    mock_run_store.get_run.return_value = None
    runner.run_store = mock_run_store

    with (
        patch("eval_runner.session.SessionManager") as mock_session_cls,
        patch(
            "eval_runner.identity.IdentityService.get_private_key",
            side_effect=ValueError("Key unavailable"),
        ),
    ):
        mock_sess = MagicMock()
        mock_sess.metadata = {}
        mock_sess.execute_tasks = AsyncMock(
            return_value=[
                {"workflow_verdict": {"status": "workflow_completed"}, "status": "COMPLETED"}
            ]
        )
        mock_session_cls.return_value = mock_sess

        res = await runner.run(
            scenario,
            run_id=run_id,
            attempts=1,
            metadata={"runtime_context": scoped_context, "execution_mode": "certification"},
        )
        assert res.pass_at_k == 0.0
        assert "Evaluator signing failed" in res.metadata.get("error", "")


@pytest.mark.asyncio
async def test_resumption_no_immutable_execution_record_in_provider():
    runner = DefaultRunner()
    run_id = "run-resumption-no-record"
    scenario = {"id": "scen-test", "version": "1.0.0"}
    mock_run_store = MagicMock()
    mock_run_store.get_run.return_value = None
    runner.run_store = mock_run_store
    with pytest.raises(
        RuntimeError,
        match="ResumptionArtifactMissing: provider has no immutable execution record for resume",
    ):
        await runner.run(scenario, run_id=run_id, resumption_token="res_tok")


@pytest.mark.asyncio
async def test_resumption_snapshot_invalid():
    runner = DefaultRunner()
    run_id = "run-resumption-snap-invalid"
    scenario = {"id": "scen-test", "version": "1.0.0"}
    mock_run_store = MagicMock()
    mock_run_store.get_run.return_value = {"run_id": run_id, "status": "OPEN"}
    manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id="scen-test",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:abc",
    )
    mock_run_store.get_manifest.return_value = {
        "execution_manifest": manifest.to_dict(),
        "scenario_data": scenario,
    }
    runner.run_store = mock_run_store
    with (
        patch(
            "eval_runner.run_lifecycle.get_run_lifecycle_state",
            return_value=RunLifecycleState.OPEN,
        ),
        patch(
            "agentv_runtime.manifest.compute_scenario_hash",
            side_effect=["sha3_256:abc", "sha3_256:abc", ValueError("Invalid scenario format")],
        ),
    ):
        with pytest.raises(RuntimeError, match="ResumptionSnapshotInvalid"):
            await runner.run(scenario, run_id=run_id, resumption_token="res_tok")


def test_is_attempt_successful_empty_outcome_with_success_true():
    runner = DefaultRunner()
    # Metrics empty outcome
    res_metric = [
        {"workflow_verdict": {"status": "workflow_completed"}},
        {"status": "COMPLETED", "metrics": [{"outcome": "", "success": True}]},
    ]
    assert runner._is_attempt_successful(res_metric) is True

    # State hygiene empty outcome
    res_hygiene = [
        {"workflow_verdict": {"status": "workflow_completed"}},
        {"status": "COMPLETED", "state_hygiene": [{"outcome": "", "success": True}]},
    ]
    assert runner._is_attempt_successful(res_hygiene) is True

    # State parity empty outcome
    res_parity = [
        {"workflow_verdict": {"status": "workflow_completed"}},
        {"status": "COMPLETED", "state_parity": [{"outcome": "", "success": True}]},
    ]
    assert runner._is_attempt_successful(res_parity) is True


@pytest.mark.asyncio
async def test_runner_run_with_falsy_run_store():
    falsy_store = MagicMock()
    falsy_store.__bool__.return_value = False
    falsy_store.get_run.return_value = None
    runner = DefaultRunner(run_store=falsy_store)
    scenario = {"id": "scen-falsy-store", "version": "1.0.0"}

    with patch("eval_runner.session.SessionManager") as mock_session_cls:
        mock_sess = MagicMock()
        mock_sess.metadata = {}
        mock_sess.execute_tasks = AsyncMock(
            return_value=[
                {"workflow_verdict": {"status": "workflow_completed"}, "status": "COMPLETED"}
            ]
        )
        mock_session_cls.return_value = mock_sess

        res = await runner.run(scenario, run_id="run-falsy-store", attempts=1)
        assert res.pass_at_k == 1.0
