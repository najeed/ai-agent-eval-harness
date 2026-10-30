"""An ambient run store never grants a recorder ownership of an arbitrary run."""

import json

import pytest

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


def test_unsigned_diagnostic_trace_closure_is_persisted_without_claiming_a_signature(tmp_path):
    store = LocalFileRunStore(tmp_path / "runs")
    store.create_run("diagnostic", "scenario")
    artifacts = LocalFileArtifactStore(tmp_path / "artifacts")
    recorder = FlightRecorderPlugin(
        run_store=store, artifact_store=artifacts, signing_backend=NullSigningBackend()
    )

    recorder.finalize_run("diagnostic")

    seal = json.loads(artifacts.get_artifact("diagnostic", "trace_seal.json"))
    assert seal["status"] == "finalized"
    assert seal["run_id"] == "diagnostic"
    assert "signature" not in seal and "signer_identity" not in seal
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
def test_optional_key_identifier_is_emitted_only_when_nonempty(tmp_path, key_id):
    store = LocalFileRunStore(tmp_path / "runs")
    store.create_run("key-hint", "scenario")
    artifacts = LocalFileArtifactStore(tmp_path / "artifacts")
    recorder = FlightRecorderPlugin(
        run_store=store, artifact_store=artifacts, signing_backend=DiagnosticSigner(key_id)
    )

    recorder.finalize_run("key-hint")

    seal = json.loads(artifacts.get_artifact("key-hint", "trace_seal.json"))
    assert seal["signature"] == "fixture-signature"
    assert ("key_id" in seal) is bool(key_id)
    if key_id:
        assert seal["key_id"] == key_id
    assert store.get_run("key-hint")["lifecycle"] == "FINALIZING"
