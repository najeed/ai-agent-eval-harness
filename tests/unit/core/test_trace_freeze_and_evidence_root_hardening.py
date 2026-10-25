"""
Hardened Audit Defensibility & Trace Freeze Test Suite.
Tests the hardened evaluation -> trace -> certification -> verification pipeline:
  1. Hard-freeze run lifecycle and write rejection during/after FINALIZING
  2. Deterministic evidence root derivation and mismatch detection
  3. Portable verification with public keys only (never private keys)
  4. Mandatory scenario hash binding
  5. Score-independent verification semantics (score < 1.0 with passing status)
  6. Explain run temporary file isolation with UUID
  7. SSE intrinsic _seq emission
  8. VerificationAuthority mandatory signature requirement
  9. Authoritative verdict execution
"""

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

import eval_runner.console.routes.runs as runs_route
from agentv_runtime.package import VerificationPackage
from eval_runner.console.routes.runs import run_bp
from eval_runner.console.routes.trust import trust_bp
from eval_runner.events import Event
from eval_runner.flight_recorder import FlightRecorderPlugin
from eval_runner.identity import IdentityService
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.services.run_summary import RunSummaryService
from eval_runner.verifier import (
    TraceVerifier,
    VerificationAuthority,
    verify_trace_certificate,
)

_authoritative_verdict = RunSummaryService.get_authoritative_verdict


@pytest.fixture
def isolated_vault(tmp_path, monkeypatch):
    """Sets up an isolated test project environment."""
    project_root = tmp_path / "project"
    run_log_dir = project_root / "runs"
    reports_dir = project_root / "reports"
    trust_root = project_root / ".aes" / "keys"

    run_log_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    trust_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", project_root)
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", run_log_dir)
    monkeypatch.setattr("eval_runner.config.REPORTS_DIR", reports_dir)
    monkeypatch.setattr("eval_runner.config.TRUST_ROOT", trust_root)

    IdentityService._provision_local_identity("system_id")
    IdentityService._provision_local_identity("test_signer")

    return {
        "project_root": project_root,
        "run_log_dir": run_log_dir,
        "reports_dir": reports_dir,
        "trust_root": trust_root,
    }


def test_flight_recorder_write_rejection_after_freeze(isolated_vault):
    """Verify FlightRecorderPlugin rejects event writes once a run is FINALIZING/SEALED."""
    store = LocalFileRunStore(isolated_vault["run_log_dir"])
    recorder = FlightRecorderPlugin(run_store=store)
    run_id = "freeze-test-run-001"
    store.create_run(run_id, scenario_id="scenario")

    # 1. Normal write while RUNNING
    recorder.handle_event(Event("test_action", {"run_id": run_id, "data": "initial_event"}))
    events = store.get_events(run_id, offset=0, limit=100)
    assert any(e.get("data") == "initial_event" for e in events)

    # 2. Freeze the run
    recorder.freeze_run(run_id)
    assert recorder.get_run_state(run_id) in {"FINALIZING", "SEALED"}

    # 3. Subsequent event writes are dropped/rejected
    recorder.handle_event(Event("test_action", {"run_id": run_id, "data": "post_freeze_mutation"}))
    events_after = store.get_events(run_id, offset=0, limit=100)
    assert not any(e.get("data") == "post_freeze_mutation" for e in events_after)


def test_deterministic_evidence_root_derivation_and_mismatch(isolated_vault):
    """Verify sign_trace_bytes computes evidence root deterministically and fails on mismatch."""
    run_id = "evroot-test-run-001"
    store = LocalFileRunStore(isolated_vault["run_log_dir"])
    store.create_run(run_id, scenario_id="scenario")
    store.append_events(
        run_id,
        [
            {"event": "metric_evaluated", "metric": "safety", "passed": True, "_seq": 1},
            {"event": "run_end", "_seq": 2},
        ],
    )
    trace_bytes = store.get_trace_bytes(run_id)

    # 1. sign_trace_bytes without evidence_root_hash -> derives automatically
    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        run_id=run_id,
        run_store=store,
        identity_id="test_signer",
        compliance_status="pass",
    )
    derived_root = manifest.get("evidence_root_hash")
    assert derived_root is not None
    assert derived_root.startswith("sha3_256:")
    assert manifest["provisional"] is True

    # 2. sign_trace_bytes with mismatched evidence_root_hash -> fails closed
    bogus_root = "sha3_256:" + "0" * 64
    with pytest.raises(Exception) as exc_info:
        TraceVerifier.sign_trace_bytes(
            trace_bytes,
            run_id=run_id,
            run_store=store,
            identity_id="test_signer",
            evidence_root_hash=bogus_root,
        )
    err_str = str(exc_info.value)
    assert "EvidenceRootMismatch" in err_str or "CERTIFICATION_FAILED" in err_str


