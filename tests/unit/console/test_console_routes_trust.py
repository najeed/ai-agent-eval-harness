import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from agentv_runtime.evidence_graph import build_evidence_graph_from_events
from agentv_runtime.finalization import EvaluatorFinalizationRecord
from agentv_runtime.manifest import compute_scenario_hash
from eval_runner import config

# SUT
from eval_runner.console.routes.trust import trust_bp
from eval_runner.utils import rmtree_resilient


def _make_finalization_event(
    run_id: str,
    scenario_id: str,
    events: list[str],
    outcome: str = "pass",
    score: float = 1.0,
    run_dir: Any = None,
) -> str:
    """Build a cryptographically-valid EvaluatorFinalizationRecord event."""
    from pathlib import Path

    from agentv_runtime.manifest import ExecutionManifest

    parsed = []
    for line in events:
        line = line.strip()
        if line:
            try:
                parsed.append(json.loads(line))
            except Exception:
                pass

    ev_graph = build_evidence_graph_from_events(parsed)
    evidence_root = ev_graph.get(
        "evidence_root_hash",
        f"sha3_256:{hashlib.sha3_256(b'empty').hexdigest()}",
    )

    scenario_data = {"id": scenario_id, "version": "1.0.0"}
    scen_hash = compute_scenario_hash(scenario_data)
    exec_manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id=scenario_id,
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
    )
    exec_manifest_hash = exec_manifest.compute_manifest_hash()
    if run_dir is not None:
        (Path(run_dir) / "execution_manifest.json").write_text(
            json.dumps(exec_manifest.to_dict()), encoding="utf-8"
        )

    rec = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash=exec_manifest_hash,
        scenario_id=scenario_id,
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        evaluator_identity="test_evaluator",
        evaluator_config_hash="sha3_256:abc123",
        required_oracle_ids=[],
        evidence_root_hash=evidence_root,
        outcome=outcome,
        score=score,
        terminal_seq=1,
    )
    rec = rec.sign()
    fin_dict = rec.to_dict()
    return json.dumps({"event": "evaluator_finalization", "data": fin_dict})


@pytest.fixture(scope="module")
def console_jail(request):
    worker_id = getattr(request.config, "workerinput", {}).get("workerid", "master")
    tmp_root = Path(tempfile.gettempdir()) / f"aes_console_trust_jail_{worker_id}"
    root = tmp_root / "root"
    runs = root / "runs"

    if tmp_root.exists():
        rmtree_resilient(tmp_root)

    os.makedirs(runs, exist_ok=True)
    yield {"root": root, "runs": runs}

    if tmp_root.exists():
        rmtree_resilient(tmp_root)


@pytest.fixture
def client(console_jail, monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
    app.register_blueprint(trust_bp)

    monkeypatch.setattr(config, "PROJECT_ROOT", console_jail["root"])
    monkeypatch.setattr(config, "RUN_LOG_DIR", console_jail["runs"])
    trust_root = console_jail["root"] / ".aes" / "keys"
    trust_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "TRUST_ROOT", trust_root)

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        yield app.test_client()


def test_certify_run_missing_id(client):
    res = client.post("/api/v1/certify", json={})
    assert res.status_code == 400
    assert "run_id is required" in res.get_json()["error"]


def test_certify_run_404(client):
    res = client.post("/api/v1/certify", json={"run_id": "ghost_run"})
    assert res.status_code == 404
    assert "vault not found" in res.get_json()["error"]


def test_certify_run_success(client, console_jail):
    run_id = "test_run_1"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    start_ev = json.dumps(
        {
            "event": "run_start",
            "scenario_id": "scen_1",
            "data": {"execution_mode": "live", "execution_mode_declared": True},
        }
    )
    assert_ev = json.dumps({"event": "assertion_evaluated", "assertion": "check_1", "passed": True})
    end_ev = json.dumps({"event": "run_end", "data": {"status": "pass", "score": 1.0}})
    core_events = [start_ev, assert_ev, end_ev]
    fin_ev = _make_finalization_event(run_id, "scen_1", core_events, run_dir=run_dir)
    (run_dir / "run.jsonl").write_text("\n".join(core_events + [fin_ev]) + "\n", encoding="utf-8")

    with (
        patch("eval_runner.verifier.TraceVerifier.sign_trace") as mock_sign,
        patch(
            "eval_runner.loader.load_scenario", return_value={"id": "scen_1", "version": "1.0.0"}
        ),
    ):
        mock_sign.return_value = {"trace_hash": "fake_hash"}
        res = client.post(
            "/api/v1/certify",
            json={"run_id": run_id, "scenario_data": {"id": "scen_1", "version": "1.0.0"}},
        )
        assert res.status_code == 200
        assert res.get_json()["status"] == "certified"
        assert (run_dir / "run_manifest.json").exists()


