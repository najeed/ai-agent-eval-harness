"""An ambient run store never grants a recorder ownership of an arbitrary run."""

import pytest

from eval_runner.events import Event
from eval_runner.flight_recorder import FlightRecorderPlugin
from eval_runner.interfaces.signing import SigningBackend
from eval_runner.reference.local_artifact import LocalFileArtifactStore
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.runtime_services import NullSigningBackend


def test_recorder_requires_explicit_run_binding_despite_an_ambient_provider(tmp_path, monkeypatch):
    store = LocalFileRunStore(tmp_path / "runs")
    monkeypatch.setattr("eval_runner.runtime_services.resolve_run_store", lambda: store)
    recorder = FlightRecorderPlugin(
        artifact_store=LocalFileArtifactStore(tmp_path / "artifacts"),
        signing_backend=NullSigningBackend(),
    )

    with pytest.raises(RuntimeError, match="RunStorageProviderBindingRequired"):
        recorder._provider_for_run("foreign")

    context = {"tenant_id": "owner"}
    recorder.bind_run_provider("owned", store, context)
    assert recorder._provider_for_run("owned") == (store, context)


@pytest.mark.parametrize("run_id", ["", "unknown"])
def test_freezing_an_unassigned_identity_preserves_its_public_recorder_state(tmp_path, run_id):
    recorder = FlightRecorderPlugin(run_store=LocalFileRunStore(tmp_path / "runs"))
    before = recorder.get_run_state(run_id)

    recorder.freeze_run(run_id)

    assert recorder.get_run_state(run_id) == before


def test_finalizing_unknown_identity_never_publishes_a_trace_seal(tmp_path):
    artifacts = LocalFileArtifactStore(tmp_path / "artifacts")
    recorder = FlightRecorderPlugin(
        run_store=LocalFileRunStore(tmp_path / "runs"),
        artifact_store=artifacts,
        signing_backend=NullSigningBackend(),
    )

    recorder.finalize_run("unknown")

    assert artifacts.get_artifact("unknown", "trace_seal.json") is None


def test_diagnostic_trace_closure_never_publishes_a_certificate_seal(tmp_path):
    store = LocalFileRunStore(tmp_path / "runs")
    store.create_run("diagnostic", "scenario")
    artifacts = LocalFileArtifactStore(tmp_path / "artifacts")
    recorder = FlightRecorderPlugin(
        run_store=store, artifact_store=artifacts, signing_backend=NullSigningBackend()
    )

    recorder.finalize_run("diagnostic")

    assert artifacts.get_artifact("diagnostic", "trace_seal.json") is None
    assert store.get_run("diagnostic")["lifecycle"] == "FINALIZING"


class DiagnosticSigner(SigningBackend):
    identity = "diagnostic-fixture"

    def __init__(self, key_id):
        self.key_id = key_id

    def sign_payload(self, payload, key_identifier=None, **kwargs):
        return "fixture-signature"

    def verify_signature(self, payload, signature, public_key_identifier=None, **kwargs):
        return False


@pytest.mark.parametrize("key_id", [None, "", "opaque-provider-key"])
def test_recorder_signer_configuration_cannot_publish_a_premature_seal(tmp_path, key_id):
    store = LocalFileRunStore(tmp_path / "runs")
    store.create_run("key-hint", "scenario")
    artifacts = LocalFileArtifactStore(tmp_path / "artifacts")
    recorder = FlightRecorderPlugin(
        run_store=store, artifact_store=artifacts, signing_backend=DiagnosticSigner(key_id)
    )

    recorder.finalize_run("key-hint")

    assert artifacts.get_artifact("key-hint", "trace_seal.json") is None
    assert store.get_run("key-hint")["lifecycle"] == "FINALIZING"


def test_handle_event_failure_marks_custom_bound_provider_not_default(tmp_path):
    class FailingStore:
        def __init__(self):
            self.status_updates = []

        def get_run(self, run_id, context=None):
            return {"run_id": run_id, "status": "RUNNING"}

        def get_events(self, run_id, offset=0, limit=1000, context=None):
            return []

        def append_events(self, run_id, events, context=None):
            raise OSError("I/O failure during append")

        def update_run_status(self, run_id, status, details=None, context=None):
            self.status_updates.append((run_id, status, details, context))
            return True

    class DefaultStore:
        def __init__(self):
            self.status_updates = []

        def get_run(self, run_id, context=None):
            return {"run_id": run_id, "status": "RUNNING"}

        def get_events(self, run_id, offset=0, limit=1000, context=None):
            return []

        def append_events(self, run_id, events, context=None):
            return len(events)

        def update_run_status(self, run_id, status, details=None, context=None):
            self.status_updates.append((run_id, status, details, context))
            return True

    default_store = DefaultStore()
    custom_store = FailingStore()
    recorder = FlightRecorderPlugin(
        run_store=default_store,
        artifact_store=LocalFileArtifactStore(tmp_path / "artifacts"),
        signing_backend=NullSigningBackend(),
    )
    custom_context = {"tenant_id": "tenant-corp"}
    recorder.bind_run_provider("custom-run", custom_store, custom_context)

    with pytest.raises(
        RuntimeError,
        match="TracePersistenceError: Failed to persist telemetry event for run 'custom-run'",
    ):
        recorder.handle_event(Event("step", {"run_id": "custom-run"}))

    assert len(custom_store.status_updates) == 1
    assert custom_store.status_updates[0][0] == "custom-run"
    assert custom_store.status_updates[0][1] == "CERTIFICATION_FAILED"
    assert custom_store.status_updates[0][3] == custom_context
    assert len(default_store.status_updates) == 0