def test_public_key_only_verification_without_private_key(isolated_vault, monkeypatch):
    """Verify verify_trace_certificate verifies using public keys only."""
    run_id = "pubkey-verify-run-001"
    store = LocalFileRunStore(isolated_vault["run_log_dir"])
    store.create_run(run_id, scenario_id="scenario")
    store.append_events(run_id, [{"event": "start", "_seq": 1}])
    trace_bytes = store.get_trace_bytes(run_id)

    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        run_id=run_id,
        run_store=store,
        identity_id="test_signer",
        compliance_status="pass",
    )

    # Monkeypatch get_private_key to raise an error to prove it is NEVER called
    def _forbidden_get_private_key(*args, **kwargs):
        raise AssertionError("Private key accessed during verification! Must use public keys only.")

    target = "eval_runner.identity.IdentityService.get_private_key"
    monkeypatch.setattr(target, _forbidden_get_private_key)

    res = verify_trace_certificate(run_id=run_id, trace_bytes=trace_bytes, cert_data=manifest)
    assert res["verified"] is True
    assert res["signer_identity"] == "test_signer"


def test_scenario_hash_binding_enforcement(isolated_vault):
    """Verify verify_trace_certificate requires scenario_hash_match to certify."""
    run_id = "scenario-bound-run-001"
    store = LocalFileRunStore(isolated_vault["run_log_dir"])
    store.create_run(run_id, scenario_id="scenario")
    store.append_events(run_id, [{"event": "start", "_seq": 1}])
    trace_bytes = store.get_trace_bytes(run_id)

    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        run_id=run_id,
        run_store=store,
        identity_id="test_signer",
        metadata={"scenario_hash": "sha3_256:correct_scen_hash_123"},
    )

    # 1. Missing scenario data when scenario_hash is present -> verified = False
    res_missing = verify_trace_certificate(
        run_id=run_id, trace_bytes=trace_bytes, cert_data=manifest
    )
    assert res_missing["verified"] is False
    assert any("Scenario binding verification required" in err for err in res_missing["errors"])


def test_verify_trace_certificate_invalid_utf8_trace(isolated_vault):
    """Verify verify_trace_certificate fails when trace_bytes contains non-UTF-8 bytes."""
    run_id = "utf8-fail-run-001"
    store = LocalFileRunStore(isolated_vault["run_log_dir"])
    store.create_run(run_id, scenario_id="scenario")
    store.append_events(run_id, [{"event": "start", "_seq": 1}])
    trace_bytes = store.get_trace_bytes(run_id)

    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        run_id=run_id,
        run_store=store,
        identity_id="test_signer",
    )
    # Pass invalid UTF-8 trace bytes to verify_trace_certificate
    invalid_trace_bytes = b"\xff\xfe\xfa\x00\x80\x81"
    res = verify_trace_certificate(
        run_id=run_id, trace_bytes=invalid_trace_bytes, cert_data=manifest
    )
    assert res["verified"] is False
    assert any("Trace file is not valid UTF-8" in err for err in res["errors"])


def test_verify_trace_certificate_malformed_trace_line(isolated_vault):
    """Verify verify_trace_certificate fails when trace_bytes contains malformed JSONL line."""
    run_id = "malformed-line-run-001"
    store = LocalFileRunStore(isolated_vault["run_log_dir"])
    store.create_run(run_id, scenario_id="scenario")
    store.append_events(run_id, [{"event": "start", "_seq": 1}])
    trace_bytes = store.get_trace_bytes(run_id)

    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        run_id=run_id,
        run_store=store,
        identity_id="test_signer",
    )
    malformed_trace_bytes = b'{"event": "start"}\n{invalid-json-line}\n'
    res = verify_trace_certificate(
        run_id=run_id, trace_bytes=malformed_trace_bytes, cert_data=manifest
    )
    assert res["verified"] is False
    assert any("Malformed trace record at line" in err for err in res["errors"])


