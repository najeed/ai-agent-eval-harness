"""
Canonical unit and contract tests for Runtime Configuration Diagnostics
and Atomic Scoped Run Registration.
"""

from __future__ import annotations

import json

import pytest

from agentv_runtime.config import (
    ConfigDiagnosticError,
    ConfigKeyDiagnostic,
    ConfigResolutionError,
    ConfigResolver,
    ConfigSourceContributor,
    DetailedResolutionResult,
    classify_sensitivity,
    redact_sensitive_value,
)
from eval_runner.config import RegistryManager
from eval_runner.reference.local_run_store import LocalFileRunStore

# ---------------------------------------------------------------------------
# Section 1: agentv_runtime.config Diagnostics Contract & Resolution
# ---------------------------------------------------------------------------


def test_classify_sensitivity_and_redaction():
    assert classify_sensitivity("api_key") == ("secret", True)
    assert classify_sensitivity("token") == ("secret", True)
    assert classify_sensitivity("signing_key") == ("secret", True)
    assert classify_sensitivity("signing_algorithm") == ("sensitive", False)
    assert classify_sensitivity("auth_provider") == ("sensitive", False)
    assert classify_sensitivity("log_dir") == ("internal", False)
    assert classify_sensitivity("endpoint_url") == ("internal", False)
    assert classify_sensitivity("app_name") == ("public", False)

    assert redact_sensitive_value("api_key", "sk-12345") == "[REDACTED]"
    assert redact_sensitive_value("normal_setting", "value1") == "value1"
    nested = {"sub_secret": "sensitive_val", "public_info": "hello"}
    redacted_nested = redact_sensitive_value("app_settings", nested)
    assert redacted_nested == {"sub_secret": "[REDACTED]", "public_info": "hello"}

    redacted_top_secret = redact_sensitive_value("credentials", nested)
    assert redacted_top_secret == "[REDACTED]"

    redacted_list = redact_sensitive_value("api_key", ["secret1", "secret2"])
    assert redacted_list == "[REDACTED]"

    safe_list = redact_sensitive_value("tags", ["tag1", "tag2"])
    assert safe_list == ["tag1", "tag2"]


def test_detailed_resolution_data_models_and_to_dict():
    contrib = ConfigSourceContributor(
        source_type="file",
        source_name="config.json",
        value="test_val",
        applied=True,
    )
    assert contrib.source_type == "file"
    assert contrib.applied is True

    diag = ConfigKeyDiagnostic(
        canonical_key="core.audit_level",
        effective_value="STANDARD",
        contributors=[contrib],
        validation_diagnostics=[],
        sensitivity="internal",
        is_secret=False,
    )

    err = ConfigDiagnosticError(
        source="env:AUDIT_LEVEL",
        error_type="invalid_override",
        message="Invalid audit level value",
        raw_value="BOGUS",
        canonical_key="core.audit_level",
    )

    result = DetailedResolutionResult(
        provider_name="runtime_config_mesh",
        precedence_order=["default", "file", "env", "override", "mandate"],
        snapshot_fingerprint="abc123sha",
        entries={"core.audit_level": diag},
        errors=[err],
        effective_snapshot=None,
        is_valid=False,
    )

    data = result.to_dict()
    assert data["provider_name"] == "runtime_config_mesh"
    assert data["precedence_order"] == ["default", "file", "env", "override", "mandate"]
    assert data["snapshot_fingerprint"] == "abc123sha"
    assert data["is_valid"] is False
    assert len(data["errors"]) == 1
    assert data["errors"][0]["error_type"] == "invalid_override"
    assert "core.audit_level" in data["entries"]


