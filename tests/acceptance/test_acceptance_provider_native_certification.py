"""Release-gate acceptance tests for provider-native certification integrity."""

from __future__ import annotations

import threading
import uuid

import pytest

from agentv_runtime.evidence_graph import build_evidence_graph_from_events
from agentv_runtime.finalization import EvaluatorFinalizationRecord
from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash
from eval_runner import config
from eval_runner.console.app import create_app
from eval_runner.console.routes.evidence import build_verification_package
from eval_runner.identity import IdentityService
from eval_runner.reference.local_run_store import LocalFileRunStore, RunManifestImmutableError
from eval_runner.run_lifecycle import RunLifecycleState, get_run_lifecycle_state
from eval_runner.services.certification import execute_industrial_certification


@pytest.fixture
def provider_native_acceptance_env(isolated_acceptance_env, monkeypatch):
    """A real scoped provider and trust root shared with the CLI subprocess."""
    env = isolated_acceptance_env
    monkeypatch.setattr(config, "RUN_LOG_DIR", env["runs_dir"])
    monkeypatch.setattr(config, "REPORTS_DIR", env["reports_dir"])
    monkeypatch.setattr(config, "TRUST_ROOT", env["trust_dir"])
    monkeypatch.setattr(config, "PROJECT_ROOT", env["tmp_path"])
    # ``isolated_acceptance_env`` already provisions the system signer and
    # exports its public key to the CLI subprocess.  Do not replace it here.
    IdentityService._provision_local_identity("eval_kernel")
    env["store"] = LocalFileRunStore(env["runs_dir"])
    return env


def _seed_provider_run(store: LocalFileRunStore, run_id: str) -> dict:
    """Create a complete live finalization through provider methods only."""
    scenario = {
        "id": f"acceptance-{run_id}",
        "version": "1.0.0",
        "required_oracles": ["oracle-1"],
    }
    scenario_hash = compute_scenario_hash(scenario)
    execution_manifest = ExecutionManifest(
        manifest_id=f"manifest-{run_id}",
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scenario_hash,
        metadata={"required_oracle_ids": ["oracle-1"]},
        runtime_config={"execution_mode": "live"},
    )
    store.create_run(run_id, scenario["id"])
    events = [
        {"event": "run_start", "_seq": 1, "run_id": run_id, "execution_mode": "live"},
        {
            "event": "oracle_result",
            "resolver": "fixture",
            "_seq": 2,
            "run_id": run_id,
            "oracle_id": "oracle-1",
            "passed": True,
            "outcome": "PASS",
        },
        {
            "event": "session_decision",
            "_seq": 3,
            "run_id": run_id,
            "decision": "PASS",
            "score": 1.0,
        },
    ]
    store.append_events(run_id, events)
    trace_lines = store.get_trace_bytes(run_id).decode("utf-8").splitlines()
    graph = build_evidence_graph_from_events(
        list(zip(events, trace_lines, strict=True)), required_oracle_ids=["oracle-1"]
    )
    finalization = EvaluatorFinalizationRecord(
        finalization_id=f"finalization-{run_id}",
        run_id=run_id,
        scenario_id=scenario["id"],
        scenario_version=scenario["version"],
        scenario_hash=scenario_hash,
        execution_manifest_hash=execution_manifest.compute_manifest_hash(),
        evaluator_config_hash="sha3_256:acceptance-evaluator-config",
        evaluator_identity="eval_kernel",
        required_oracle_ids=["oracle-1"],
        evidence_root_hash=graph["evidence_root_hash"],
        outcome="pass",
        score=1.0,
        terminal_seq=3,
        finalized_at="2026-10-27T00:00:00Z",
    ).sign()
    store.append_events(
        run_id, [{"event": "evaluator_finalization", "_seq": 4, "data": finalization.to_dict()}]
    )
    store.save_run_manifest(
        run_id,
        {
            "run_id": run_id,
            "scenario_data": scenario,
            "execution_manifest": execution_manifest.to_dict(),
        },
    )
    return scenario


@pytest.mark.acceptance
@pytest.mark.acceptance_release
def test_acceptance_manipulated_or_stale_provider_evidence_cannot_be_certified(
    provider_native_acceptance_env, monkeypatch
):
    """A stale event view or post-finalization trace mutation fails closed."""
    store = provider_native_acceptance_env["store"]
    run_id = f"at-provider-stale-{uuid.uuid4().hex[:8]}"
    scenario = _seed_provider_run(store, run_id)
    stale_events = store.get_events(run_id, offset=0, limit=1000)
    store.append_events(run_id, [{"event": "forged_post_finalization", "_seq": 5}])
    monkeypatch.setattr(store, "get_events", lambda *_args, **_kwargs: stale_events)

    with pytest.raises(ValueError, match="ProviderEventByteDivergence"):
        execute_industrial_certification(run_id, run_store=store, scenario_data=scenario)

    assert get_run_lifecycle_state(run_id, run_store=store) is RunLifecycleState.OPEN
    assert not (store.get_manifest(run_id) or {}).get("certification")