def test_certify_run_inconclusive_missing_terminal_fails_closed(client, console_jail):
    run_id = "inconclusive_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    start_ev = json.dumps(
        {"event": "run_start", "data": {"execution_mode": "live", "execution_mode_declared": True}}
    )
    (run_dir / "run.jsonl").write_text(f"{start_ev}\n", encoding="utf-8")

    res = client.post("/api/v1/certify", json={"run_id": run_id})
    assert res.status_code == 400
    assert "inconclusive" in res.get_json()["error"]


def test_certify_run_fail_closed_computed_fail(client, console_jail):
    run_id = "computed_fail_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    start_ev = json.dumps(
        {
            "event": "run_start",
            "scenario_id": "scen_1",
            "data": {"execution_mode": "live", "execution_mode_declared": True},
        }
    )
    assert_ev = json.dumps(
        {"event": "assertion_evaluated", "assertion": "check_1", "passed": False}
    )
    end_ev = json.dumps({"event": "run_end", "data": {"status": "fail", "score": 0.0}})
    core_events = [start_ev, assert_ev, end_ev]
    fin_ev = _make_finalization_event(
        run_id, "scen_1", core_events, outcome="fail", score=0.0, run_dir=run_dir
    )
    (run_dir / "run.jsonl").write_text("\n".join(core_events + [fin_ev]) + "\n", encoding="utf-8")

    with (
        patch("eval_runner.verifier.TraceVerifier.sign_trace") as mock_sign,
        patch(
            "eval_runner.loader.load_scenario", return_value={"id": "scen_1", "version": "1.0.0"}
        ),
    ):
        mock_sign.return_value = {"trace_hash": "fake_hash"}
        # Attempt to override computed fail with pass
        res = client.post(
            "/api/v1/certify",
            json={
                "run_id": run_id,
                "status": "pass",
                "scenario_data": {"id": "scen_1", "version": "1.0.0"},
            },
        )
        assert res.status_code == 200
        # Assert that sign_trace received fail
        assert mock_sign.call_args[1]["compliance_status"] == "fail"


def test_verify_run_public_404(client):
    res = client.get("/api/v1/verify/none")
    assert res.status_code == 404