def test_config_resolver_resolve_detailed_five_tier_provenance(tmp_path, monkeypatch):
    """Verify attribution across all 5 tiers: default -> file -> env -> override -> mandate."""
    monkeypatch.delenv("AGENTV_CONFIG_DIR", raising=False)
    monkeypatch.delenv("AUDIT_LEVEL", raising=False)
    monkeypatch.delenv("RUN_TIMEOUT_SECONDS", raising=False)

    conf_dir = tmp_path / "config"
    conf_dir.mkdir()
    d_dir = conf_dir / "conf.d"
    d_dir.mkdir()
    (d_dir / "custom.json").write_text(
        json.dumps({"core": {"audit_level": "COMPREHENSIVE"}}), encoding="utf-8"
    )

    monkeypatch.setenv("AGENTV_CONFIG_DIR", str(conf_dir))
    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "120")

    result = ConfigResolver.resolve_detailed(
        overrides={"core": {"telemetry_enabled": False}},
        mandates={"core": {"audit_level": 3}},
        fail_closed=False,
    )

    assert isinstance(result, DetailedResolutionResult)
    assert result.provider_name == "runtime_config_mesh"
    assert result.precedence_order == ["default", "file", "env", "override", "mandate"]

    # Verify mandate attribution on audit_level
    audit_diag = result.entries.get("core.audit_level")
    assert audit_diag is not None
    assert audit_diag.effective_value == 3
    sources = [c.source_type for c in audit_diag.contributors]
    assert "default" in sources
    assert "mandate" in sources

    # Verify env attribution on run_timeout_seconds
    timeout_diag = result.entries.get("core.timeout_seconds")
    assert timeout_diag is not None
    assert timeout_diag.effective_value == 120
    assert any(c.source_type == "env" for c in timeout_diag.contributors)


def test_config_resolver_mandate_conflict_recorded(monkeypatch):
    """When a prior source contributed a conflicting value, an error is recorded."""
    monkeypatch.delenv("AUDIT_LEVEL", raising=False)

    result = ConfigResolver.resolve_detailed(
        overrides={"core": {"audit_level": 1}},
        mandates={"core": {"audit_level": 3}},
        fail_closed=False,
    )

    mandate_errors = [e for e in result.errors if e.error_type == "mandate_conflict"]
    assert len(mandate_errors) >= 1
    assert mandate_errors[0].canonical_key == "core.audit_level"


def test_config_resolver_malformed_file_structured_error(tmp_path, monkeypatch):
    """Malformed config file records a structured error and fails closed in production."""
    conf_dir = tmp_path / "config"
    conf_dir.mkdir()
    d_dir = conf_dir / "conf.d"
    d_dir.mkdir()
    (d_dir / "broken.json").write_text("{invalid json", encoding="utf-8")

    monkeypatch.setenv("AGENTV_CONFIG_DIR", str(conf_dir))

    # In non-production, error is recorded without crashing
    res_non_prod = ConfigResolver.resolve_detailed(fail_closed=False)
    assert any(e.error_type == "malformed_file" for e in res_non_prod.errors)

    # In fail-closed mode, raises ConfigResolutionError
    with pytest.raises(ConfigResolutionError) as exc_info:
        ConfigResolver.resolve_detailed(fail_closed=True)
    assert "malformed_file" in [e.error_type for e in exc_info.value.errors]


def test_config_resolver_invalid_env_structured_error(monkeypatch):
    """Invalid env override records a structured error and fails closed when required."""
    monkeypatch.setenv("AUDIT_LEVEL", "NON_EXISTENT_AUDIT_LEVEL")

    res_non_prod = ConfigResolver.resolve_detailed(fail_closed=False)
    assert any(
        e.error_type in ("invalid_environment_override", "invalid_env_override")
        for e in res_non_prod.errors
    )

    with pytest.raises(ConfigResolutionError):
        ConfigResolver.resolve_detailed(fail_closed=True)


# ---------------------------------------------------------------------------
# Section 2: eval_runner.config.RegistryManager Diagnostics Adapter
# ---------------------------------------------------------------------------


def test_registry_manager_resolve_detailed_precedence_and_redaction(tmp_path, monkeypatch):
    """RegistryManager maintains independent precedence: internal_baseline -> filesystem -> env."""
    reg_dir = tmp_path / "aes_config"
    shims_d = reg_dir / "shims.d"
    shims_d.mkdir(parents=True)
    (shims_d / "custom_tool.json").write_text(
        json.dumps({"bash_custom": {"secret_token": "secret_abc_123", "timeout": 30}}),
        encoding="utf-8",
    )

    monkeypatch.setattr("eval_runner.config.AES_CONFIG_DIR", reg_dir)
    monkeypatch.setenv(
        "AES_SHIM_RESOURCES_JSON",
        json.dumps({"shims": {"env_shim": {"api_key": "sk-env-secret-999"}}}),
    )

    result = RegistryManager.resolve_detailed(fail_closed=False)
    assert isinstance(result, DetailedResolutionResult)
    assert result.provider_name == "eval_runner.config.RegistryManager"
    assert result.precedence_order == [
        "internal_baseline",
        "filesystem_discovery",
        "env_override",
    ]

    # Secret keys must be completely redacted in effective values and contributors
    secret_entry = result.entries.get("shims.env_shim.api_key")
    assert secret_entry is not None
    assert secret_entry.is_secret is True
    assert secret_entry.effective_value == "[REDACTED]"
    assert secret_entry.contributors[0].value == "[REDACTED]"

    token_entry = result.entries.get("shims.bash_custom.secret_token")
    assert token_entry is not None
    assert token_entry.is_secret is True
    assert token_entry.effective_value == "[REDACTED]"