@pytest.mark.acceptance
@pytest.mark.acceptance_release
def test_acceptance_export_root_equals_the_sealed_certification_root(
    provider_native_acceptance_env,
):
    """The package graph is root-equivalent to the exact sealed evidence graph."""
    store = provider_native_acceptance_env["store"]
    run_id = f"at-provider-root-{uuid.uuid4().hex[:8]}"
    scenario = _seed_provider_run(store, run_id)
    execute_industrial_certification(run_id, run_store=store, scenario_data=scenario)

    manifest = store.get_manifest(run_id)
    package = build_verification_package(run_id, run_store=store)
    assert manifest and package
    assert package["verdict"]["verified_outcome"] == "VERIFIED"
    assert package["evidence_graph"]["evidence_root_hash"] == manifest["evidence_root_hash"]
    assert (
        package["evidence_graph"]["evidence_root_hash"]
        == manifest["verification_package"]["evidence_root_hash"]
    )


@pytest.mark.acceptance
@pytest.mark.acceptance_release
def test_acceptance_corrupt_provider_bytes_never_yield_a_usable_certificate(
    provider_native_acceptance_env, monkeypatch
):
    """The console package is invalid, empty, and non-certifying on corrupt bytes."""
    store = provider_native_acceptance_env["store"]
    run_id = f"at-provider-corrupt-{uuid.uuid4().hex[:8]}"
    scenario = _seed_provider_run(store, run_id)
    execute_industrial_certification(run_id, run_store=store, scenario_data=scenario)
    exact = store.get_trace_bytes(run_id)
    monkeypatch.setattr(store, "get_trace_bytes", lambda *_args, **_kwargs: exact + b"{bad-json}\n")

    package = build_verification_package(run_id, run_store=store)
    assert package is not None
    assert package["verdict"]["verified_outcome"] == "EVIDENCE_INVALID"
    assert package["evidence_chain_valid"] is False
    assert package["verdict"]["assertions"] == []
    assert package["evidence_graph"]["nodes"] == []


@pytest.mark.acceptance
@pytest.mark.acceptance_release
def test_acceptance_append_and_competing_certification_are_fenced(
    provider_native_acceptance_env, monkeypatch
):
    """A finalizing run rejects writes and only one transaction commits."""
    from eval_runner.verifier import TraceVerifier

    store = provider_native_acceptance_env["store"]
    run_id = f"at-provider-race-{uuid.uuid4().hex[:8]}"
    scenario = _seed_provider_run(store, run_id)
    entered_signing = threading.Event()
    release_signing = threading.Event()
    original_sign = TraceVerifier.sign_trace_bytes
    commits: list[str] = []
    original_commit = store.commit_certification

    def blocking_sign(*args, **kwargs):
        entered_signing.set()
        assert release_signing.wait(timeout=5), "certification release was not signaled"
        return original_sign(*args, **kwargs)

    def count_commit(*args, **kwargs):
        commits.append("commit")
        return original_commit(*args, **kwargs)

    monkeypatch.setattr(TraceVerifier, "sign_trace_bytes", blocking_sign)
    monkeypatch.setattr(store, "commit_certification", count_commit)
    results: list[dict] = []
    failures: list[BaseException] = []

    def certify() -> None:
        try:
            results.append(
                execute_industrial_certification(run_id, run_store=store, scenario_data=scenario)
            )
        except BaseException as exc:  # assertion below retains unexpected failure details
            failures.append(exc)

    first = threading.Thread(target=certify, daemon=True)
    second = threading.Thread(target=certify, daemon=True)
    first.start()
    assert entered_signing.wait(timeout=5), "first certification did not acquire the lease"
    with pytest.raises(RunManifestImmutableError):
        store.append_events(run_id, [{"event": "concurrent_write", "_seq": 5}])
    second.start()
    release_signing.set()
    first.join(timeout=10)
    second.join(timeout=10)

    assert not first.is_alive() and not second.is_alive()
    # A competing caller may receive a lifecycle/lease conflict after the
    # winning transaction seals.  It must never publish a second certificate.
    assert all(
        "IllegalLifecycleTransition" in str(failure) or "CertificationLockConflict" in str(failure)
        for failure in failures
    )
    assert len(commits) == 1
    assert results and all(
        result["manifest"]["trace_hash"] == results[0]["manifest"]["trace_hash"]
        for result in results
    )
    assert get_run_lifecycle_state(run_id, run_store=store) is RunLifecycleState.SEALED


@pytest.mark.acceptance
@pytest.mark.acceptance_release
def test_acceptance_gui_api_cli_and_export_share_the_authoritative_verdict(
    provider_native_acceptance_env,
):
    """The Console API, package export, and CLI all report one sealed verdict."""
    env = provider_native_acceptance_env
    store = env["store"]
    run_id = f"at-provider-parity-{uuid.uuid4().hex[:8]}"
    scenario = _seed_provider_run(store, run_id)
    execute_industrial_certification(run_id, run_store=store, scenario_data=scenario)

    app = create_app(run_store=store)
    app.config["TESTING"] = True
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = {"id": "acceptance-admin", "permissions": ["*"]}
        api = client.get(f"/api/v1/runs/{run_id}/verify")
        gui_export = client.get(f"/api/v1/evidence/packages/{run_id}")

    assert api.status_code == 200
    assert gui_export.status_code == 200
    assert api.get_json()["verification_status"] == "VERIFIED"
    assert gui_export.get_json()["verdict"]["verified_outcome"] == "VERIFIED"
    assert gui_export.get_json()["evidence_chain_valid"] is True

    cli = env["runner"].verify(run_id=run_id)
    assert cli.exit_code == 0, cli.stderr
    assert "VERIFIED" in cli.stdout