def test_verify_run_public_unsealed_rejected(client, console_jail):
    """Verify that unsealed runs return 400 with unsealed error."""
    run_id = "verify_unsealed"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text("trace", encoding="utf-8")
    manifest = {
        "compliance_status": "pass",
        "compliance_score": 1.0,
        "trace_hash": "h",
        "hash_algorithm": "sha3_256",
        "execution_mode": "live",
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    res = client.get(f"/api/v1/verify/{run_id}")
    assert res.status_code == 400
    data = res.get_json()
    assert data["verified"] is False
    assert "is not sealed" in data["error"]


def test_verify_run_public_compliant(client, console_jail):
    run_id = "verify_ok"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text("trace", encoding="utf-8")
    (run_dir / ".sealed").touch()
    manifest = {
        "compliance_status": "pass",
        "compliance_score": 1.0,
        "trace_hash": "h",
        "hash_algorithm": "sha3_256",
        "execution_mode": "live",
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=True):
        res = client.get(f"/api/v1/verify/{run_id}")
        assert res.status_code == 200
        assert res.get_json()["verified"] is True
        assert res.get_json()["terminal_verdict"] == "CERTIFIED_PASS"


def test_verify_run_public_non_compliant_score(client, console_jail):
    run_id = "verify_fail"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text("trace", encoding="utf-8")
    (run_dir / ".sealed").touch()
    manifest = {
        "compliance": {"status": "fail", "score": 0.5},
        "trace_hash": "h",
        "hash_algorithm": "sha3_256",
        "execution_mode": "live",
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=True):
        res = client.get(f"/api/v1/verify/{run_id}")
        assert res.status_code == 200
        data = res.get_json()
        assert data["verified"] is False
        assert data["policy_compliant"] is False
        assert data["compliance_score"] == 0.5
        assert data["cryptographically_valid"] is True
        assert data["terminal_verdict"] == "ATTESTED_FAIL"


def test_verify_run_exception(client, console_jail):
    run_id = "verify_error"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text("trace", encoding="utf-8")
    (run_dir / ".sealed").touch()
    (run_dir / "run_manifest.json").write_text("bad data", encoding="utf-8")

    res = client.get(f"/api/v1/verify/{run_id}")
    assert res.status_code == 500
    assert res.get_json()["verified"] is False


def test_get_identity_public_key_success(client):
    with patch(
        "eval_runner.console.routes.trust.identity.IdentityService.get_public_key"
    ) as mock_get:
        mock_key = MagicMock()
        mock_key.public_bytes.return_value = b"PEM_KEY"
        mock_get.return_value = mock_key

        res = client.get("/api/v1/identity/sys1/public_key")
        assert res.status_code == 200
        assert "PEM_KEY" in res.get_json()["public_key"]


def test_get_identity_public_key_404(client):
    with patch(
        "eval_runner.console.routes.trust.identity.IdentityService.get_public_key",
        side_effect=ValueError("not found"),
    ):
        res = client.get("/api/v1/identity/ghost/public_key")
        assert res.status_code == 404


def test_verify_run_cryptographic_proof(client, console_jail):
    run_id = "verify_crypto"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text("trace", encoding="utf-8")
    (run_dir / ".sealed").touch()
    manifest = {
        "compliance": {"status": "pass", "score": 1.0},
        "trace_hash": "h",
        "hash_algorithm": "sha3_256",
        "execution_mode": "live",
        "provenance_chain": [{"signer": "sys1"}],
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=True):
        res = client.get(f"/api/v1/verify/{run_id}")
        assert res.status_code == 200
        assert res.get_json()["verified"] is True
        assert "ED25519" in res.get_json()["method"]


def test_certify_run_generic_exception(client, console_jail):
    run_id = "crash_run"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    start_ev = json.dumps(
        {
            "event": "run_start",
            "scenario_id": "scen_1",
            "data": {"execution_mode": "live", "execution_mode_declared": True},
        }
    )
    assert_ev = json.dumps({"event": "assertion_evaluated", "assertion": "check_1", "passed": True})
    end_ev = json.dumps({"event": "run_end", "data": {"status": "pass", "score": 1.0}})
    core_events = [start_ev, assert_ev, end_ev]
    fin_ev = _make_finalization_event(run_id, "scen_1", core_events, run_dir=run_dir)
    (run_dir / "run.jsonl").write_text("\n".join(core_events + [fin_ev]) + "\n", encoding="utf-8")

    with (
        patch(
            "eval_runner.verifier.TraceVerifier.sign_trace",
            side_effect=Exception("Critical Failure"),
        ),
        patch(
            "eval_runner.loader.load_scenario", return_value={"id": "scen_1", "version": "1.0.0"}
        ),
    ):
        res = client.post(
            "/api/v1/certify",
            json={"run_id": run_id, "scenario_data": {"id": "scen_1", "version": "1.0.0"}},
        )
        assert res.status_code == 500
        assert "Critical Failure" in res.get_json()["error"]


def test_read_run_truth_level_branches(client, console_jail):
    from eval_runner.console.routes.trust import _read_run_truth_level

    # Nonexistent trace
    mode, prov = _read_run_truth_level("nonexistent_run")
    assert mode is None
    assert prov is False

    # Trace with empty line and non-run_start event
    run_id = "truth_level_test"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.jsonl").write_text(
        "\n"
        + json.dumps({"event": "other_event"})
        + "\n"
        + json.dumps(
            {
                "event": "run_start",
                "data": {"execution_mode": "LIVE_API", "execution_mode_declared": True},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    mode, prov = _read_run_truth_level(run_id)
    assert mode == "LIVE_API"
    # LIVE_API is not a recognized canonical execution mode (only 'live' and 'hybrid' are);
    # therefore it is correctly classified as provisional=True per the T1 contract.
    assert prov is True


def test_get_identity_public_key_none_and_private_key_none(client):
    from eval_runner.console.routes.trust import _private_key_pem_bytes

    # Public key returns None
    with patch(
        "eval_runner.console.routes.trust.identity.IdentityService.get_public_key",
        return_value=None,
    ):
        res = client.get("/api/v1/identity/sys_none/public_key")
        assert res.status_code == 404

    # Private key returns None
    with patch(
        "eval_runner.console.routes.trust.identity.IdentityService.get_private_key",
        return_value=None,
    ):
        with pytest.raises(ValueError, match="No signing identity available"):
            _private_key_pem_bytes("sys_none")


def test_extension_signing_and_verification_endpoints(client, monkeypatch):
    # Sign manifest invalid (non-dict)
    res_sign_invalid = client.post("/api/v1/extensions/sign", json={"manifest": "not-a-dict"})
    assert res_sign_invalid.status_code == 400

    # Sign manifest missing required field raising ExtensionContractError
    res_sign_missing = client.post(
        "/api/v1/extensions/sign", json={"manifest": {"extension_id": "only_id"}}
    )
    assert res_sign_missing.status_code == 400
    assert "Invalid manifest" in res_sign_missing.get_json()["error"]

    # _public_key_pem_bytes returns None
    from eval_runner.console.routes.trust import _public_key_pem_bytes

    with patch("eval_runner.identity.IdentityService.get_public_key", return_value=None):
        assert _public_key_pem_bytes("ghost_identity") is None

    # Sign manifest signing exception (500)
    valid_manifest = {
        "extension_id": "ext-1",
        "display_name": "Extension 1",
        "version": "1.0.0",
        "remote_entry": "http://127.0.0.1:8080/ext.js",
        "sri_hash": "sha3-256-dummy",
        "publisher": "dev_publisher",
        "capabilities": ["routes", "navigation"],
    }
    with patch(
        "eval_runner.console.routes.trust._private_key_pem_bytes",
        side_effect=OSError("Key unreadable"),
    ):
        res_sign_500 = client.post("/api/v1/extensions/sign", json={"manifest": valid_manifest})
        assert res_sign_500.status_code == 500

    # Successful signing
    res_sign = client.post("/api/v1/extensions/sign", json={"manifest": valid_manifest})
    assert res_sign.status_code == 200
    sig_data = res_sign.get_json()
    assert "signature" in sig_data

    # Verify publisher non-dict manifest
    res_ver_nodict = client.post(
        "/api/v1/extensions/verify-publisher", json={"manifest": "not-dict"}
    )
    assert res_ver_nodict.status_code == 400

    # Verify publisher contract violation
    res_ver_viol = client.post(
        "/api/v1/extensions/verify-publisher",
        json={"manifest": {"extension_id": "bad", "display_name": "Bad", "version": "not-semver"}},
    )
    assert res_ver_viol.status_code == 400
    assert res_ver_viol.get_json()["reason"] == "contract-violation"

    # Verify publisher missing signature
    res_ver_nosig = client.post(
        "/api/v1/extensions/verify-publisher",
        json={"manifest": {**valid_manifest, "signature": ""}},
    )
    assert res_ver_nosig.status_code == 200
    assert res_ver_nosig.get_json()["reason"] == "missing-signature"

    # Verify publisher missing publisher name
    res_ver_nopub = client.post(
        "/api/v1/extensions/verify-publisher",
        json={"manifest": {**valid_manifest, "publisher": "", "signature": sig_data["signature"]}},
    )
    assert res_ver_nopub.status_code == 200
    assert res_ver_nopub.get_json()["reason"] == "missing-publisher"

    # Verify publisher unknown publisher
    with patch("eval_runner.console.routes.trust._public_key_pem_bytes", return_value=None):
        res_ver_unknown = client.post(
            "/api/v1/extensions/verify-publisher",
            json={
                "manifest": {
                    **valid_manifest,
                    "publisher": "ghost_pub",
                    "signature": sig_data["signature"],
                },
            },
        )
        assert res_ver_unknown.status_code == 200
        assert res_ver_unknown.get_json()["reason"] == "unknown-publisher"

    # Verify publisher signature mismatch
    res_ver_bad_sig = client.post(
        "/api/v1/extensions/verify-publisher",
        json={
            "manifest": {**valid_manifest, "signature": "00" * 64},
        },
    )
    assert res_ver_bad_sig.status_code == 200
    assert res_ver_bad_sig.get_json()["tier"] == "invalid-signature"
    assert res_ver_bad_sig.get_json()["reason"] == "signature-mismatch"

    # Verify publisher community tier
    monkeypatch.setenv("AGENTV_OFFICIAL_PUBLISHERS", "other_corp")
    res_ver_comm = client.post(
        "/api/v1/extensions/verify-publisher",
        json={
            "manifest": {**valid_manifest, "signature": sig_data["signature"]},
        },
    )
    assert res_ver_comm.status_code == 200
    assert res_ver_comm.get_json()["tier"] == "community"
    assert res_ver_comm.get_json()["valid"] is True

    # Verify publisher official tier
    monkeypatch.setenv("AGENTV_OFFICIAL_PUBLISHERS", "dev_publisher,sec_corp")
    res_ver_official = client.post(
        "/api/v1/extensions/verify-publisher",
        json={
            "manifest": {**valid_manifest, "signature": sig_data["signature"]},
        },
    )
    assert res_ver_official.status_code == 200
    assert res_ver_official.get_json()["tier"] == "official"
    assert res_ver_official.get_json()["valid"] is True

    assert res_ver_official.status_code == 200
    assert res_ver_official.get_json()["tier"] == "official"
    assert res_ver_official.get_json()["valid"] is True


def test_verify_run_trace_parse_error_fallback(client, console_jail):
    """Lines 140-141: bad UTF-8 trace bytes still proceed (events_data stays empty)."""
    run_id = "verify_parse_err"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    # Write invalid UTF-8 bytes
    (run_dir / "run.jsonl").write_bytes(b"\xff\xfe not utf-8")
    (run_dir / ".sealed").touch()
    manifest = {
        "compliance_status": "pass",
        "compliance_score": 1.0,
        "trace_hash": "h",
        "hash_algorithm": "sha3_256",
        "execution_mode": "live",
        "verification_package": {
            "scenario_id": "s1",
            "scenario_version": "1.0.0",
            "scenario_hash": "sha3_256:abc",
            "manifest_id": "m1",
            "manifest_hash": "sha3_256:def",
            "execution_identity": {},
            "trace_hash": "sha3_256:abc",
            "trace_seal": {},
            "evidence_root_hash": "sha3_256:ev",
            "required_oracle_ids": [],
            "executed_oracle_results": [],
            "decision": {"decision": "PASS", "verdict": "VERIFIED"},
            "signature": None,
            "signer_identity": "sys",
        },
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with (
        patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=True),
        patch(
            "eval_runner.verifier.VerificationAuthority.verify_package_artifacts",
            return_value={"verified": False, "failures": ["TraceEventsMissing: ..."]},
        ),
    ):
        res = client.get(f"/api/v1/verify/{run_id}")
    # Should not crash; is_valid becomes False due to failed pkg artifacts
    assert res.status_code == 200
    assert res.get_json()["verified"] is False


def test_verify_run_exec_manifest_read_error_fallback(client, console_jail):
    """Lines 148-149: corrupt execution_manifest.json silently falls back to main manifest."""
    run_id = "verify_exec_manifest_err"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_event = json.dumps({"event": "start", "_seq": 1})
    (run_dir / "run.jsonl").write_text(trace_event + "\n", encoding="utf-8")
    (run_dir / ".sealed").touch()
    # Write corrupt execution_manifest.json (not valid JSON)
    (run_dir / "execution_manifest.json").write_bytes(b"\xff\xfe corrupt")
    manifest = {
        "compliance_status": "pass",
        "compliance_score": 1.0,
        "trace_hash": "h",
        "hash_algorithm": "sha3_256",
        "execution_mode": "live",
        "verification_package": {
            "scenario_id": "s1",
            "scenario_version": "1.0.0",
            "scenario_hash": "sha3_256:abc",
            "manifest_id": "m1",
            "manifest_hash": "sha3_256:def",
            "execution_identity": {},
            "trace_hash": "sha3_256:abc",
            "trace_seal": {},
            "evidence_root_hash": "sha3_256:ev",
            "required_oracle_ids": [],
            "executed_oracle_results": [],
            "decision": {"decision": "PASS", "verdict": "VERIFIED"},
            "signature": None,
            "signer_identity": "sys",
        },
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with (
        patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=True),
        patch(
            "eval_runner.verifier.VerificationAuthority.verify_package_artifacts",
            return_value={"verified": True, "failures": []},
        ),
    ):
        res = client.get(f"/api/v1/verify/{run_id}")
    # Falls back to main manifest for canonical_m; verification should proceed
    assert res.status_code == 200


def test_verify_run_scenario_resolved_read_error_fallback(client, console_jail):
    """Lines 156-157: corrupt scenario_resolved.json silently falls back (scen_data=None)."""
    run_id = "verify_scen_resolved_err"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_event = json.dumps({"event": "start", "_seq": 1})
    (run_dir / "run.jsonl").write_text(trace_event + "\n", encoding="utf-8")
    (run_dir / ".sealed").touch()
    # Write corrupt scenario_resolved.json
    (run_dir / "scenario_resolved.json").write_bytes(b"\xff\xfe corrupt")
    manifest = {
        "compliance_status": "pass",
        "compliance_score": 1.0,
        "trace_hash": "h",
        "hash_algorithm": "sha3_256",
        "execution_mode": "live",
        "verification_package": {
            "scenario_id": "s1",
            "scenario_version": "1.0.0",
            "scenario_hash": "sha3_256:abc",
            "manifest_id": "m1",
            "manifest_hash": "sha3_256:def",
            "execution_identity": {},
            "trace_hash": "sha3_256:abc",
            "trace_seal": {},
            "evidence_root_hash": "sha3_256:ev",
            "required_oracle_ids": [],
            "executed_oracle_results": [],
            "decision": {"decision": "PASS", "verdict": "VERIFIED"},
            "signature": None,
            "signer_identity": "sys",
        },
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with (
        patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=True),
        patch(
            "eval_runner.verifier.VerificationAuthority.verify_package_artifacts",
            return_value={"verified": True, "failures": []},
        ),
    ):
        res = client.get(f"/api/v1/verify/{run_id}")
    # scen_data falls back to None; no crash
    assert res.status_code == 200


def test_verify_run_pkg_artifacts_fail_marks_invalid(client, console_jail):
    """Lines 168-172: verify_package_artifacts returning verified=False sets is_valid=False."""
    run_id = "verify_pkg_fail"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_event = json.dumps({"event": "start", "_seq": 1})
    (run_dir / "run.jsonl").write_text(trace_event + "\n", encoding="utf-8")
    (run_dir / ".sealed").touch()
    manifest = {
        "compliance_status": "pass",
        "compliance_score": 1.0,
        "trace_hash": "h",
        "hash_algorithm": "sha3_256",
        "execution_mode": "live",
        "verification_package": {
            "scenario_id": "s1",
            "scenario_version": "1.0.0",
            "scenario_hash": "sha3_256:abc",
            "manifest_id": "m1",
            "manifest_hash": "sha3_256:def",
            "execution_identity": {},
            "trace_hash": "sha3_256:abc",
            "trace_seal": {},
            "evidence_root_hash": "sha3_256:ev",
            "required_oracle_ids": [],
            "executed_oracle_results": [],
            "decision": {"decision": "PASS", "verdict": "VERIFIED"},
            "signature": None,
            "signer_identity": "sys",
        },
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with (
        patch("eval_runner.verifier.TraceVerifier.verify_trace", return_value=True),
        patch(
            "eval_runner.verifier.VerificationAuthority.verify_package_artifacts",
            return_value={
                "verified": False,
                "failures": ["EvidenceRootMismatch: package=X actual=Y"],
            },
        ),
    ):
        res = client.get(f"/api/v1/verify/{run_id}")
    # is_valid=False means verified=False and UNVERIFIED terminal verdict
    assert res.status_code == 200
    data = res.get_json()
    assert data["verified"] is False
    assert data["terminal_verdict"] in ("UNVERIFIED", "ATTESTED_FAIL", "PROVISIONAL")


def test_get_verified_run_manifest_invalid_run_id(client):
    """Lines 247-254: path traversal run_id blocked with 400."""
    res = client.get("/api/v1/verify/../etc/passwd/manifest")
    assert res.status_code == 400
    assert "Invalid or unsafe run_id" in res.get_json()["error"]


def test_get_verified_run_manifest_not_found(client):
    """Lines 256-258: non-existent manifest returns 404."""
    res = client.get("/api/v1/verify/ghost_run_no_manifest/manifest")
    assert res.status_code == 404
    assert "not found" in res.get_json()["error"]


def test_get_verified_run_manifest_success(client, console_jail):
    """Lines 260-263: existing manifest returns 200 with manifest contents."""
    run_id = "manifest_ok"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"compliance_status": "pass", "run_id": run_id}
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    res = client.get(f"/api/v1/verify/{run_id}/manifest")
    assert res.status_code == 200
    assert res.get_json()["run_id"] == run_id


def test_get_verified_run_manifest_corrupt_file(client, console_jail):
    """Lines 264-265: corrupt manifest JSON returns 500."""
    run_id = "manifest_corrupt"
    run_dir = console_jail["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_manifest.json").write_text("not json {{", encoding="utf-8")

    res = client.get(f"/api/v1/verify/{run_id}/manifest")
    assert res.status_code == 500
    assert "Failed to load manifest" in res.get_json()["error"]