def test_registry_manager_structured_errors_on_malformed_input(tmp_path, monkeypatch):
    """RegistryManager records structured errors on invalid files/env and supports fail-closed."""
    reg_dir = tmp_path / "aes_config"
    shims_d = reg_dir / "shims.d"
    shims_d.mkdir(parents=True)
    (shims_d / "corrupted.json").write_text("NOT_JSON", encoding="utf-8")

    monkeypatch.setattr("eval_runner.config.AES_CONFIG_DIR", reg_dir)
    monkeypatch.setenv("AES_SHIM_RESOURCES_JSON", "NOT_JSON_ENV")

    # In resilient mode
    res = RegistryManager.resolve_detailed(fail_closed=False)
    assert len(res.errors) >= 2
    err_types = [e.error_type for e in res.errors]
    assert "parse_error" in err_types
    assert "invalid_env_override" in err_types

    # In fail-closed mode
    with pytest.raises(ConfigResolutionError):
        RegistryManager.resolve_detailed(fail_closed=True)


def test_providers_remain_distinct_and_independent():
    """Assert that the two config providers remain distinct without merging."""
    mesh_res = ConfigResolver.resolve_detailed(fail_closed=False)
    reg_res = RegistryManager.resolve_detailed(fail_closed=False)

    assert mesh_res.provider_name == "runtime_config_mesh"
    assert reg_res.provider_name == "eval_runner.config.RegistryManager"
    assert mesh_res.precedence_order != reg_res.precedence_order


# ---------------------------------------------------------------------------
# Section 3: Atomic Scoped Run Registration & Lifecycle Scoping
# ---------------------------------------------------------------------------


def test_atomic_scoped_submission_reservation_and_transition(tmp_path):
    """Provider admission is scoped, durable, and transition-checked."""
    run_id = "test-run-scoped-123"
    context = {
        "org_id": "test-org",
        "tenant_id": "test-tenant",
        "workspace_id": "test-workspace",
        "active_environment": "staging",
    }

    store = LocalFileRunStore(tmp_path)
    reservation = store.reserve_submission(
        run_id, "scenario-sample", "agent", {}, context, "idem-1"
    )
    assert reservation["state"] == "RESERVED"
    assert store.get_submission(run_id, context=context)["context"] == context
    dispatched = store.transition_submission(run_id, "RESERVED", "DISPATCHED", context)
    assert dispatched["state"] == "DISPATCHED"
    running = store.transition_submission(run_id, "DISPATCHED", "RUNNING", context)
    assert running["state"] == "RUNNING"


def test_submission_reservation_idempotency_and_collision(tmp_path):
    store = LocalFileRunStore(tmp_path)
    context = {
        "org_id": "org",
        "tenant_id": "tenant",
        "workspace_id": "ws",
        "active_environment": "prod",
    }
    first = store.reserve_submission("run", "scen", "agent", {}, context, "idem")
    assert store.reserve_submission("run", "scen", "agent", {}, context, "idem") == first
    with pytest.raises(FileExistsError, match="RunIdCollision"):
        store.reserve_submission("run", "other", "agent", {}, context, "idem")


def test_scoped_submission_exhaustive_edge_cases(tmp_path):
    """Provider admission rejects missing records and invalid CAS transitions."""
    store = LocalFileRunStore(tmp_path)
    valid_context = {
        "org_id": "org_1",
        "tenant_id": "tenant_1",
        "workspace_id": "ws_1",
        "active_environment": "prod",
    }
    assert store.get_submission("missing", context=valid_context) is None
    store.reserve_submission("dup_run", "scen_1", "agent", {}, valid_context, "idem")
    with pytest.raises(RuntimeError, match="SubmissionTransitionConflict"):
        store.transition_submission("dup_run", "RUNNING", "COMPLETED", valid_context)


