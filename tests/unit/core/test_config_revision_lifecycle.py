"""
tests.unit.core.test_config_revision_lifecycle
Comprehensive test suite for Runtime Configuration Revision Consumption, Observation,
and Mandate Authority Clarification.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agentv_runtime.config import (
    ConfigDiagnosticError,
    ConfigResolutionError,
    ConfigResolver,
    ConfigurationRevisionRecord,
    ConfigurationRevisionState,
    InstanceObservation,
    RuntimeWorkerConfigConsumer,
)
from eval_runner.services.config_revision import (
    ConfigurationRevisionService,
    RuntimeDeploymentProviderAdapter,
    ScopeAccessDeniedError,
    StaleRevisionError,
    bind_revision_to_evidence,
    derive_verified_scope,
)


@pytest.fixture
def sample_scope() -> dict[str, str]:
    return {
        "org_id": "org_healthcare_corp",
        "tenant_id": "tenant_radiology",
        "workspace_id": "ws_clinical_eval",
        "active_environment": "production",
    }


@pytest.fixture
def foreign_scope() -> dict[str, str]:
    return {
        "org_id": "org_finance_inc",
        "tenant_id": "tenant_trading",
        "workspace_id": "ws_risk_eval",
        "active_environment": "staging",
    }


@pytest.fixture
def revision_service(tmp_path: Path) -> ConfigurationRevisionService:
    return ConfigurationRevisionService(storage_root=tmp_path / "aes_revisions")


# ---------------------------------------------------------------------------
# Section 1: Mandate Authority Clarification & Participation
# ---------------------------------------------------------------------------


def test_file_merged_mandates_participate_in_effective_result(tmp_path: Path):
    """File-declared mandates must participate in the effective mandate result with provenance."""
    conf_dir = tmp_path / "aes_conf"
    conf_dir.mkdir(parents=True)
    mandate_file = conf_dir / "governance_mandates.yaml"
    mandate_file.write_text(
        """
mandates:
  core:
    audit_level: 3
    timeout_seconds: 300
  policies:
    retention_days: 90