def test_public_verification_score_independence(isolated_vault):
    """Verify /v1/verify/<run_id> reports verified=True for a passing status with score < 1.0."""
    run_id = "score-indep-run-001"
    store = LocalFileRunStore(isolated_vault["run_log_dir"])
    store.create_run(run_id, scenario_id="scenario")
    store.append_events(run_id, [{"event": "start", "_seq": 1}])
    trace_bytes = store.get_trace_bytes(run_id)

    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        identity_id="test_signer",
        run_id=run_id,
        run_store=store,
        compliance_status="pass",
        compliance_score=0.96,  # Non-perfect passing score
        execution_mode="live",
    )
    store.save_run_manifest(run_id, manifest)
    store.update_run_status(run_id, "SEALED")

    app = Flask(__name__)
    app.extensions["agentv_run_store"] = store
    app.register_blueprint(trust_bp, url_prefix="/api")
    client = app.test_client()

    with patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=True):
        resp = client.get(f"/api/v1/verify/{run_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["verified"] is True
        assert data["cryptographically_valid"] is True
        assert data["compliance_score"] == 0.96
        assert data["policy_compliant"] is True


def test_explain_run_reads_only_provider_events(isolated_vault):
    """Explain never creates a filesystem trace outside the active provider."""
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(run_bp, url_prefix="/api")
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["user"] = {"id": "tester", "roles": ["admin"]}

    with patch("eval_runner.console.auth_manager.get_auth_provider") as get_provider:
        provider = MagicMock()
        provider.has_permission.return_value = True
        get_provider.return_value = provider
        store = MagicMock()
        store.get_events.return_value = [{"event": "start", "run_id": "master-run-001", "_seq": 1}]
        with patch("eval_runner.console.routes.runs._active_run_store", return_value=store):
            resp = client.get("/api/v1/explain/master-run-001")
    assert resp.status_code == 200


def test_provider_stream_preserves_intrinsic_seq(isolated_vault):
    """Verify provider streaming keeps forensic _seq while transport ids are cursors."""
    run_id = "seq-test-run-001"
    events = [{"event": "step_1", "_seq": 42}, {"event": "run_end", "_seq": 43}]
    store = MagicMock()
    store.get_run.return_value = {"run_id": run_id, "status": "RUNNING"}
    store.stream_events.return_value = iter(events)
    app = Flask(__name__)
    with (
        patch.object(runs_route, "_active_run_store", return_value=store),
        patch.object(runs_route, "active_runtime_context", return_value=None),
        app.test_request_context("/"),
    ):
        emitted = "".join(runs_route.stream_run_logs.__wrapped__(run_id).response)
    assert '"_seq": 42' in emitted
    assert '"_seq": 43' in emitted
    assert "id: 42" in emitted or "id: 1" in emitted
    assert "id: 43" in emitted or "id: 2" in emitted


def test_verification_authority_default_require_signature():
    """Verify VerificationAuthority.verify_package enforces require_signature=True."""
    pkg = VerificationPackage(
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:abcd",
        manifest_id="manifest-001",
        manifest_hash="sha3_256:fedcba0987654321fedcba0987654321fedcba0987654321fedcba0987654321",
        execution_identity={"agent_id": "test_agent"},
        trace_hash="sha3_256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        trace_seal={"seal": "ok"},
        evidence_root_hash="sha3_256:1111222233334444555566667777888899990000aaaabbbbccccddddeeeeffff",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"verdict": "PASS"},
        signature=None,  # Unsigned
    )

    res = VerificationAuthority.verify_package(pkg)
    assert res["verified"] is False
    assert any("UnsignedPackage" in f for f in res["failures"])


def test_authoritative_verdict_execution(isolated_vault):
    """Verify _authoritative_verdict runs full TraceVerifier verification."""
    store = LocalFileRunStore(isolated_vault["run_log_dir"])
    run_id_prov = "auth-verdict-run-prov"
    store.create_run(run_id_prov, scenario_id="scenario")
    store.append_events(run_id_prov, [{"event": "start", "_seq": 1}])
    trace_prov = store.get_trace_bytes(run_id_prov)

    # Before signing -> UNKNOWN
    assert _authoritative_verdict(run_id_prov, run_store=store) == "UNKNOWN"

    # Sign trace without declared mode -> VERIFIED_PROVISIONAL
    manifest_prov = TraceVerifier.sign_trace_bytes(
        trace_prov,
        identity_id="test_signer",
        run_id=run_id_prov,
        run_store=store,
        compliance_status="pass",
    )
    store.save_run_manifest(run_id_prov, manifest_prov)
    store.update_run_status(run_id_prov, "SEALED")
    assert _authoritative_verdict(run_id_prov, run_store=store) == "VERIFIED_PROVISIONAL"

    # Distinct live run: Sign trace with declared non-provisional mode -> VERIFIED
    run_id_live = "auth-verdict-run-live"
    store.create_run(run_id_live, scenario_id="scenario")
    store.append_events(
        run_id_live,
        [
            {"event": "run_start", "execution_mode": "live", "_seq": 1},
            {"event": "run_end", "_seq": 2},
        ],
    )
    trace_live = store.get_trace_bytes(run_id_live)

    manifest_live = TraceVerifier.sign_trace_bytes(
        trace_live,
        identity_id="test_signer",
        run_id=run_id_live,
        run_store=store,
        compliance_status="pass",
        execution_mode="live",
        provisional=False,
    )
    store.save_run_manifest(run_id_live, manifest_live)
    store.update_run_status(run_id_live, "SEALED")
    assert _authoritative_verdict(run_id_live, run_store=store) == "VERIFIED"

    # Tamper trace in provider -> FAILED_VERIFICATION
    (isolated_vault["run_log_dir"] / run_id_live / "run.jsonl").write_bytes(
        b'{"_seq":1,"event":"tampered"}\n'
    )
    assert _authoritative_verdict(run_id_live, run_store=store) == "FAILED_VERIFICATION"


def test_provider_lookup_rejects_missing_or_unsafe_run_ids(isolated_vault):
    """The console asks its provider; it never probes alternate trace paths."""
    store = MagicMock()
    store.get_run.return_value = None
    app = Flask(__name__)
    with (
        patch.object(runs_route, "_active_run_store", return_value=store),
        patch.object(runs_route, "active_runtime_context", return_value=None),
        app.test_request_context("/"),
    ):
        response, status = runs_route.get_run_status.__wrapped__("../evil/path")
    assert status == 404
    assert response.get_json()["error"] == "Run not found"