def test_inprocess_backend_lifecycle_writes_and_failed_manifest(tmp_path, monkeypatch):
    """InProcessExecutionBackend updates the provider submission and manifest."""
    from eval_runner.reference.inprocess_backend import InProcessExecutionBackend

    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)

    run_id = "failing-run-test-456"
    context = {
        "org_id": "org-fail",
        "tenant_id": "tenant-fail",
        "workspace_id": "workspace-fail",
        "active_environment": "prod",
    }
    run_store = LocalFileRunStore(tmp_path)
    run_store.reserve_submission(run_id, "fail-scenario", None, {}, context, "idem-failure")
    run_store.transition_submission(run_id, "RESERVED", "RUNNING", context)

    def failing_runner(*args, **kwargs):
        raise RuntimeError("Simulated execution failure")

    backend = InProcessExecutionBackend(runner_callable=failing_runner, run_store=run_store)
    with pytest.raises(RuntimeError, match="Simulated execution failure"):
        backend.submit(
            run_id=run_id,
            scenario_data={"id": "fail-scenario"},
            background=False,
        )

    # 1. Provider submission status must be FAILED with scope preserved.
    submission = run_store.get_submission(run_id, context=context)
    assert submission["state"] == "FAILED"
    assert submission["context"] == context

    # 2. Failed run manifest must be persisted with verified scope tuple
    manifest_data = run_store.get_manifest(run_id, context=context)
    assert manifest_data is not None
    assert manifest_data["status"] == "FAILED"
    assert manifest_data["context"] == context
    assert "Simulated execution failure" in manifest_data["error"]


def test_async_evaluation_scoped_execution_and_authorized_reads(tmp_path, monkeypatch):
    """Async evaluation executes cleanly while immediate status/stream reads remain authorized."""
    import time

    from eval_runner.reference.inprocess_backend import InProcessExecutionBackend
    from eval_runner.reference.local_run_store import LocalFileRunStore

    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", tmp_path)

    run_id = "async-run-scoped-789"
    context = {
        "org_id": "test-org-async",
        "tenant_id": "test-tenant-async",
        "workspace_id": "test-workspace-async",
        "active_environment": "production",
    }

    run_store = LocalFileRunStore(tmp_path)
    reservation = run_store.reserve_submission(
        run_id, "async-scen-1", None, {}, context, "idem-async"
    )
    assert reservation["state"] == "RESERVED"
    assert run_store.get_submission(run_id, context=context)["context"] == context
    run_store.transition_submission(run_id, "RESERVED", "RUNNING", context)

    # 3. Simulate asynchronous runner execution
    def successful_async_runner(*args, **kwargs):
        # Publish terminal evidence through the same explicit provider that
        # owns the asynchronous execution.
        manifest_payload = {
            "run_id": run_id,
            "scenario_id": "async-scen-1",
            "status": "COMPLETED",
            "context": context,
            "pass_at_k": 1.0,
        }
        run_store.save_run_manifest(run_id, manifest_payload, context=context)
        return {"status": "SUCCESS"}

    backend = InProcessExecutionBackend(
        runner_callable=successful_async_runner,
        run_store=run_store,
    )
    backend.submit(
        run_id=run_id,
        scenario_data={"id": "async-scen-1"},
        background=True,
        run_store=run_store,
        context=context,
    )

    # 4. Wait for the provider-owned terminal run record.
    max_wait = 15.0
    start = time.time()
    final_read = None
    while time.time() - start < max_wait:
        rec = run_store.get_run(run_id, context=context)
        if rec and rec["status"] == "COMPLETED":
            final_read = rec
            break
        time.sleep(0.05)

    assert final_read is not None
    assert final_read["status"] == "COMPLETED"
    assert final_read["context"] == context

    # 5. Provider manifest preserves the immutable scope tuple.
    manifest_data = run_store.get_manifest(run_id, context=context)
    assert manifest_data is not None
    assert manifest_data["status"] == "COMPLETED"
    assert manifest_data["context"] == context


def test_resolved_runtime_config_validation_and_methods():
    from agentv_runtime.config import ResolvedRuntimeConfig

    # Valid instance with pre-computed hash
    cfg = ResolvedRuntimeConfig(config_hash="precomputed_hash")
    assert cfg.config_hash == "precomputed_hash"
    assert isinstance(cfg.to_dict(), dict)

    # Invalid audit_level
    with pytest.raises(ValueError, match="Invalid audit_level"):
        ResolvedRuntimeConfig(audit_level=0)

    # Invalid timeout_seconds
    with pytest.raises(ValueError, match="Invalid timeout_seconds"):
        ResolvedRuntimeConfig(timeout_seconds=0)

    # Invalid execution_backend
    with pytest.raises(ValueError, match="execution_backend must be a non-empty string"):
        ResolvedRuntimeConfig(execution_backend="")

    # Invalid checkpoint_store
    with pytest.raises(ValueError, match="checkpoint_store must be a non-empty string"):
        ResolvedRuntimeConfig(checkpoint_store="")

    # Invalid artifact_store
    with pytest.raises(ValueError, match="artifact_store must be a non-empty string"):
        ResolvedRuntimeConfig(artifact_store="")


