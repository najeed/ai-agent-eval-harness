"""Contract tests for pluggable run-storage discovery and lifecycle delegation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentv_runtime.canonical import canonical_json_encode
from eval_runner.events import CoreEvents, Event
from eval_runner.flight_recorder import FlightRecorderPlugin
from eval_runner.reference.local_run_store import LocalFileRunStore, RunManifestImmutableError
from eval_runner.run_lifecycle import (
    RunLifecycleState,
    assert_can_write_trace,
    get_run_lifecycle_state,
    transition_run_lifecycle,
)
from eval_runner.storage_resolver import (
    reset_run_storage_provider,
    resolve_run_storage_provider,
    set_active_run_storage_provider,
)


@pytest.fixture(autouse=True)
def isolated_provider():
    reset_run_storage_provider()
    yield
    reset_run_storage_provider()


def test_resolver_discovers_external_entry_point(monkeypatch, tmp_path):
    class ExternalProvider(LocalFileRunStore):
        pass

    provider = ExternalProvider(tmp_path)
    entry_point = SimpleNamespace(name="database", load=lambda: lambda: provider)
    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group=None: [entry_point] if group == "agentv_runtime.run_stores" else [],
    )

    active = resolve_run_storage_provider()
    assert active is provider
    active.create_run("external-1", "scenario-1", context={"org_id": "acme"})
    active.save_run_manifest("external-1", {"status": "SUCCESS"})
    active.update_run_status("external-1", "SEALED")
    assert active.get_run("external-1", context={"org_id": "other"}) is None
    with pytest.raises(RunManifestImmutableError):
        active.save_run_manifest("external-1", {"status": "FAILED"})


def test_resolver_falls_back_to_local_store(monkeypatch):
    monkeypatch.setattr("importlib.metadata.entry_points", lambda **_: [])

    assert isinstance(resolve_run_storage_provider(), LocalFileRunStore)


def test_set_active_run_storage_provider_invalid_type():
    with pytest.raises(TypeError, match="RunStorageProvider"):
        set_active_run_storage_provider("not-a-provider")


def test_local_provider_enforces_context_streaming_and_sealed_manifest(tmp_path):
    store = LocalFileRunStore(tmp_path)
    context = {"org_id": "acme", "workspace_id": "primary"}
    store.create_run("run-1", "scenario-1", context=context)
    store.append_events(
        "run-1", [{"_seq": 1, "event": "run_start"}, {"_seq": 2, "event": "run_end"}]
    )

    assert store.search_runs("scenario", context=context)[0]["run_id"] == "run-1"
    assert store.get_run("run-1", context={"org_id": "other"}) is None
    assert [event["_seq"] for event in store.stream_events("run-1", from_seq=1)] == [2]

    store.save_run_manifest("run-1", {"status": "SUCCESS"})
    assert store.get_manifest("run-1", context=context) == {"status": "SUCCESS"}
    store.update_run_status("run-1", "SEALED")
    with pytest.raises(RunManifestImmutableError):
        store.save_run_manifest("run-1", {"status": "FAILED"})


def test_local_provider_returns_exact_canonical_committed_trace_bytes(tmp_path):
    """Provider trace bytes are the bytes appended and later signed, not a reconstruction."""
    store = LocalFileRunStore(tmp_path)
    store.create_run("run-canonical", "scenario")
    event = {"z": 1, "event": "run_start", "a": "stable"}

    store.append_events("run-canonical", [event])

    assert store.get_trace_bytes("run-canonical") == canonical_json_encode(event) + b"\n"


def test_local_provider_recovers_journaled_certification_commit_after_interruption(tmp_path):
    """A durable commit decision recovers forward instead of exposing a partial seal."""
    store = LocalFileRunStore(tmp_path)
    run_id = "run-recovery"
    store.create_run(run_id, "scenario")
    vault = store._get_run_vault(run_id)
    original = store.get_run(run_id)
    manifest = {"run_id": run_id, "trace_hash": "sha3_256:recovery"}
    sealed_record = {
        **original,
        "status": "SEALED",
        "lifecycle": "SEALED",
    }
    store._write_json_durable(
        store._commit_journal_path(vault),
        {
            "version": 1,
            "run_id": run_id,
            "manifest": manifest,
            "sealed_record": sealed_record,
            "manifest_digest": "ignored-by-recovery",
        },
    )

    assert store.get_manifest(run_id) == manifest
    assert store.get_run(run_id)["lifecycle"] == "SEALED"
    assert (vault / ".sealed").exists()
    assert not store._commit_journal_path(vault).exists()


def test_lifecycle_uses_injected_provider_not_filesystem(tmp_path):
    provider = LocalFileRunStore(tmp_path)
    provider.create_run("run-1", "scenario-1")
    set_active_run_storage_provider(provider)

    assert (
        transition_run_lifecycle("run-1", RunLifecycleState.FINALIZING, run_store=provider)
        == RunLifecycleState.FINALIZING
    )
    assert get_run_lifecycle_state("run-1", run_store=provider) == RunLifecycleState.FINALIZING
    assert provider.get_run("run-1")["status"] == "FINALIZING"


def test_flight_recorder_appends_to_explicit_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_LOG_MASTER", "false")
    monkeypatch.setenv("RUN_LOG_PER_RUN", "true")
    provider = LocalFileRunStore(tmp_path / "provider-a")
    global_provider = LocalFileRunStore(tmp_path / "provider-b")
    # A process-global resolver deliberately points at B.  The recorder has
    # already been bound to A by its execution owner and must not drift.
    set_active_run_storage_provider(global_provider)
    # A recorder is process-global, so ownership must be supplied by its
    # execution owner; it must not inspect the globally selected provider.
    recorder = FlightRecorderPlugin(log_dir=tmp_path, run_store=provider)

    recorder.handle_event(
        Event(CoreEvents.RUN_START, {"run_id": "run-1", "scenario": "scenario-1"})
    )
    recorder.handle_event(Event("tool_call", {"run_id": "run-1"}))

    assert [event["event"] for event in provider.get_events("run-1")] == [
        CoreEvents.RUN_START,
        "tool_call",
    ]
    assert global_provider.get_run("run-1") is None


def test_provider_contexts_are_isolated_for_the_same_run_identifier(tmp_path):
    """Scope checks belong to the provider, not to a console or global resolver."""
    store = LocalFileRunStore(tmp_path)
    context_a = {"org_id": "a", "workspace_id": "one"}
    context_b = {"org_id": "b", "workspace_id": "two"}
    store.create_run("shared-id", "scenario-a", context=context_a)
    store.append_events(
        "shared-id", [{"event": "run_start", "run_id": "shared-id"}], context=context_a
    )

    assert store.get_run("shared-id", context=context_a) is not None
    assert store.get_events("shared-id", context=context_a)
    assert store.get_run("shared-id", context=context_b) is None
    assert store.get_events("shared-id", context=context_b) == []
    assert store.get_trace_bytes("shared-id", context=context_b) is None


def test_unbound_flight_recorder_fails_closed_when_event_is_recorded(tmp_path, monkeypatch):
    """A process-global recorder cannot infer run ownership from global state."""
    monkeypatch.setenv("RUN_LOG_MASTER", "false")
    monkeypatch.setenv("RUN_LOG_PER_RUN", "true")
    recorder = FlightRecorderPlugin(log_dir=tmp_path)
    provider = LocalFileRunStore(tmp_path / "active-provider")
    set_active_run_storage_provider(provider)

    with pytest.raises(RuntimeError, match="RunStorageProviderBindingRequired"):
        recorder.handle_event(
            Event(CoreEvents.RUN_START, {"run_id": "late-bound-run", "scenario": "scenario-1"})
        )
    assert provider.get_events("late-bound-run") == []


def test_inprocess_resume_uses_owned_provider_and_never_re_resolves_global(tmp_path):
    from eval_runner.reference.inprocess_backend import InProcessExecutionBackend

    provider_a = LocalFileRunStore(tmp_path / "provider-a")
    provider_b = LocalFileRunStore(tmp_path / "provider-b")
    run_id = "backend-provider-affinity"
    provider_a.create_run(run_id, "scenario-a")
    transition_run_lifecycle(run_id, RunLifecycleState.PAUSED_FOR_APPROVAL, run_store=provider_a)
    backend = InProcessExecutionBackend(run_store=provider_a)
    backend._active_runs[run_id] = {"status": "PAUSED", "scenario_data": {"id": "scenario-a"}}
    set_active_run_storage_provider(provider_b)

    backend.resume(run_id)

    assert get_run_lifecycle_state(run_id, run_store=provider_a) == RunLifecycleState.OPEN
    assert provider_b.get_run(run_id) is None


def test_inprocess_resume_without_owned_provider_fails_closed(tmp_path):
    from eval_runner.reference.inprocess_backend import InProcessExecutionBackend

    provider_b = LocalFileRunStore(tmp_path / "provider-b")
    set_active_run_storage_provider(provider_b)
    backend = InProcessExecutionBackend()
    backend._active_runs["unowned-run"] = {
        "status": "PAUSED",
        "scenario_data": {"id": "scenario-a"},
    }

    with pytest.raises(RuntimeError, match="Provider ownership is unavailable"):
        backend.resume("unowned-run")
    assert provider_b.get_run("unowned-run") is None


def test_execution_scoped_provider_affinity_ignores_global_resolver(tmp_path, monkeypatch):
    """Telemetry, HITL lifecycle, and certification preflight stay on injected provider A."""
    monkeypatch.setenv("RUN_LOG_MASTER", "false")
    monkeypatch.setenv("RUN_LOG_PER_RUN", "true")
    provider_a = LocalFileRunStore(tmp_path / "provider-a")
    provider_b = LocalFileRunStore(tmp_path / "provider-b")
    run_id = "provider-affinity-run"
    context = {"org_id": "acme", "tenant_id": "tenant-a"}
    set_active_run_storage_provider(provider_b)

    recorder = FlightRecorderPlugin(log_dir=tmp_path / "provider-a", run_store=provider_a)
    recorder.bind_run_provider(run_id, provider_a, context)
    recorder.handle_event(Event(CoreEvents.RUN_START, {"run_id": run_id, "scenario": "scenario-a"}))
    recorder.handle_event(Event("tool_call", {"run_id": run_id, "tool": "lookup"}))

    assert [event["event"] for event in provider_a.get_events(run_id, context=context)] == [
        CoreEvents.RUN_START,
        "tool_call",
    ]
    assert provider_b.get_events(run_id, context=context) == []

    transition_run_lifecycle(
        run_id,
        RunLifecycleState.PAUSED_FOR_APPROVAL,
        run_store=provider_a,
        context=context,
    )
    assert (
        get_run_lifecycle_state(run_id, run_store=provider_a, context=context)
        == RunLifecycleState.PAUSED_FOR_APPROVAL
    )
    with pytest.raises(Exception, match="PAUSED_FOR_APPROVAL"):
        assert_can_write_trace(run_id, run_store=provider_a, context=context)
    assert provider_b.get_run(run_id, context=context) is None

    # Certification must carry its supplied provider into sealed preflight
    # rather than materializing a path or reading the global provider.
    from eval_runner.services.certification import CertificationService

    observed: dict[str, object] = {}

    def lifecycle_probe(observed_run_id, *args, **kwargs):
        observed["run_id"] = observed_run_id
        observed["run_store"] = kwargs.get("run_store")
        observed["context"] = kwargs.get("context")
        return RunLifecycleState.SEALED

    monkeypatch.setattr("eval_runner.run_lifecycle.get_run_lifecycle_state", lifecycle_probe)

    with pytest.raises(ValueError, match="SealedRunCertificateInvalid"):
        CertificationService.execute_industrial_certification(
            run_id, run_store=provider_a, context=context
        )
    assert observed == {
        "run_id": run_id,
        "run_store": provider_a,
        "context": context,
    }


def test_default_runner_constructs_session_with_scoped_provider_affinity(tmp_path, monkeypatch):
    """DefaultRunner must reach SessionManager with the injected provider and scope."""
    from eval_runner.runner import DefaultRunner
    from eval_runner.session import SessionManager

    monkeypatch.setenv("RUN_LOG_MASTER", "false")
    monkeypatch.setenv("RUN_LOG_PER_RUN", "true")
    provider_a = LocalFileRunStore(tmp_path / "provider-a")
    provider_b = LocalFileRunStore(tmp_path / "provider-b")
    set_active_run_storage_provider(provider_b)
    run_id = "runner-session-provider-affinity"
    context = {
        "org_id": "acme",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "active_environment": "test",
    }
    recorder = FlightRecorderPlugin(log_dir=tmp_path / "provider-a", run_store=provider_a)
    observed: dict[str, object] = {}
    original_init = SessionManager.__init__

    class StopAfterSessionConstruction(Exception):
        pass

    def recording_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        observed["run_store"] = self.run_store
        observed["context"] = self.metadata.get("runtime_context")
        observed["recorder_binding"] = recorder._provider_for_run(self.run_id)
        raise StopAfterSessionConstruction()

    monkeypatch.setattr(SessionManager, "__init__", recording_init)

    async def exercise_runner():
        runner = DefaultRunner(run_store=provider_a)
        with pytest.raises(StopAfterSessionConstruction):
            await runner.run(
                {"id": "scoped-session", "workflow": {"nodes": [], "edges": []}},
                run_id=run_id,
                metadata={"runtime_context": context},
            )

    import asyncio

    asyncio.run(exercise_runner())
    assert observed["run_store"] is provider_a
    assert observed["context"] == context
    assert observed["recorder_binding"] == (provider_a, context)
    assert provider_b.get_run(run_id, context=context) is None


def test_recorder_provider_binding_preserves_context_until_certification_releases_it(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("RUN_LOG_MASTER", "false")
    monkeypatch.setenv("RUN_LOG_PER_RUN", "true")
    provider = LocalFileRunStore(tmp_path)
    run_id = "terminal-provider-binding"
    context = {"org_id": "acme", "tenant_id": "tenant-a"}
    provider.create_run(run_id, "scenario", context=context)
    recorder = FlightRecorderPlugin(log_dir=tmp_path, run_store=provider)

    recorder.bind_run_provider(run_id, provider, context)
    recorder.bind_run_provider(run_id, provider, None)
    assert recorder._provider_for_run(run_id) == (provider, context)

    monkeypatch.setattr(
        "eval_runner.run_lifecycle.get_run_lifecycle_state",
        lambda *_args, **_kwargs: RunLifecycleState.SEALED,
    )
    recorder.finalize_run(run_id)
    # Recorder finalization cannot own the irreversible seal.  Certification
    # releases the binding only after its provider commit succeeds.
    assert recorder._provider_for_run(run_id) == (provider, context)


def test_certification_release_does_not_drop_another_provider_binding(tmp_path):
    provider_a = LocalFileRunStore(tmp_path / "provider-a")
    provider_b = LocalFileRunStore(tmp_path / "provider-b")
    recorder = FlightRecorderPlugin(log_dir=tmp_path / "provider-a", run_store=provider_a)
    recorder.bind_run_provider("run-a", provider_a, {"org_id": "a"})
    recorder.bind_run_provider("run-b", provider_b, {"org_id": "b"})

    FlightRecorderPlugin.release_active_recorder("run-a", provider_a)

    assert "run-a" not in recorder._run_providers
    assert recorder._provider_for_run("run-b") == (provider_b, {"org_id": "b"})


def test_scenario_name_parsing_helpers():
    """Verify parsing scenario identifiers from composite run identifiers."""
    from eval_runner.reference.local_run_store import _parse_scenario_from_run_id

    assert _parse_scenario_from_run_id("run-scenario_one-20261016") == "scenario_one"
    assert _parse_scenario_from_run_id("run-simple_scenario") == "simple_scenario"
    assert _parse_scenario_from_run_id("custom_benchmark_id") == "custom_benchmark_id"


def test_local_file_run_store_vault_and_manifest_edge_cases(tmp_path):
    """Verify vault isolation, corrupt manifest handling, and scenario/timestamp fallbacks."""
    import json

    store = LocalFileRunStore(tmp_path)

    # 1. Path traversal security checks
    assert store.get_run("../escaped_run") is None
    assert store.get_manifest("../escaped_run") is None
    assert store.get_events("../escaped_run") == []
    assert store.delete_run("../escaped_run") is False

    # 2. Corrupt manifest handling fails closed for manifest read and marks run invalid
    corrupt_vault = tmp_path / "run-corrupt"
    corrupt_vault.mkdir(parents=True)
    (corrupt_vault / "run_manifest.json").write_text("not_valid_json", encoding="utf-8")
    assert store.get_manifest("run-corrupt") is None
    corrupted_run = store.get_run("run-corrupt")
    assert corrupted_run is not None
    assert corrupted_run["manifest"] == {}
    assert corrupted_run["status"] == "INVALID"

    # 3. Vault without record file but with valid manifest
    manifest_only_vault = tmp_path / "run-manifest-only"
    manifest_only_vault.mkdir(parents=True)
    (manifest_only_vault / "run_manifest.json").write_text(
        json.dumps(
            {
                "scenario_id": "scen-from-manifest",
                "timestamp": "2026-10-16T00:00:00Z",
                "context": {"tenant_id": "alpha"},
            }
        ),
        encoding="utf-8",
    )
    run_info = store.get_run("run-manifest-only", context={"tenant_id": "alpha"})
    assert run_info is not None
    assert run_info["scenario"] == "scen-from-manifest"
    assert run_info["timestamp"] == "2026-10-16T00:00:00Z"

    # Context mismatch on manifest-only vault returns None
    assert store.get_run("run-manifest-only", context={"tenant_id": "beta"}) is None

    # 4. Vault without record and without manifest, relying on trace.jsonl
    trace_only_vault = tmp_path / "run-trace-only"
    trace_only_vault.mkdir(parents=True)
    assert store.get_run("run-trace-only") is None

    # Empty trace file
    trace_file = trace_only_vault / "run.jsonl"
    trace_file.write_text("\n", encoding="utf-8")
    assert store.get_run("run-trace-only") is None

    # Invalid JSON in trace file
    trace_file.write_text("invalid json\n", encoding="utf-8")
    assert store.get_run("run-trace-only") is None

    # Valid event in trace file
    trace_event = {
        "event": "run_start",
        "scenario": "scen-from-trace",
        "timestamp": "2026-10-16T01:00:00Z",
    }
    trace_file.write_text(json.dumps(trace_event) + "\n", encoding="utf-8")
    trace_run_info = store.get_run("run-trace-only")
    assert trace_run_info is not None
    assert trace_run_info["scenario"] == "scen-from-trace"
    assert trace_run_info["timestamp"] == "2026-10-16T01:00:00Z"

    # 5. Manifest metadata alternative keys
    alt_meta_vault = tmp_path / "run-alt-meta-123"
    alt_meta_vault.mkdir(parents=True)
    (alt_meta_vault / "run_manifest.json").write_text(
        json.dumps(
            {
                "metadata": {"scenario": "scen-alt-meta"},
                "created_at": "2026-10-16T02:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    alt_info = store.get_run("run-alt-meta-123")
    assert alt_info is not None
    assert alt_info["scenario"] == "scen-alt-meta"
    assert alt_info["created_at"] == "2026-10-16T02:00:00Z"


def test_local_file_run_store_provisional_index_and_fragments(tmp_path):
    """Verify provisional index resolution, fragment parsing, and list_runs aggregation."""
    store = LocalFileRunStore(tmp_path)

    # 1. Provisional index file: .index/<run_id>.json
    index_dir = tmp_path / ".index"
    index_dir.mkdir(parents=True)
    (index_dir / "run-provisional.json").write_text(
        json.dumps(
            {
                "run_id": "run-provisional",
                "scenario_id": "scen-prov",
                "status": "QUEUED",
                "created_at": "2026-10-16T03:00:00Z",
                "context": {"org_id": "eng"},
            }
        ),
        encoding="utf-8",
    )
    prov_run = store.get_run("run-provisional", context={"org_id": "eng"})
    assert prov_run is not None
    assert prov_run["status"] == "QUEUED"
    assert prov_run["provisional"] is True
    # Context mismatch returns None
    assert store.get_run("run-provisional", context={"org_id": "sales"}) is None

    # 2. Fragment log file: <run_id>.jsonl
    frag_data = {
        "run_id": "run-fragment-test-1",
        "scenario": "scen-frag",
        "timestamp": "2026-10-16T04:00:00Z",
    }
    (tmp_path / "run-fragment-test-1.jsonl").write_text(
        json.dumps(frag_data) + "\n",
        encoding="utf-8",
    )
    frag_run = store.get_run("run-fragment-test-1")
    assert frag_run is not None
    assert frag_run["scenario"] == "scen-frag"
    assert frag_run["_fragment_path"] == "run-fragment-test-1.jsonl"

    # Fragment with context check
    (tmp_path / "run-frag-ctx.jsonl").write_text(
        json.dumps({"run_id": "run-frag-ctx", "context": {"active_environment": "prod"}}) + "\n",
        encoding="utf-8",
    )
    assert store.get_run("run-frag-ctx", context={"active_environment": "dev"}) is None

    # 3. list_runs includes fragments, provisional indices, and regular vaults
    store.create_run("run-regular", "scen-reg")
    all_runs = store.list_runs(limit=50)
    run_ids = {r["run_id"] for r in all_runs}
    assert "run-provisional" in run_ids
    assert "run-fragment-test-1" in run_ids
    assert "run-regular" in run_ids


def test_local_file_run_store_lifecycle_events_and_manifest_revisions(tmp_path):
    """Verify events appending, streaming, status transitions, revisions, and deletion."""
    store = LocalFileRunStore(tmp_path)

    # 1. Append zero events returns 0
    assert store.append_events("run-ev-1", []) == 0

    # 2. Append events creates run and writes JSON lines
    store.create_run("run-ev-1", "scen-ev", context={"org_id": "c1"})
    appended = store.append_events("run-ev-1", [{"step": 1}, {"step": 2}])
    assert appended == 2

    # Events offset and limit
    events = store.get_events("run-ev-1", offset=1, limit=1)
    assert len(events) == 1
    assert events[0]["step"] == 2

    # Context mismatch on get_events returns empty list
    assert store.get_events("run-ev-1", context={"org_id": "wrong"}) == []

    # 3. Manifest publication revisions
    manifest_v1 = {"version": 1, "status": "PENDING"}
    path1 = store.save_run_manifest("run-ev-1", manifest_v1)

    # Idempotent republication returns same path
    path1_repeat = store.save_run_manifest("run-ev-1", manifest_v1)
    assert path1 == path1_repeat
    assert store.list_manifest_revisions("run-ev-1") == []

    # Divergent pre-certification republication generates revision
    manifest_v2 = {"version": 2, "status": "IN_PROGRESS"}
    rev_path = store.save_run_manifest("run-ev-1", manifest_v2)
    assert "manifest_revisions" in rev_path
    revisions = store.list_manifest_revisions("run-ev-1")
    assert len(revisions) == 1

    # 4. update_run_status with details and context mismatch
    assert (
        store.update_run_status(
            "run-ev-1", "RUNNING", details={"progress": 50}, context={"org_id": "wrong"}
        )
        is False
    )
    assert (
        store.update_run_status("run-ev-1", "PAUSED_FOR_APPROVAL", details={"approver": "sec_lead"})
        is True
    )

    # Appending events while paused raises RunManifestImmutableError
    with pytest.raises(RunManifestImmutableError):
        store.append_events("run-ev-1", [{"step": 3}])

    # 5. Seal run and verify immutability
    store.update_run_status("run-ev-1", "FINALIZING")
    with pytest.raises(RunManifestImmutableError):
        store.append_events("run-ev-1", [{"step": 4}])

    store.update_run_status("run-ev-1", "SEALED")
    with pytest.raises(RunManifestImmutableError):
        store.save_run_manifest("run-ev-1", {"version": 3})

    with pytest.raises(RunManifestImmutableError):
        store.delete_run("run-ev-1")

    # 6. Unsealed run deletion
    store.create_run("run-to-delete", "scen-del")
    assert store.delete_run("run-to-delete") is True
    assert store.get_run("run-to-delete") is None
    assert store.delete_run("run-to-delete") is False


def test_local_file_run_store_search_and_edge_branches(tmp_path):
    """Verify search_runs filters, manifest context mismatch, rewrite, and traversal."""
    store = LocalFileRunStore(tmp_path)

    store.create_run("run-search-1", "alpha_scenario", context={"org_id": "org-a"})
    store.update_run_status("run-search-1", "PASSED")
    store.create_run("run-search-2", "beta_scenario", context={"org_id": "org-b"})
    store.update_run_status("run-search-2", "FAILED")

    # 1. Search with query matching and non-matching
    assert len(store.search_runs("alpha")) == 1
    assert len(store.search_runs("nonexistent_needle")) == 0

    # 2. Search with filters
    assert len(store.search_runs(filters={"status": "PASSED"})) == 1
    assert len(store.search_runs(filters={"status": "UNKNOWN_STATUS"})) == 0

    # 3. get_manifest with context mismatch
    store.save_run_manifest("run-search-1", {"status": "PASSED", "context": {"org_id": "org-a"}})
    assert store.get_manifest("run-search-1", context={"org_id": "wrong-org"}) is None

    # 4. update_run_status on non-existent run auto-creates
    assert store.update_run_status("run-auto-created", "OPEN") is True
    assert store.get_run("run-auto-created") is not None

    # 5. list_manifest_revisions with path traversal
    assert store.list_manifest_revisions("../escaped_id") == []

    # 6. save_run_manifest when existing manifest is corrupted
    corrupt_vault = tmp_path / "run-manifest-corrupt"
    corrupt_vault.mkdir(parents=True)
    (corrupt_vault / "run_manifest.json").write_text("corrupt json", encoding="utf-8")
    new_path = store.save_run_manifest("run-manifest-corrupt", {"version": "fresh"})
    assert "manifest_revisions" in new_path

    # 7. Non-existent log_dir
    non_existent_store = LocalFileRunStore(tmp_path / "never_created_dir")
    import shutil

    shutil.rmtree(tmp_path / "never_created_dir", ignore_errors=True)
    assert non_existent_store.list_runs() == []


def test_local_file_run_store_lifecycle_marker_and_master_log_branches(tmp_path, monkeypatch):
    from eval_runner import config

    # log_dir property resolution with string config and Path config
    monkeypatch.setattr(config, "RUN_LOG_DIR", str(tmp_path / "custom_str_dir"))
    str_store = LocalFileRunStore()
    assert str_store.log_dir == (tmp_path / "custom_str_dir").resolve()

    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "custom_path_dir")
    path_store = LocalFileRunStore()
    assert path_store.log_dir == (tmp_path / "custom_path_dir").resolve()

    store = LocalFileRunStore(tmp_path)

    # create_run when record already exists
    first_rec = store.create_run("run-exists", "scenario-1")
    second_rec = store.create_run("run-exists", "scenario-1")
    assert first_rec == second_rec

    # get_run with .run_lifecycle marker
    marker_vault = tmp_path / "run-marker"
    marker_vault.mkdir(parents=True)
    (marker_vault / ".run_lifecycle").write_text(
        json.dumps({"status": "CUSTOM_STATUS"}), encoding="utf-8"
    )
    assert store.get_run("run-marker")["status"] == "CUSTOM_STATUS"

    # Raw non-json marker
    raw_vault = tmp_path / "run-raw-marker"
    raw_vault.mkdir(parents=True)
    (raw_vault / ".run_lifecycle").write_text("RAW_RUNNING", encoding="utf-8")
    assert store.get_run("run-raw-marker")["status"] == "RAW_RUNNING"

    # Corrupt/unreadable marker raising OSError
    oserr_vault = tmp_path / "run-oserr-marker"
    oserr_vault.mkdir(parents=True)
    (oserr_vault / ".run_lifecycle").mkdir()
    res_oserr = store.get_run("run-oserr-marker")
    assert res_oserr is not None
    assert res_oserr["status"] == "INVALID"

    # Marker status overriding existing record status
    override_vault = tmp_path / "run-override"
    override_vault.mkdir(parents=True)
    (override_vault / "run_record.json").write_text(
        json.dumps({"run_id": "run-override", "status": "OPEN", "scenario": "scen"}),
        encoding="utf-8",
    )
    (override_vault / ".run_lifecycle").write_text("RUNNING", encoding="utf-8")
    assert store.get_run("run-override")["status"] == "RUNNING"

    # Context denies record or manifest
    context_vault = tmp_path / "run-context-denied"
    context_vault.mkdir(parents=True)
    (context_vault / "run_record.json").write_text(
        json.dumps({"run_id": "run-context-denied", "context": {"org_id": "corp_a"}}),
        encoding="utf-8",
    )
    assert store.get_run("run-context-denied", context={"org_id": "corp_b"}) is None

    # Sealed marker without record.json
    sealed_vault = tmp_path / "run-sealed-only"
    sealed_vault.mkdir(parents=True)
    (sealed_vault / ".sealed").touch()
    assert store.get_run("run-sealed-only")["status"] == "SEALED"

    # append_events rejecting PAUSED_FOR_APPROVAL
    store.create_run("run-paused", "scenario-1")
    store.update_run_status("run-paused", "PAUSED_FOR_APPROVAL")
    with pytest.raises(RunManifestImmutableError):
        store.append_events("run-paused", [{"event": "test"}])

    # get_events with context denial
    assert store.get_events("run-context-denied", context={"org_id": "corp_b"}) == []

    # list_runs reading master log
    master_log = tmp_path / "run.jsonl"
    master_log.write_text(
        json.dumps(
            {
                "run_id": "run-from-master",
                "scenario": "master-scen",
                "status": "OPEN",
                "timestamp": "2026-10-16T12:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    runs = store.list_runs()
    assert any(r["run_id"] == "run-from-master" for r in runs)

    # get_manifest with context denial
    assert store.get_manifest("run-context-denied", context={"org_id": "corp_b"}) is None

    # Trace open OSError fallback in get_events
    oserr_events_vault = tmp_path / "run-events-oserr"
    oserr_events_vault.mkdir(parents=True)
    (oserr_events_vault / "run.jsonl").mkdir()
    assert store.get_events("run-events-oserr") == []

    # Sealed vault append_events raises RunManifestImmutableError
    store.create_run("run-to-seal", "scenario-1")
    store.update_run_status("run-to-seal", "SEALED")
    with pytest.raises(RunManifestImmutableError):
        store.append_events("run-to-seal", [{"event": "test"}])

    # Vault with empty trace returns None
    empty_trace_vault = tmp_path / "run-empty-trace"
    empty_trace_vault.mkdir(parents=True)
    (empty_trace_vault / "run.jsonl").write_text("", encoding="utf-8")
    assert store.get_run("run-empty-trace") is None

    # Context denies manifest_data when record context is allowed
    manifest_diff_vault = tmp_path / "run-manifest-diff"
    manifest_diff_vault.mkdir(parents=True)
    (manifest_diff_vault / "run_record.json").write_text(
        json.dumps({"run_id": "run-manifest-diff", "context": {"org_id": "corp_x"}}),
        encoding="utf-8",
    )
    (manifest_diff_vault / "run_manifest.json").write_text(
        json.dumps({"context": {"org_id": "corp_y"}}), encoding="utf-8"
    )
    assert store.get_run("run-manifest-diff", context={"org_id": "corp_x"}) is None

    # append_events on non-existent run auto-creates run record
    assert store.append_events("run-auto-append", [{"event": "ev1"}]) == 1
    assert store.get_run("run-auto-append") is not None

    # append_events on sealed vault raises RunManifestImmutableError
    with pytest.raises(RunManifestImmutableError):
        store.append_events("run-sealed-only", [{"event": "ev2"}])


def test_local_run_store_rejects_corrupted_jsonl(tmp_path: Path):
    """Corrupted lines in JSONL must raise ValueError under strict validation."""
    store = LocalFileRunStore(tmp_path)
    run_id = "run-corrupted-trace"
    run_dir = store._get_run_vault(run_id, create=True)
    trace_file = run_dir / "run.jsonl"

    valid_record = json.dumps({"event": "step_1", "seq": 1})
    trace_file.write_text(f"{valid_record}\n{{malformed_json_not_valid\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        store.get_events(run_id)
    assert "MalformedTraceRecord" in str(exc_info.value)