""",
        encoding="utf-8",
    )

    res = ConfigResolver.resolve_detailed(config_dir=conf_dir, fail_closed=False)
    assert res.is_valid

    # Verify file mandates are recorded and enforced in effective snapshot
    assert res.effective_snapshot is not None
    assert res.effective_snapshot.audit_level == 3
    assert res.effective_snapshot.timeout_seconds == 300
    assert res.effective_snapshot.mandates["core"]["audit_level"] == 3

    # Check diagnostic entry provenance
    diag = res.entries["core.audit_level"]
    applied_contrib = [c for c in diag.contributors if c.applied]
    assert len(applied_contrib) == 1
    assert applied_contrib[0].source_type == "file_mandate"
    assert "governance_mandates.yaml:mandates.core.audit_level" in applied_contrib[0].source_name


def test_file_merged_mandate_conflict_with_runtime_mandate_fails_closed(tmp_path: Path):
    """When a file mandate conflicts with runtime mandate, mandate_conflict is recorded."""
    conf_dir = tmp_path / "aes_conf"
    conf_dir.mkdir(parents=True)
    mandate_file = conf_dir / "base_mandates.json"
    mandate_file.write_text(
        json.dumps({"mandates": {"core": {"audit_level": 3}}}),
        encoding="utf-8",
    )

    # Explicit runtime mandate specifies a conflicting audit_level
    res = ConfigResolver.resolve_detailed(
        config_dir=conf_dir,
        mandates={"core": {"audit_level": 1}},
        fail_closed=False,
    )

    assert not res.is_valid
    conflicts = [e for e in res.errors if e.error_type == "mandate_conflict"]
    assert len(conflicts) >= 1
    assert conflicts[0].canonical_key == "core.audit_level"
    assert "strictly enforces" in conflicts[0].message

    # Fail closed enforcement in production
    with pytest.raises(ConfigResolutionError) as exc_info:
        ConfigResolver.resolve_detailed(
            config_dir=conf_dir,
            mandates={"core": {"audit_level": 1}},
            fail_closed=True,
        )
    assert "failed closed" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Section 2: Generic Server-Side Scope Verification & Acceptance
# ---------------------------------------------------------------------------


def test_derive_verified_scope_strictness(sample_scope: dict[str, str]):
    """Server-side scope derivation validates all four required scope coordinates."""
    valid = derive_verified_scope(sample_scope)
    assert valid["org_id"] == "org_healthcare_corp"
    assert valid["active_environment"] == "production"

    # Missing coordinate fails closed
    with pytest.raises(ValueError, match="Missing required server-side scope parameters"):
        derive_verified_scope({"org_id": "test", "tenant_id": "test"})

    # Empty string coordinate fails closed
    with pytest.raises(ValueError, match="Missing required server-side scope parameters"):
        derive_verified_scope({**sample_scope, "active_environment": "   "})


def test_accept_revision_enters_provider_accepted(
    revision_service: ConfigurationRevisionService,
    sample_scope: dict[str, str],
):
    """Provider acceptance creates an immutable desired revision with PROVIDER_ACCEPTED state."""
    rec = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint="sha3_256:abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234",
        target_instances=["worker-node-01", "worker-node-02"],
    )

    assert rec.revision_id.startswith("rev_")
    assert rec.status == ConfigurationRevisionState.PROVIDER_ACCEPTED.value
    assert rec.provider_acknowledged is False
    assert rec.target_scope == sample_scope
    assert rec.target_instances == ["worker-node-01", "worker-node-02"]
    assert rec.instances == {}

    # Invalid empty desired fingerprint is rejected
    with pytest.raises(ValueError, match="desired_fingerprint must be a non-empty string"):
        revision_service.accept_revision(context=sample_scope, desired_fingerprint="   ")


def test_concurrency_stale_revision_rejected(
    revision_service: ConfigurationRevisionService,
    sample_scope: dict[str, str],
):
    """Specifying an outdated expected_base_revision_id raises StaleRevisionError."""
    # First revision accepted
    rev1 = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint="sha3_256:fingerprint_v1",
        target_instances=["node-1"],
    )
    # Complete rollout for rev1 to make it active
    revision_service.acknowledge_deployment(context=sample_scope, revision_id=rev1.revision_id)
    revision_service.record_instance_observation(
        context=sample_scope,
        revision_id=rev1.revision_id,
        instance_id="node-1",
        consumed_fingerprint="sha3_256:fingerprint_v1",
        reload_status="reloaded",
    )

    # Attempting to base a new revision on a bogus base ID fails closed
    with pytest.raises(StaleRevisionError, match="does not match current active revision"):
        revision_service.accept_revision(
            context=sample_scope,
            desired_fingerprint="sha3_256:fingerprint_v2",
            expected_base_revision_id="rev_outdated_unknown",
        )


# ---------------------------------------------------------------------------
# Section 3: Deployment Acknowledgement & Multi-Instance Observation
# ---------------------------------------------------------------------------


def test_deployment_acknowledgement_transition(
    revision_service: ConfigurationRevisionService,
    sample_scope: dict[str, str],
):
    """Acknowledging deployment transitions status to DEPLOYED."""
    rev = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint="sha3_256:target_hash",
        target_instances=["node-a"],
    )
    assert rev.status == ConfigurationRevisionState.PROVIDER_ACCEPTED.value

    acked = revision_service.acknowledge_deployment(
        context=sample_scope,
        revision_id=rev.revision_id,
        provider_acknowledged=True,
    )
    assert acked.provider_acknowledged is True
    assert acked.status == ConfigurationRevisionState.DEPLOYED.value


def test_multi_instance_rollout_reaches_observed_agreement(
    revision_service: ConfigurationRevisionService,
    sample_scope: dict[str, str],
):
    """When all target instances report verified reload, state transitions to OBSERVED."""
    desired = "sha3_256:agreed_fingerprint"
    rev = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint=desired,
        target_instances=["inst-1", "inst-2"],
    )
    revision_service.acknowledge_deployment(context=sample_scope, revision_id=rev.revision_id)

    # Instance 1 reloads: Partial rollout
    after_inst1 = revision_service.record_instance_observation(
        context=sample_scope,
        revision_id=rev.revision_id,
        instance_id="inst-1",
        consumed_fingerprint=desired,
        reload_status="reloaded",
    )
    assert after_inst1.status == ConfigurationRevisionState.PARTIALLY_APPLIED.value
    assert "inst-1" in after_inst1.instances

    # Active pointer is not yet updated before full observation
    active_before = revision_service.get_active_revision(sample_scope)
    assert active_before is None

    # Instance 2 reloads with restart: Full agreement
    after_inst2 = revision_service.record_instance_observation(
        context=sample_scope,
        revision_id=rev.revision_id,
        instance_id="inst-2",
        consumed_fingerprint=desired,
        reload_status="restarted",
    )
    assert after_inst2.status == ConfigurationRevisionState.OBSERVED.value
    assert len(after_inst2.instances) == 2

    # Active pointer is now updated to the observed revision
    active_after = revision_service.get_active_revision(sample_scope)
    assert active_after is not None
    assert active_after.revision_id == rev.revision_id
    assert active_after.desired_fingerprint == desired


def test_multi_instance_partial_and_total_failure(
    revision_service: ConfigurationRevisionService,
    sample_scope: dict[str, str],
):
    """Instance reload failures correctly produce PARTIALLY_APPLIED or FAILED states."""
    desired = "sha3_256:target_fingerprint"
    rev = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint=desired,
        target_instances=["inst-success", "inst-fail"],
    )
    revision_service.acknowledge_deployment(context=sample_scope, revision_id=rev.revision_id)

    # Success on first instance
    revision_service.record_instance_observation(
        context=sample_scope,
        revision_id=rev.revision_id,
        instance_id="inst-success",
        consumed_fingerprint=desired,
        reload_status="reloaded",
    )

    # Failure on second instance with structured diagnostic
    diag = ConfigDiagnosticError(
        source="env:AUDIT_LEVEL",
        error_type="invalid_environment_override",
        message="Failed to parse AUDIT_LEVEL",
    )
    after_fail = revision_service.record_instance_observation(
        context=sample_scope,
        revision_id=rev.revision_id,
        instance_id="inst-fail",
        consumed_fingerprint="sha3_256:stale_local_fingerprint",
        reload_status="failed",
        failure_reason="Invalid environment override encountered during worker startup",
        diagnostics=[diag],
    )

    # Mixed success and failure yields PARTIALLY_APPLIED
    assert after_fail.status == ConfigurationRevisionState.PARTIALLY_APPLIED.value
    assert after_fail.instances["inst-fail"].reload_status == "failed"
    assert after_fail.instances["inst-fail"].failure_reason is not None

    # Total failure scenario: revision where all instances fail
    rev_all_fail = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint=desired,
        target_instances=["solo-worker"],
    )
    after_total_fail = revision_service.record_instance_observation(
        context=sample_scope,
        revision_id=rev_all_fail.revision_id,
        instance_id="solo-worker",
        consumed_fingerprint="",
        reload_status="failed",
        failure_reason="Worker crashed on configuration load",
    )
    assert after_total_fail.status == ConfigurationRevisionState.FAILED.value


# ---------------------------------------------------------------------------
# Section 4: Rollback as a New Auditable Revision
# ---------------------------------------------------------------------------


def test_rollback_creates_new_auditable_revision(
    revision_service: ConfigurationRevisionService,
    sample_scope: dict[str, str],
):
    """Rollback creates a new revision referencing target fingerprint, preserving history."""
    # 1. First revision accepted and observed
    rev1 = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint="sha3_256:healthy_config_v1",
        target_instances=["node-1"],
    )
    revision_service.record_instance_observation(
        context=sample_scope,
        revision_id=rev1.revision_id,
        instance_id="node-1",
        consumed_fingerprint="sha3_256:healthy_config_v1",
        reload_status="reloaded",
    )

    # 2. Second revision accepted and observed
    rev2 = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint="sha3_256:problematic_config_v2",
        target_instances=["node-1"],
    )
    revision_service.record_instance_observation(
        context=sample_scope,
        revision_id=rev2.revision_id,
        instance_id="node-1",
        consumed_fingerprint="sha3_256:problematic_config_v2",
        reload_status="reloaded",
    )

    # 3. Rollback to rev1
    rb_rec = revision_service.rollback(
        context=sample_scope,
        target_revision_id=rev1.revision_id,
    )

    # Rollback must be a new distinct revision ID
    assert rb_rec.revision_id != rev1.revision_id
    assert rb_rec.revision_id != rev2.revision_id
    assert rb_rec.is_rollback is True
    assert rb_rec.desired_fingerprint == "sha3_256:healthy_config_v1"
    assert rb_rec.previous_revision_id == rev2.revision_id
    assert rb_rec.status == ConfigurationRevisionState.PROVIDER_ACCEPTED.value
    assert rb_rec.metadata["rollback_source_revision_id"] == rev1.revision_id

    # Historical records remain completely intact
    rev1_reloaded = revision_service.get_revision(sample_scope, rev1.revision_id)
    assert rev1_reloaded is not None
    assert rev1_reloaded.is_rollback is False

    rev2_reloaded = revision_service.get_revision(sample_scope, rev2.revision_id)
    assert rev2_reloaded is not None

    # Listing revisions shows all entries in append-only sequence
    all_recs = revision_service.list_revisions(sample_scope)
    assert len(all_recs) == 3


# ---------------------------------------------------------------------------
# Section 5: Cross-Scope Isolation & Non-Leakage
# ---------------------------------------------------------------------------


def test_cross_scope_reads_and_writes_denied_without_existence_leakage(
    revision_service: ConfigurationRevisionService,
    sample_scope: dict[str, str],
    foreign_scope: dict[str, str],
):
    """Cross-scope reads return None (uniform 404) and writes raise ScopeAccessDeniedError."""
    # Create revision under sample_scope
    rev = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint="sha3_256:healthcare_private_cfg",
        target_instances=["node-hc-1"],
    )

    # Foreign scope attempting to read the revision receives None (no existence leakage)
    assert revision_service.get_revision(foreign_scope, rev.revision_id) is None

    # Foreign scope attempting to record instance observation fails closed
    with pytest.raises(ScopeAccessDeniedError):
        revision_service.record_instance_observation(
            context=foreign_scope,
            revision_id=rev.revision_id,
            instance_id="attacker-node",
            consumed_fingerprint="sha3_256:tampered",
        )

    # Foreign scope attempting to acknowledge deployment fails closed
    with pytest.raises(ScopeAccessDeniedError):
        revision_service.acknowledge_deployment(
            context=foreign_scope,
            revision_id=rev.revision_id,
        )

    # Foreign scope attempting rollback fails closed
    with pytest.raises(ScopeAccessDeniedError):
        revision_service.rollback(
            context=foreign_scope,
            target_revision_id=rev.revision_id,
        )


# ---------------------------------------------------------------------------
# Section 6: Evidence & Manifest Audit Binding
# ---------------------------------------------------------------------------


def test_bind_revision_to_evidence(
    revision_service: ConfigurationRevisionService,
    sample_scope: dict[str, str],
):
    """Observed configuration revision state binds cleanly to execution evidence/manifest."""
    rev = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint="sha3_256:audit_bound_fingerprint",
        target_instances=["worker-1"],
    )
    observed_rev = revision_service.record_instance_observation(
        context=sample_scope,
        revision_id=rev.revision_id,
        instance_id="worker-1",
        consumed_fingerprint="sha3_256:audit_bound_fingerprint",
        reload_status="reloaded",
    )

    manifest: dict[str, Any] = {
        "run_id": "run_test_audit_123",
        "scenario_id": "clinical_trial_verification",
    }

    bound = bind_revision_to_evidence(manifest, observed_rev)
    assert "config_revision" in bound
    cfg_evidence = bound["config_revision"]
    assert cfg_evidence["revision_id"] == rev.revision_id
    assert cfg_evidence["desired_fingerprint"] == "sha3_256:audit_bound_fingerprint"
    assert cfg_evidence["status"] == "OBSERVED"
    assert "worker-1" in cfg_evidence["instances"]
    assert cfg_evidence["instances"]["worker-1"]["reload_status"] == "reloaded"
    assert cfg_evidence["target_scope"] == sample_scope


# ---------------------------------------------------------------------------
# Section 7: Models Serialization Roundtrip
# ---------------------------------------------------------------------------


def test_revision_models_serialization_roundtrip(sample_scope: dict[str, str]):
    """InstanceObservation and ConfigurationRevisionRecord support lossless dict roundtrip."""
    diag = ConfigDiagnosticError(source="env", error_type="custom", message="Test")
    obs = InstanceObservation(
        instance_id="inst-rt",
        consumed_fingerprint="fp123",
        reload_status="reloaded",
        observed_at="2026-10-15T00:00:00Z",
        failure_reason=None,
        diagnostics=[diag],
    )
    obs_dict = obs.to_dict()
    obs_rebuilt = InstanceObservation.from_dict(obs_dict)
    assert obs_rebuilt.instance_id == "inst-rt"
    assert obs_rebuilt.consumed_fingerprint == "fp123"
    assert len(obs_rebuilt.diagnostics) == 1

    rec = ConfigurationRevisionRecord(
        revision_id="rev_rt_1",
        target_scope=sample_scope,
        desired_fingerprint="fp123",
        status=ConfigurationRevisionState.OBSERVED.value,
        provider_acknowledged=True,
        target_instances=["inst-rt"],
        instances={"inst-rt": obs},
    )
    rec_dict = rec.to_dict()
    rec_rebuilt = ConfigurationRevisionRecord.from_dict(rec_dict)
    assert rec_rebuilt.revision_id == "rev_rt_1"
    assert rec_rebuilt.status == "OBSERVED"
    assert rec_rebuilt.instances["inst-rt"].instance_id == "inst-rt"


def test_revision_service_and_config_coverage_branches(
    revision_service: ConfigurationRevisionService,
    sample_scope: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
):
    """Test boundary conditions, empty target instances, invalid scope queries, and error paths."""
    from agentv_runtime.config import is_production

    # Default storage root
    default_svc = ConfigurationRevisionService()
    assert default_svc._root.name == "revisions"

    # Invalid instance_id
    with pytest.raises(ValueError, match="instance_id must be a non-empty string"):
        revision_service.record_instance_observation(
            context=sample_scope,
            revision_id="rev_123",
            instance_id="",
            consumed_fingerprint="fp",
        )

    # Empty target_instances in record_instance_observation
    rev_dyn = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint="sha3_256:dynamic_fp",
        target_instances=None,
    )
    revision_service.acknowledge_deployment(sample_scope, rev_dyn.revision_id)
    obs_dyn = revision_service.record_instance_observation(
        context=sample_scope,
        revision_id=rev_dyn.revision_id,
        instance_id="dyn-node-1",
        consumed_fingerprint="sha3_256:dynamic_fp",
        reload_status="reloaded",
    )
    assert obs_dyn.status == ConfigurationRevisionState.OBSERVED.value

    # Rollback with expected_base_revision_id matching active
    active = revision_service.get_active_revision(sample_scope)
    assert active is not None
    rb = revision_service.rollback(
        context=sample_scope,
        target_revision_id=rev_dyn.revision_id,
        expected_base_revision_id=active.revision_id,
    )
    assert rb.is_rollback is True

    # Rollback with mismatched expected_base_revision_id raises StaleRevisionError
    with pytest.raises(StaleRevisionError, match="does not match current active revision"):
        revision_service.rollback(
            context=sample_scope,
            target_revision_id=rev_dyn.revision_id,
            expected_base_revision_id="stale_active_id",
        )

    # Pending instance observation preserving DEPLOYED status
    rev_pending = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint="sha3_256:pending_fp",
        target_instances=["pending-node"],
    )
    revision_service.acknowledge_deployment(sample_scope, rev_pending.revision_id)
    obs_p = revision_service.record_instance_observation(
        context=sample_scope,
        revision_id=rev_pending.revision_id,
        instance_id="unrelated-node",
        consumed_fingerprint="different",
        reload_status="pending",
    )
    assert obs_p.status == ConfigurationRevisionState.DEPLOYED.value

    # Invalid context queries
    assert revision_service.get_revision({}, "any_id") is None
    assert revision_service.get_active_revision({}) is None
    assert revision_service.list_revisions({}) == []

    # Non-existent scope dir
    empty_scope = {
        "org_id": "non_existent_org",
        "tenant_id": "none",
        "workspace_id": "none",
        "active_environment": "none",
    }
    assert revision_service.list_revisions(empty_scope) == []

    # Corrupted file and mismatched scope in storage
    s_dir = revision_service._scope_dir(sample_scope)
    (s_dir / "rev_corrupt.json").write_text("NOT_JSON", encoding="utf-8")
    assert revision_service.get_revision(sample_scope, "rev_corrupt") is None
    recs_with_corrupt = revision_service.list_revisions(sample_scope)
    assert len(recs_with_corrupt) >= 1

    (s_dir / ".active_revision.json").write_text("NOT_JSON", encoding="utf-8")
    assert revision_service.get_active_revision(sample_scope) is None

    (s_dir / ".active_revision.json").write_text(
        json.dumps({"active_revision_id": ""}), encoding="utf-8"
    )
    assert revision_service.get_active_revision(sample_scope) is None

    (s_dir / "rev_mismatch.json").write_text(
        json.dumps({"revision_id": "rev_mismatch", "target_scope": {"org_id": "diff"}}),
        encoding="utf-8",
    )
    assert revision_service.get_revision(sample_scope, "rev_mismatch") is None
    recs_filtered = revision_service.list_revisions(sample_scope)
    assert not any(r.revision_id == "rev_mismatch" for r in recs_filtered)

    # is_production and ConfigResolver.resolve success branch
    monkeypatch.setenv("AGENTV_ENV", "production")
    assert is_production() is True
    monkeypatch.setenv("AGENTV_ENV", "dev")
    assert is_production() is False

    cfg_ok = ConfigResolver.resolve(fail_closed=False)
    assert cfg_ok is not None


# ---------------------------------------------------------------------------
# Section 7: Runtime Worker Consumer & Deployment Provider Adapter
# ---------------------------------------------------------------------------


def test_runtime_worker_config_consumer_successful_reload(tmp_path: Path):
    """
    Verifies that a Runtime worker consumer reloads desired configuration,
    verifies fingerprint agreement, and emits a reloaded InstanceObservation.
    """
    resolver = ConfigResolver()
    consumer = RuntimeWorkerConfigConsumer(
        instance_id="worker-node-01", resolver=resolver, config_dir=tmp_path / "config"
    )

    payload = {"custom_settings": {"cache_ttl": 300}, "audit_level": 2}
    expected_result = resolver.resolve_detailed(overrides=payload)
    desired_fp = expected_result.snapshot_fingerprint

    record = ConfigurationRevisionRecord(
        revision_id="rev_test_worker_1",
        target_scope={
            "org_id": "o1",
            "tenant_id": "t1",
            "workspace_id": "w1",
            "active_environment": "prod",
        },
        desired_fingerprint=desired_fp,
    )

    obs = consumer.consume_and_reload(record, config_dict=payload)
    assert obs.instance_id == "worker-node-01"
    assert obs.reload_status == "reloaded"
    assert obs.consumed_fingerprint == desired_fp
    assert obs.failure_reason is None
    assert obs.diagnostics == []
    assert consumer.consumed_fingerprint == desired_fp
    assert consumer.active_revision_id == "rev_test_worker_1"


def test_runtime_worker_config_consumer_fingerprint_mismatch(tmp_path: Path):
    """
    Verifies that a Runtime worker consumer reports failure if consumed fingerprint
    differs from desired revision fingerprint.
    """
    resolver = ConfigResolver()
    consumer = RuntimeWorkerConfigConsumer(
        instance_id="worker-node-mismatch", resolver=resolver, config_dir=tmp_path / "config"
    )

    record = ConfigurationRevisionRecord(
        revision_id="rev_test_worker_2",
        target_scope={
            "org_id": "o1",
            "tenant_id": "t1",
            "workspace_id": "w1",
            "active_environment": "prod",
        },
        desired_fingerprint="sha3_256:expected_different_fingerprint",
    )

    payload = {"custom_settings": {"mode": "fast"}}
    obs = consumer.consume_and_reload(record, config_dict=payload)
    assert obs.reload_status == "failed"
    assert "does not match desired revision fingerprint" in (obs.failure_reason or "")


def test_runtime_worker_config_consumer_mandate_conflict(tmp_path: Path):
    """
    Verifies that mandate conflicts during worker reload fail closed with diagnostics.
    """
    cfg_dir = tmp_path / "config_mandates"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "mandates.yaml").write_text("mandates:\n  audit_level: 3\n", encoding="utf-8")

    resolver = ConfigResolver()
    consumer = RuntimeWorkerConfigConsumer(
        instance_id="worker-node-conflict", resolver=resolver, config_dir=cfg_dir
    )

    record = ConfigurationRevisionRecord(
        revision_id="rev_test_worker_3",
        target_scope={
            "org_id": "o1",
            "tenant_id": "t1",
            "workspace_id": "w1",
            "active_environment": "prod",
        },
        desired_fingerprint="any_fp",
    )

    # Runtime mandate conflicts with file mandate (3 != 1)
    obs = consumer.consume_and_reload(record, mandates={"audit_level": 1})
    assert obs.reload_status == "failed"
    assert "Mandate conflict on 'audit_level'" in (obs.failure_reason or "")
    assert len(obs.diagnostics) == 1
    assert obs.diagnostics[0].error_type == "mandate_conflict"


def test_runtime_worker_config_consumer_exception_handling():
    """
    Verifies that unexpected worker reload exceptions are caught
    and reported as failed observations.
    """
    mock_resolver = ConfigResolver()
    consumer = RuntimeWorkerConfigConsumer(instance_id="worker-node-crash", resolver=mock_resolver)

    record = ConfigurationRevisionRecord(
        revision_id="rev_test_worker_4",
        target_scope={
            "org_id": "o1",
            "tenant_id": "t1",
            "workspace_id": "w1",
            "active_environment": "prod",
        },
        desired_fingerprint="any_fp",
    )

    def crash(*args, **kwargs):
        raise RuntimeError("Disk I/O failure during worker reload")

    mock_resolver.resolve_detailed = crash  # type: ignore[assignment]

    obs = consumer.consume_and_reload(record)
    assert obs.reload_status == "failed"
    assert "Disk I/O failure" in (obs.failure_reason or "")
    assert len(obs.diagnostics) == 1
    assert obs.diagnostics[0].error_type == "worker_reload_exception"


def test_runtime_deployment_provider_adapter_full_rollout(
    revision_service: ConfigurationRevisionService, sample_scope: dict[str, str], tmp_path: Path
):
    """
    Verifies that the deployment provider adapter coordinates acknowledgement,
    worker reload, and observation aggregation to OBSERVED across multiple workers.
    """
    adapter = revision_service.get_deployment_adapter()

    resolver_1 = ConfigResolver()
    resolver_2 = ConfigResolver()

    payload = {"custom_settings": {"workers": 8}, "audit_level": 2}
    expected_fp = resolver_1.resolve_detailed(overrides=payload).snapshot_fingerprint

    record = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint=expected_fp,
        target_instances=["worker-1", "worker-2"],
    )
    assert record.status == ConfigurationRevisionState.PROVIDER_ACCEPTED.value

    w1 = RuntimeWorkerConfigConsumer(
        instance_id="worker-1", resolver=resolver_1, config_dir=tmp_path / "w1"
    )
    w2 = RuntimeWorkerConfigConsumer(
        instance_id="worker-2", resolver=resolver_2, config_dir=tmp_path / "w2"
    )

    updated_record = adapter.deploy_and_observe(
        context=sample_scope,
        revision_id=record.revision_id,
        workers=[w1, w2],
        config_payload=payload,
    )

    assert updated_record.provider_acknowledged is True
    assert updated_record.status == ConfigurationRevisionState.OBSERVED.value
    assert len(updated_record.instances) == 2
    assert updated_record.instances["worker-1"].reload_status == "reloaded"
    assert updated_record.instances["worker-2"].reload_status == "reloaded"

    # Active pointer is updated
    active = revision_service.get_active_revision(sample_scope)
    assert active is not None
    assert active.revision_id == record.revision_id


def test_runtime_deployment_provider_adapter_partial_rollout(
    revision_service: ConfigurationRevisionService, sample_scope: dict[str, str], tmp_path: Path
):
    """
    Verifies that partial worker failure during rollout produces PARTIALLY_APPLIED.
    """
    adapter = RuntimeDeploymentProviderAdapter(revision_service)

    resolver_1 = ConfigResolver()
    payload = {"custom_settings": {"batch_size": 64}}
    desired_fp = resolver_1.resolve_detailed(overrides=payload).snapshot_fingerprint

    record = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint=desired_fp,
        target_instances=["worker-ok", "worker-fail"],
    )

    w_ok = RuntimeWorkerConfigConsumer(
        instance_id="worker-ok", resolver=resolver_1, config_dir=tmp_path / "w1"
    )

    # Worker with failing resolver
    w_fail = RuntimeWorkerConfigConsumer(instance_id="worker-fail")
    w_fail.consume_and_reload = lambda *args, **kwargs: InstanceObservation(  # type: ignore[assignment]
        instance_id="worker-fail",
        consumed_fingerprint="corrupt_fp",
        reload_status="failed",
        observed_at="2026-10-15T00:00:00Z",
        failure_reason="Corrupt binary",
    )

    updated_record = adapter.deploy_and_observe(
        context=sample_scope,
        revision_id=record.revision_id,
        workers=[w_ok, w_fail],
        config_payload=payload,
    )

    assert updated_record.status == ConfigurationRevisionState.PARTIALLY_APPLIED.value
    assert updated_record.instances["worker-ok"].reload_status == "reloaded"
    assert updated_record.instances["worker-fail"].reload_status == "failed"


def test_runtime_deployment_provider_adapter_report_worker_observation(
    revision_service: ConfigurationRevisionService, sample_scope: dict[str, str]
):
    """
    Verifies direct reporting of external worker observations via the deployment adapter.
    """
    adapter = RuntimeDeploymentProviderAdapter(revision_service)

    record = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint="sha3_256:direct_report_fp",
        target_instances=["direct-worker-01"],
    )
    revision_service.acknowledge_deployment(sample_scope, record.revision_id)

    obs = InstanceObservation(
        instance_id="direct-worker-01",
        consumed_fingerprint="sha3_256:direct_report_fp",
        reload_status="reloaded",
        observed_at="2026-10-15T00:00:00Z",
    )

    updated_rec = adapter.report_worker_observation(
        context=sample_scope,
        revision_id=record.revision_id,
        observation=obs,
    )
    assert updated_rec.status == ConfigurationRevisionState.OBSERVED.value
    assert "direct-worker-01" in updated_rec.instances


# ---------------------------------------------------------------------------
# 8. Execution-Worker Lifecycle Adoption Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_worker_adoption_successful_rollout(
    revision_service: ConfigurationRevisionService,
    sample_scope: dict[str, str],
    monkeypatch,
    tmp_path: Path,
):
    """
    Verifies that the DefaultRunner execution lifecycle retrieves the scope's revision,
    consumes it through RuntimeWorkerConfigConsumer, reports observation through the adapter,
    transitions status to OBSERVED, and binds the revision record to evidence.
    """
    from eval_runner.runner import DefaultRunner

    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setenv("AGENTV_WORKER_INSTANCE_ID", "worker-exec-01")

    async def mock_exec(*args, **kwargs):
        return [
            {
                "workflow_verdict": {"status": "COMPLETED"},
                "oracle_results": [{"oracle_id": "oracle_1", "passed": True}],
            }
        ]

    monkeypatch.setattr("eval_runner.session.SessionManager.execute_tasks", mock_exec)

    resolver = ConfigResolver()
    payload = {"custom_settings": {"max_concurrency": 16}, "audit_level": 2}
    expected_fp = resolver.resolve_detailed(overrides=payload).snapshot_fingerprint

    # Step 1: Accept & acknowledge deployment for target worker
    rec = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint=expected_fp,
        target_instances=["worker-exec-01"],
    )
    revision_service.acknowledge_deployment(sample_scope, rec.revision_id)

    scenario = {
        "id": "scen_exec_adopt",
        "config": payload,
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "tool": "echo",
                    "arguments": {"msg": "hi"},
                    "success_criteria": [{"type": "exact_match", "expected": "hi"}],
                }
            ]
        },
    }

    runner = DefaultRunner(revision_service=revision_service)
    result = await runner.run(
        scenario,
        run_id="run_config_adopt_01",
        metadata={"runtime_context": sample_scope},
    )

    assert result is not None
    # Verify active revision is now OBSERVED
    active = revision_service.get_active_revision(sample_scope)
    assert active is not None
    assert active.revision_id == rec.revision_id
    assert active.status == ConfigurationRevisionState.OBSERVED.value
    assert "worker-exec-01" in active.instances
    assert active.instances["worker-exec-01"].reload_status == "reloaded"

    # Verify evidence binding in stored run manifest
    run_record = runner.run_store.get_run("run_config_adopt_01")
    assert run_record is not None
    saved_manifest = run_record.get("manifest", {})
    assert "config_revision" in saved_manifest
    assert saved_manifest["config_revision"]["revision_id"] == rec.revision_id
    assert saved_manifest["config_revision"]["status"] == ConfigurationRevisionState.OBSERVED.value
    assert saved_manifest["config_revision"]["desired_fingerprint"] == expected_fp


@pytest.mark.asyncio
async def test_runner_worker_adoption_failed_reload_preserves_previous_active(
    revision_service: ConfigurationRevisionService,
    sample_scope: dict[str, str],
    monkeypatch,
    tmp_path: Path,
):
    """
    Verifies that worker reload failure reports FAILED, binds structured diagnostics
    to evidence, and retains the previously observed active revision without altering it.
    """
    from eval_runner.runner import DefaultRunner

    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setenv("AGENTV_WORKER_INSTANCE_ID", "worker-exec-fail")

    async def mock_exec(*args, **kwargs):
        return [
            {
                "workflow_verdict": {"status": "COMPLETED"},
                "oracle_results": [{"oracle_id": "oracle_1", "passed": True}],
            }
        ]

    monkeypatch.setattr("eval_runner.session.SessionManager.execute_tasks", mock_exec)

    # Establish initial verified active revision
    rec_baseline = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint="sha3_256:baseline_valid_fingerprint",
        target_instances=["worker-exec-fail"],
    )
    revision_service.acknowledge_deployment(sample_scope, rec_baseline.revision_id)
    adapter = revision_service.get_deployment_adapter()
    adapter.report_worker_observation(
        sample_scope,
        rec_baseline.revision_id,
        InstanceObservation(
            instance_id="worker-exec-fail",
            consumed_fingerprint="sha3_256:baseline_valid_fingerprint",
            reload_status="reloaded",
            observed_at="2026-10-15T00:00:00Z",
        ),
    )
    baseline_active = revision_service.get_active_revision(sample_scope)
    assert baseline_active is not None
    assert baseline_active.revision_id == rec_baseline.revision_id

    # Create new desired revision with mismatching fingerprint
    rec_broken = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint="sha3_256:target_different_fingerprint",
        target_instances=["worker-exec-fail"],
    )
    revision_service.acknowledge_deployment(sample_scope, rec_broken.revision_id)

    scenario = {
        "id": "scen_broken_config",
        "config": {"mode": "test"},
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "tool": "echo",
                    "arguments": {"msg": "hi"},
                    "success_criteria": [{"type": "exact_match", "expected": "hi"}],
                }
            ]
        },
    }

    runner = DefaultRunner(revision_service=revision_service)
    result = await runner.run(
        scenario,
        run_id="run_config_adopt_fail",
        metadata={"runtime_context": sample_scope},
    )

    assert result is not None
    # Previous active revision is retained
    active = revision_service.get_active_revision(sample_scope)
    assert active is not None
    assert active.revision_id == rec_baseline.revision_id

    # New revision marked FAILED
    broken_rec = revision_service.get_revision(sample_scope, rec_broken.revision_id)
    assert broken_rec is not None
    assert broken_rec.status == ConfigurationRevisionState.FAILED.value
    assert broken_rec.instances["worker-exec-fail"].reload_status == "failed"

    # Evidence binding retains failure diagnostics
    run_record = runner.run_store.get_run("run_config_adopt_fail")
    assert run_record is not None
    saved_manifest = run_record.get("manifest", {})
    assert "config_revision" in saved_manifest
    assert saved_manifest["config_revision"]["revision_id"] == rec_broken.revision_id
    assert saved_manifest["config_revision"]["status"] == ConfigurationRevisionState.FAILED.value


@pytest.mark.asyncio
async def test_runner_worker_adoption_multi_instance_partial_rollout(
    revision_service: ConfigurationRevisionService,
    sample_scope: dict[str, str],
    monkeypatch,
    tmp_path: Path,
):
    """
    Verifies that multi-worker deployments report PARTIALLY_APPLIED when only
    one of multiple targeted workers has completed observation.
    """
    from eval_runner.runner import DefaultRunner

    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setenv("AGENTV_WORKER_INSTANCE_ID", "worker-node-1")

    async def mock_exec(*args, **kwargs):
        return [
            {
                "workflow_verdict": {"status": "COMPLETED"},
                "oracle_results": [{"oracle_id": "oracle_1", "passed": True}],
            }
        ]

    monkeypatch.setattr("eval_runner.session.SessionManager.execute_tasks", mock_exec)

    resolver = ConfigResolver()
    payload = {"custom_settings": {"timeout": 60}}
    expected_fp = resolver.resolve_detailed(overrides=payload).snapshot_fingerprint

    # Deploy revision targeted at TWO instances
    rec_multi = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint=expected_fp,
        target_instances=["worker-node-1", "worker-node-2"],
    )
    revision_service.acknowledge_deployment(sample_scope, rec_multi.revision_id)

    scenario = {
        "id": "scen_multi_worker",
        "config": payload,
        "workflow": {
            "nodes": [
                {
                    "id": "node_1",
                    "tool": "echo",
                    "arguments": {"msg": "hi"},
                    "success_criteria": [{"type": "exact_match", "expected": "hi"}],
                }
            ]
        },
    }

    runner = DefaultRunner(revision_service=revision_service)
    await runner.run(
        scenario,
        run_id="run_config_adopt_partial",
        metadata={"runtime_context": sample_scope},
    )

    # Status must be PARTIALLY_APPLIED because worker-node-2 hasn't observed yet
    multi_rec = revision_service.get_revision(sample_scope, rec_multi.revision_id)
    assert multi_rec is not None
    assert multi_rec.status == ConfigurationRevisionState.PARTIALLY_APPLIED.value
    assert "worker-node-1" in multi_rec.instances
    assert "worker-node-2" not in multi_rec.instances

    # Active pointer not yet updated
    assert revision_service.get_active_revision(sample_scope) is None

    # Stored manifest evidence reflects PARTIALLY_APPLIED
    run_record = runner.run_store.get_run("run_config_adopt_partial")
    assert run_record is not None
    saved_manifest = run_record.get("manifest", {})
    assert (
        saved_manifest["config_revision"]["status"]
        == ConfigurationRevisionState.PARTIALLY_APPLIED.value
    )


def test_config_revision_service_and_adapter_full_branch_coverage(
    revision_service: ConfigurationRevisionService,
    sample_scope: dict[str, str],
):
    """
    Exhaustively exercises boundary branches:
    - accept_revision with expected_base_revision_id matching and mismatching
    - acknowledge_deployment with provider_acknowledged=False
    - record_instance_observation with pending status and unacknowledged deployment
    - get_pending_or_active_revision with invalid scope, instance targeting filters,
      and fallback to active
    - deployment adapter forwarding of get_pending_or_active_revision
    """
    # Invalid scope in get_pending_or_active_revision returns None
    assert revision_service.get_pending_or_active_revision({}) is None
    adapter = revision_service.get_deployment_adapter()
    assert adapter.get_pending_or_active_revision({}) is None

    # Base active revision setup
    rev1 = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint="sha3_256:fp_v1",
        target_instances=["worker-A"],
    )
    revision_service.acknowledge_deployment(sample_scope, rev1.revision_id)
    revision_service.record_instance_observation(
        sample_scope,
        rev1.revision_id,
        instance_id="worker-A",
        consumed_fingerprint="sha3_256:fp_v1",
        reload_status="reloaded",
    )
    active = revision_service.get_active_revision(sample_scope)
    assert active is not None
    assert active.revision_id == rev1.revision_id

    # accept_revision concurrency check with expected_base_revision_id
    with pytest.raises(StaleRevisionError):
        revision_service.accept_revision(
            context=sample_scope,
            desired_fingerprint="sha3_256:fp_v2",
            expected_base_revision_id="stale_active_id",
        )

    rev2 = revision_service.accept_revision(
        context=sample_scope,
        desired_fingerprint="sha3_256:fp_v2",
        expected_base_revision_id=active.revision_id,
        target_instances=["worker-B"],
    )
    assert rev2 is not None

    # acknowledge_deployment with provider_acknowledged=False leaves status unchanged
    rev_unack = revision_service.acknowledge_deployment(
        sample_scope, rev2.revision_id, provider_acknowledged=False
    )
    assert rev_unack.provider_acknowledged is False
    assert rev_unack.status == ConfigurationRevisionState.PROVIDER_ACCEPTED.value

    # Pending observation when provider_acknowledged is False
    obs_pending = revision_service.record_instance_observation(
        sample_scope,
        rev2.revision_id,
        instance_id="worker-B",
        consumed_fingerprint="sha3_256:fp_v2",
        reload_status="pending",
    )
    assert obs_pending.status == ConfigurationRevisionState.PROVIDER_ACCEPTED.value

    # get_pending_or_active_revision with target_instances filter
    # Worker-C is not in target_instances (["worker-B"]) of pending rev2
    # So it skips rev2 and falls back to active revision (rev1)
    rev_for_c = adapter.get_pending_or_active_revision(sample_scope, instance_id="worker-C")
    assert rev_for_c is not None
    assert rev_for_c.revision_id == rev1.revision_id

    # When no instance_id is provided, rev2 (PROVIDER_ACCEPTED) is returned
    rev_for_any = adapter.get_pending_or_active_revision(sample_scope)
    assert rev_for_any is not None
    assert rev_for_any.revision_id == rev2.revision_id

    # Fallback to active when all revisions are non-pending (e.g. OBSERVED)
    revision_service.record_instance_observation(
        sample_scope,
        rev2.revision_id,
        instance_id="worker-B",
        consumed_fingerprint="sha3_256:fp_v2",
        reload_status="reloaded",
    )
    active_now = adapter.get_pending_or_active_revision(sample_scope, instance_id="worker-B")
    assert active_now is not None
    assert active_now.revision_id == rev2.revision_id