def test_config_resolver_env_var_overrides(monkeypatch):
    monkeypatch.setenv("RUN_LOG_DIR", "custom_runs")
    monkeypatch.setenv("AUDIT_LEVEL", "3")
    monkeypatch.setenv("EXECUTION_BACKEND", "in_process")
    monkeypatch.setenv("CHECKPOINT_STORE", "sqlite")
    monkeypatch.setenv("ARTIFACT_STORE", "local_file")
    monkeypatch.setenv("FLIGHT_RECORDER_KEY_PATH", "keys/test.key")
    monkeypatch.setenv("EVAL_SIGNING_FAIL_CLOSED", "true")
    monkeypatch.setenv("ENABLE_HITL", "true")
    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "300")

    result = ConfigResolver.resolve_detailed(fail_closed=False)
    assert result.is_valid
    snap = result.effective_snapshot
    assert snap.run_log_dir == "custom_runs"
    assert snap.audit_level == 3
    assert snap.signing_key_path == "keys/test.key"
    assert snap.fail_closed_signing is True
    assert snap.enable_hitl is True
    assert snap.timeout_seconds == 300


def test_config_resolver_invalid_env_timeout(monkeypatch):
    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "-5")
    result = ConfigResolver.resolve_detailed(fail_closed=False)
    assert not result.is_valid
    assert any(e.canonical_key == "core.timeout_seconds" for e in result.errors)


def test_config_resolver_apply_config_dict_variations():
    # Direct core fields and known namespace dict
    overrides = {
        "audit_level": 4,
        "adapters": {"claude": {"model": "claude-3"}},
        "custom": {"feature_flag": True},
        "extra_field": "extra_val",
    }
    result = ConfigResolver.resolve_detailed(overrides=overrides, fail_closed=False)
    assert result.is_valid
    snap = result.effective_snapshot
    assert snap.audit_level == 4
    assert snap.adapters["claude"]["model"] == "claude-3"
    assert snap.custom_settings["feature_flag"] is True
    assert snap.custom_settings["extra_field"] == "extra_val"


def test_config_resolver_mandate_variations():
    # 1. Mandate on core field directly
    # 2. Mandate on nested core field
    # 3. Mandate on custom settings with dot notation
    # 4. Mandate on new key not in entries
    mandates = {
        "audit_level": 3,
        "core": {"timeout_seconds": 180},
        "features.deep_audit": True,
        "new_mandate_setting": "enforced",
    }
    result = ConfigResolver.resolve_detailed(mandates=mandates, fail_closed=False)
    assert result.is_valid
    snap = result.effective_snapshot
    assert snap.audit_level == 3
    assert snap.timeout_seconds == 180
    assert snap.custom_settings["new_mandate_setting"] == "enforced"


def test_config_resolver_dot_d_malformed_file(tmp_path):
    d_dir = tmp_path / "extra.d"
    d_dir.mkdir()
    # Write a drop file that contains a JSON array (not a dict)
    (d_dir / "01_list.json").write_text(json.dumps(["item1", "item2"]), encoding="utf-8")

    result = ConfigResolver.resolve_detailed(config_dir=tmp_path, fail_closed=False)
    assert not result.is_valid
    assert any(e.error_type == "malformed_file" for e in result.errors)


def test_config_resolver_resolve_fail_closed_and_invalid_snapshot():
    # Production fail-closed on invalid env
    with pytest.raises(ConfigResolutionError, match="failed closed"):
        ConfigResolver.resolve(overrides={"audit_level": 0}, fail_closed=True)

    # resolve with invalid overrides in fail_closed=False raising error because snapshot is None
    with pytest.raises(ConfigResolutionError, match="Configuration resolution failed"):
        ConfigResolver.resolve(overrides={"audit_level": 0}, fail_closed=False)


def test_deep_merge_and_default_timeout_exception(monkeypatch):
    from agentv_runtime.config import _deep_merge

    # Nested dict merge
    res = _deep_merge({"k": {"a": 1}}, {"k": {"b": 2}})
    assert res == {"k": {"a": 1, "b": 2}}

    # RUN_TIMEOUT_SECONDS invalid parse during default initialization
    monkeypatch.setenv("RUN_TIMEOUT_SECONDS", "not_an_int")
    detailed = ConfigResolver.resolve_detailed(fail_closed=False)
    assert any(e.canonical_key == "core.timeout_seconds" for e in detailed.errors)


def test_config_resolver_file_parsing_variations(tmp_path):
    # 1. Valid YAML file
    (tmp_path / "valid.yaml").write_text("custom_yaml_key: yaml_val\n", encoding="utf-8")

    # 2. File with non-dict root
    (tmp_path / "nondict_root.json").write_text(json.dumps("string_root"), encoding="utf-8")

    # 3. File with malformed content
    (tmp_path / "corrupt.json").write_text("{malformed_json_here", encoding="utf-8")

    # 4. Valid drop directory with valid YAML, empty JSON, and corrupt YAML
    d_dir = tmp_path / "nested.d"
    d_dir.mkdir()
    (d_dir / "valid_drop.yaml").write_text("drop_key: drop_val\n", encoding="utf-8")
    (d_dir / "empty_drop.json").write_text("null", encoding="utf-8")
    (d_dir / "corrupt_drop.yaml").write_text("::invalid_yaml", encoding="utf-8")

    result = ConfigResolver.resolve_detailed(config_dir=tmp_path, fail_closed=False)
    assert not result.is_valid
    errors = [e.error_type for e in result.errors]
    assert "malformed_file" in errors

    # Test fail-closed raise on ConfigResolver.resolve with malformed files
    with pytest.raises(ConfigResolutionError, match="Configuration resolution failed closed"):
        ConfigResolver.resolve(config_dir=tmp_path, fail_closed=True)


def test_config_resolver_audit_level_zero_and_deep_mandates(monkeypatch):
    # AUDIT_LEVEL < 1 error
    monkeypatch.setenv("AUDIT_LEVEL", "0")
    res = ConfigResolver.resolve_detailed(fail_closed=False)
    assert not res.is_valid
    assert any(e.canonical_key == "core.audit_level" for e in res.errors)

    # Clean up AUDIT_LEVEL before deep mandate resolution
    monkeypatch.delenv("AUDIT_LEVEL", raising=False)

    # Deep nested mandate and top-level unregistered key
    mandates = {
        "core": {"arbitrary": {"deep": "deep_val"}},
        "completely_unregistered_key": "unregistered_val",
        "my_custom_namespace": {"setting": 123},
    }
    overrides = {"top_level_unregistered": 42}
    res_deep = ConfigResolver.resolve_detailed(
        overrides=overrides,
        mandates=mandates,
        fail_closed=False,
    )
    assert res_deep.effective_snapshot.custom_settings["top_level_unregistered"] == 42
    assert (
        res_deep.effective_snapshot.custom_settings["completely_unregistered_key"]
        == "unregistered_val"
    )
    assert res_deep.effective_snapshot.custom_settings["my_custom_namespace"]["setting"] == 123


def test_config_resolver_uncovered_branches(tmp_path):
    from unittest.mock import patch

    # 1. Non-existent config_dir (branch 402->401)
    res_no_dir = ConfigResolver.resolve_detailed(
        config_dir=tmp_path / "does_not_exist",
        fail_closed=False,
    )
    assert res_no_dir.is_valid

    # 2. File with null data (branch 414->403) and fake.d file (branch 434->433)
    c_dir = tmp_path / "branch_cfg"
    c_dir.mkdir()
    (c_dir / "empty.yaml").write_text("# only comment\n", encoding="utf-8")
    (c_dir / "fake.d").write_text("not a directory", encoding="utf-8")
    res_files = ConfigResolver.resolve_detailed(config_dir=c_dir, fail_closed=False)
    assert res_files.is_valid

    # 3. ConfigResolver.resolve fail-closed lines 699-702
    dummy_invalid = DetailedResolutionResult(
        provider_name="test",
        precedence_order=["default"],
        snapshot_fingerprint="abc",
        entries={},
        errors=[ConfigDiagnosticError(source="test", error_type="custom", message="Mock failure")],
        effective_snapshot=None,
        is_valid=False,
    )
    with patch.object(ConfigResolver, "resolve_detailed", return_value=dummy_invalid):
        with pytest.raises(
            ConfigResolutionError,
            match="Production configuration resolution failed closed",
        ):
            ConfigResolver.resolve(fail_closed=True)
