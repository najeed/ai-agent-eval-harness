"""
tests/unit/console/test_console_routes_evidence.py
Comprehensive unit test suite achieving 100% coverage on the
Evidence & Verification Package API routes with dynamic timestamps.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from eval_runner import config
from eval_runner.console.app import create_app
from eval_runner.console.routes.evidence import (
    compute_sha3_digest,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    reports_dir = tmp_path / "reports"
    runs_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)
    monkeypatch.setattr(config, "REPORTS_DIR", reports_dir)

    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(log_dir=runs_dir)
    app = create_app(run_store=store)
    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"id": "test-admin", "name": "Admin", "permissions": ["*"]}
        yield c


@pytest.fixture
def crypto_client(tmp_path, monkeypatch):
    """
    Client with a fully provisioned certification environment: isolated trust
    root and a generated system_id keypair so real certificates can be issued.
    """
    runs_dir = tmp_path / "runs"
    reports_dir = tmp_path / "reports"
    trust_root = tmp_path / ".aes" / "keys"
    for d in (runs_dir, reports_dir, trust_root):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "RUN_LOG_DIR", runs_dir)
    monkeypatch.setattr(config, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(config, "TRUST_ROOT", trust_root)

    from eval_runner.identity import IdentityService

    IdentityService._provision_local_identity("system_id")

    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(log_dir=runs_dir)
    app = create_app(run_store=store)
    app.config["TESTING"] = True
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user"] = {"id": "test-admin", "name": "Admin", "permissions": ["*"]}
        yield c


def test_compute_sha3_digest():
    digest_bytes = compute_sha3_digest(b"test content")
    digest_str = compute_sha3_digest("test content")
    assert digest_bytes == digest_str
    assert digest_bytes.startswith("sha3_256:")


def test_get_verification_package_not_found(client):
    res = client.get("/api/v1/evidence/packages/run-nonexistent")
    assert res.status_code == 404
    data = res.get_json()
    assert "error" in data


def test_get_verification_package_success_with_cert_and_provenance(crypto_client, tmp_path):
    """
    P0-4: VERIFIED requires genuine cryptographic verification of a certificate
    produced by the transactional certification pipeline — not merely the
    presence of signature-shaped JSON.
    """
    import hashlib

    from agentv_runtime.evidence_graph import build_evidence_graph_from_events
    from agentv_runtime.finalization import EvaluatorFinalizationRecord
    from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash
    from eval_runner.identity import IdentityService
    from eval_runner.reference.local_run_store import LocalFileRunStore
    from eval_runner.verifier import TraceVerifier

    IdentityService._provision_local_identity("test_evaluator")

    runs_dir = Path(config.RUN_LOG_DIR)
    run_id = f"run-test-{int(datetime.now(UTC).timestamp())}"
    store = LocalFileRunStore(log_dir=runs_dir)
    store.create_run(run_id, scenario_id="sec_eval")

    now = datetime.now(UTC)

    scenario_data = {"id": "sec_eval", "title": "Security Eval", "version": "1.0.0"}
    scen_hash = compute_scenario_hash(scenario_data)
    exec_manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id="sec_eval",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
    )

    core_events = [
        {
            "event": "run_start",
            "_seq": 1,
            "run_id": run_id,
            "timestamp": now.isoformat(),
            "data": {
                "scenario": "sec_eval",
                "execution_mode": "live",
                "execution_mode_declared": True,
            },
        },
        {
            "event": "assertion_evaluated",
            "_seq": 2,
            "timestamp": (now + timedelta(seconds=5)).isoformat(),
            "data": {"name": "check1", "passed": True},
        },
        {
            "event": "run_end",
            "_seq": 3,
            "outcome": "pass",
            "timestamp": (now + timedelta(seconds=10)).isoformat(),
            "data": {"status": "EXECUTION_COMPLETED", "passed": True, "score": 1.0},
        },
    ]

    ev_graph = build_evidence_graph_from_events(core_events)
    evidence_root = ev_graph.get(
        "evidence_root_hash", f"sha3_256:{hashlib.sha3_256(b'empty').hexdigest()}"
    )
    fin_rec = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash=exec_manifest.compute_manifest_hash(),
        scenario_id="sec_eval",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        evaluator_identity="test_evaluator",
        evaluator_config_hash="sha3_256:abc123",
        required_oracle_ids=[],
        evidence_root_hash=evidence_root,
        outcome="pass",
        score=1.0,
        terminal_seq=3,
    ).sign()
    fin_ev = {"event": "evaluator_finalization", "data": fin_rec.to_dict()}
    store.append_events(run_id, [*core_events, fin_ev])

    trace_bytes = store.get_trace_bytes(run_id)
    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        run_id=run_id,
        run_store=store,
        execution_mode="live",
        scenario_data=scenario_data,
        execution_manifest=exec_manifest.to_dict(),
    )
    store.save_run_manifest(run_id, manifest)
    store.update_run_status(run_id, "SEALED")

    # Query API
    res = crypto_client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res.status_code == 200
    pkg = res.get_json()
    assert pkg["format"] == "agentv_verification_package"
    assert pkg["package_version"] == "2.0.0"  # evidence graph schema
    assert "evidence_graph" in pkg
    assert pkg["evidence_graph"]["graph_version"] == "1.0.0"

    assert pkg["verdict"]["verified_outcome"] == "VERIFIED"
    crypto = pkg["cryptographic_verification"]
    assert crypto["verified"] is True
    assert crypto["manifest_hash_match"] is True
    chain = pkg["signatures"]
    assert isinstance(chain, list) and len(chain) >= 1
    assert any(n.get("algorithm") == "ED25519" for n in chain)
    assert pkg["evidence_chain_valid"] is True
    assert "package_hash" in pkg
    assert pkg["package_hash"].startswith("sha3_256:")

    # Tampering with certified evidence must flip the verdict truthfully
    run_vault = runs_dir / run_id
    (run_vault / "run.jsonl").write_bytes(trace_bytes + b'{"event":"tampered"}\n')
    res2 = crypto_client.get(f"/api/v1/evidence/packages/{run_id}")
    pkg2 = res2.get_json()
    assert pkg2["verdict"]["verified_outcome"] == "UNVERIFIED"
    assert pkg2["evidence_chain_valid"] is False


def test_get_verification_package_policy_breach_and_vault_cert(client, tmp_path):
    runs_dir = tmp_path / "runs"
    run_id = f"run-breach-{int(datetime.now(UTC).timestamp())}"

    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(log_dir=runs_dir)
    store.create_run(run_id, scenario_id="test_scenario")

    now = datetime.now(UTC)

    events = [
        {"event": "run_start", "timestamp": now.isoformat(), "data": {}},
        {
            "event": "policy_violation",
            "timestamp": (now + timedelta(seconds=5)).isoformat(),
            "data": {"rule": "no_exfil"},
        },
        {
            "event": "run_end",
            "timestamp": (now + timedelta(seconds=10)).isoformat(),
            "data": {"status": "EXECUTION_COMPLETED", "passed": False},
        },
    ]
    store.append_events(run_id, events)

    store.save_run_manifest(
        run_id,
        {
            "provenance_chain": ["prov_root"],
            "signatures": ["prov_root"],
            "compliance": {"status": "fail"},
        },
    )

    res = client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res.status_code == 200
    pkg = res.get_json()
    # A terminal event is evidence, not certification authority.  Without a
    # sealed transactional certificate this remains explicitly preliminary.
    assert pkg["verdict"]["verified_outcome"] == "PRELIMINARY"
    assert pkg["verdict"]["assertions"] == []
    assert pkg["signatures"] == ["prov_root"]


def test_corrupt_files_in_vault(client, tmp_path):
    runs_dir = tmp_path / "runs"
    run_id = f"run-corrupt-{int(datetime.now(UTC).timestamp())}"

    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(log_dir=runs_dir)
    store.create_run(run_id, scenario_id="test_scenario")
    store.append_events(run_id, [{"event": "run_start", "data": {}}])

    run_vault = runs_dir / run_id
    # Corrupt json files
    (run_vault / "scenario_resolved.json").write_text("NOT_JSON", encoding="utf-8")
    (run_vault / "run_manifest.json").write_text("NOT_JSON", encoding="utf-8")

    res = client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res.status_code == 200
    pkg = res.get_json()
    assert pkg["tenant_id"] == "default-tenant"
    assert pkg["workspace_id"] == "default-workspace"


def test_download_verification_package(client, tmp_path):
    runs_dir = tmp_path / "runs"
    run_id = f"run-download-{int(datetime.now(UTC).timestamp())}"

    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(log_dir=runs_dir)
    store.create_run(run_id, scenario_id="test_scenario")
    store.append_events(run_id, [{"event": "run_start", "data": {}}])

    res = client.get(f"/api/v1/evidence/packages/{run_id}?download=true")
    assert res.status_code == 200
    assert "application/json" in res.content_type
    assert f"{run_id}.agentv-package.json" in res.headers.get("Content-Disposition", "")


def test_list_verification_packages(client, tmp_path):
    runs_dir = tmp_path / "runs"

    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(log_dir=runs_dir)
    store.create_run("run-001", scenario_id="scen-1")
    store.create_run("run-002", scenario_id="scen-2")
    store.save_run_manifest("run-001", {"vc_version": "3.0.0"})
    store.save_run_manifest("run-002", {"vc_version": "3.0.0"})
    (runs_dir / "ignored_file.txt").write_text("hello", encoding="utf-8")

    res = client.get("/api/v1/evidence/packages")
    assert res.status_code == 200
    data = res.get_json()
    assert "packages" in data
    assert len(data["packages"]) >= 2

    res = client.get("/api/v1/evidence/packages")
    assert res.status_code == 200
    data = res.get_json()
    assert "packages" in data
    assert len(data["packages"]) >= 2


def test_list_verification_packages_empty_dir(client, tmp_path, monkeypatch):
    nonexistent_dir = tmp_path / "does_not_exist"
    monkeypatch.setattr(config, "RUN_LOG_DIR", str(nonexistent_dir))

    res = client.get("/api/v1/evidence/packages")
    assert res.status_code == 200
    data = res.get_json()
    assert data["packages"] == []


def test_verification_package_determinism_and_unsigned_outcome(client, tmp_path):
    runs_dir = tmp_path / "runs"
    run_id = f"run-unsigned-{int(datetime.now(UTC).timestamp())}"

    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(log_dir=runs_dir)
    store.create_run(run_id, scenario_id="test_scenario")

    now = datetime.now(UTC)

    events = [
        {"event": "run_start", "timestamp": now.isoformat(), "data": {}},
        {
            "event": "run_end",
            "timestamp": (now + timedelta(seconds=10)).isoformat(),
            "data": {"status": "EXECUTION_COMPLETED", "passed": True, "score": 0.85},
        },
    ]
    store.append_events(run_id, events)

    res1 = client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res1.status_code == 200
    pkg1 = res1.get_json()
    # An unsigned terminal result is preliminary; it cannot project a verdict
    # or score into a verification package.
    assert pkg1["verdict"]["verified_outcome"] == "PRELIMINARY"
    assert pkg1["verdict"]["score"] is None
    assert pkg1["verdict"]["assertions"] == []

    res2 = client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res2.status_code == 200
    pkg2 = res2.get_json()

    # Package hash MUST be 100% deterministic despite different timestamps
    assert pkg1["package_hash"] == pkg2["package_hash"]


def test_verification_package_direct_fragment_without_vault(client, tmp_path):
    runs_dir = tmp_path / "runs"
    run_id = f"run-direct-frag-{int(datetime.now(UTC).timestamp())}"

    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(log_dir=runs_dir)
    store.create_run(run_id, scenario_id="test_scenario")

    now = datetime.now(UTC)
    events = [
        {"event": "run_start", "timestamp": now.isoformat(), "data": {}},
        {
            "event": "run_end",
            "timestamp": (now + timedelta(seconds=10)).isoformat(),
            "data": {"status": "EXECUTION_COMPLETED", "passed": False},
        },
    ]
    store.append_events(run_id, events)

    res = client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res.status_code == 200
    pkg = res.get_json()
    assert pkg["verdict"]["verified_outcome"] == "PRELIMINARY"
    assert pkg["verdict"]["score"] is None


def test_verification_package_score_default_verified(crypto_client, tmp_path):
    runs_dir = Path(config.RUN_LOG_DIR)
    run_id = f"run-default-verified-{int(datetime.now(UTC).timestamp())}"

    from eval_runner.reference.local_run_store import LocalFileRunStore
    from eval_runner.verifier import TraceVerifier

    store = LocalFileRunStore(log_dir=runs_dir)
    store.create_run(run_id, scenario_id="test_scenario")

    now = datetime.now(UTC)

    events = [
        {"event": "run_start", "timestamp": now.isoformat(), "data": {}},
        {
            "event": "run_end",
            "timestamp": (now + timedelta(seconds=10)).isoformat(),
            "data": {"status": "EXECUTION_COMPLETED", "verified": True},
        },
    ]
    store.append_events(run_id, events)
    trace_bytes = store.get_trace_bytes(run_id)

    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        run_id=run_id,
        run_store=store,
        compliance_status="pass",
        compliance_score=1.0,
    )
    store.save_run_manifest(run_id, manifest)
    store.update_run_status(run_id, "SEALED")

    res = crypto_client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res.status_code == 200
    pkg = res.get_json()
    # Direct signing with no live finalization produces PROVISIONAL_PASS;
    # sealing it manually cannot upgrade it into a certificate.
    assert pkg["verdict"]["verified_outcome"] == "UNVERIFIED"
    assert pkg["verdict"]["score"] is None


def test_fake_certificate_signature_yields_unverified(client, tmp_path):
    """
    P0-4 negative lock: signature-SHAPED JSON without a verifiable chain must
    never produce VERIFIED. Presence of signatures is not proof.
    """
    runs_dir = Path(config.RUN_LOG_DIR)
    run_id = f"run-fake-cert-{int(datetime.now(UTC).timestamp())}"

    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(log_dir=runs_dir)
    store.create_run(run_id, scenario_id="test_scenario")

    now = datetime.now(UTC)
    events = [
        {"event": "run_start", "timestamp": now.isoformat(), "data": {}},
        {
            "event": "run_end",
            "timestamp": (now + timedelta(seconds=5)).isoformat(),
            "data": {"status": "EXECUTION_COMPLETED", "passed": True},
        },
    ]
    store.append_events(run_id, events)

    manifest = {
        "signatures": ["sig_test"],
        "provenance_chain": ["p1"],
        "compliance": {"status": "pass"},
    }
    store.save_run_manifest(run_id, manifest)

    res = client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res.status_code == 200
    pkg = res.get_json()
    assert pkg["verdict"]["verified_outcome"] == "PRELIMINARY"
    assert pkg["evidence_chain_valid"] is False


def test_package_corruption_policy_blocks_certification(crypto_client, tmp_path):
    """[E3] Unparseable trace content -> EVIDENCE_INVALID + exact byte offsets."""
    import json as _json

    runs_dir = tmp_path / "runs"
    run_id = f"run-corrupt-{int(datetime.now(UTC).timestamp())}"

    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(log_dir=runs_dir)
    store.create_run(run_id, scenario_id="test_scenario")

    now = datetime.now(UTC)
    good1 = _json.dumps({"event": "run_start", "timestamp": now.isoformat(), "_seq": 1})
    corrupt_fragment = "{not valid json{{"
    good2 = _json.dumps(
        {
            "event": "run_end",
            "timestamp": (now + timedelta(seconds=5)).isoformat(),
            "_seq": 2,
            "data": {"passed": True},
        }
    )
    # Layout: line1(offset 0) | line2 corrupt | line3
    trace = runs_dir / run_id / "run.jsonl"
    line1 = (good1 + "\n").encode()
    line2 = (corrupt_fragment + "\n").encode()
    line3 = (good2 + "\n").encode()
    trace.write_bytes(line1 + line2 + line3)

    res = crypto_client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res.status_code == 200
    pkg = res.get_json()

    assert pkg["verdict"]["verified_outcome"] == "EVIDENCE_INVALID"
    assert pkg["evidence_chain_valid"] is False
    corruption = pkg["integrity_corruption"]
    assert corruption["status"] == "EVIDENCE_INVALID"
    assert corruption["corrupt_count"] == 1
    assert corruption["corrupt_line_byte_offsets"] == [len(line1)]
    assert pkg["verdict"]["assertions"] == []
    assert pkg["verdict"]["score"] is None


def test_sealed_package_rejects_graph_not_committed_by_certificate(client, tmp_path, monkeypatch):
    """A presentation graph may never replace the certificate's root."""
    from eval_runner.reference.local_run_store import LocalFileRunStore

    run_id = "run-evidence-root-mismatch"
    store = LocalFileRunStore(log_dir=tmp_path / "runs")
    store.create_run(run_id, scenario_id="scenario")
    store.append_events(
        run_id,
        [{"event": "assertion_evaluated", "_seq": 1, "data": {"passed": True}}],
    )
    store.save_run_manifest(
        run_id,
        {
            "certification": {"transactional": True, "outcome": "CERTIFIED_PASS"},
            "compliance": {"status": "pass", "score": 1.0},
            "verification_package": {
                "evidence_root_hash": "sha3_256:not-the-trace-root",
                "required_oracle_ids": [],
                "executed_oracle_results": [{"passed": True}],
            },
        },
    )
    store.update_run_status(run_id, "SEALED")

    import eval_runner.console.routes.evidence as evidence_module

    monkeypatch.setattr(
        evidence_module,
        "verify_trace_certificate",
        lambda **_kwargs: {"verified": True, "manifest_hash_match": True},
        raising=False,
    )
    # The route imports the verifier lazily, so patch its public function.
    monkeypatch.setattr(
        "eval_runner.verifier.verify_trace_certificate",
        lambda **_kwargs: {"verified": True, "manifest_hash_match": True},
    )

    package = evidence_module.build_verification_package(run_id, run_store=store)
    assert package is not None
    assert package["verdict"]["verified_outcome"] == "EVIDENCE_INVALID"
    assert package["verdict"]["assertions"] == []
    assert package["evidence_chain_valid"] is False


def test_verify_verification_package_route(client):
    import base64

    # 1. Invalid payload
    res_bad = client.post("/api/v1/evidence/verify", json="not a dict")
    assert res_bad.status_code == 400

    # 2. Valid minimal package
    pkg_payload = {
        "scenario_id": "scen-01",
        "scenario_version": "1.0.0",
        "scenario_hash": "sha3_256:scen",
        "manifest_id": "man-01",
        "manifest_hash": "sha3_256:man",
        "execution_identity": {},
        "trace_hash": "sha3_256:112233",
        "trace_seal": {},
        "evidence_root_hash": "sha3_256:evroot",
        "required_oracle_ids": [],
        "executed_oracle_results": [],
        "decision": {"decision": "PASS"},
    }

    # 2. Valid minimal package (explicit offline unsigned diagnostic)
    res_valid = client.post(
        "/api/v1/evidence/verify-diagnostic",
        json={"package": pkg_payload, "require_signature": False, "require_scenario": False},
    )
    assert res_valid.status_code == 200
    assert res_valid.get_json()["verified"] is True
    assert res_valid.get_json()["verification_mode"] == "DIAGNOSTIC"
    assert res_valid.get_json()["authoritative"] is False
    assert res_valid.get_json()["certified"] is False

    # The authoritative endpoint cannot be downgraded by a request field.
    res_downgrade = client.post(
        "/api/v1/evidence/verify",
        json={"package": pkg_payload, "require_signature": False},
    )
    assert res_downgrade.status_code == 400
    assert "AuthoritativeVerificationRequiresSignature" in res_downgrade.get_json()["error"]

    res_untrusted_key = client.post(
        "/api/v1/evidence/verify",
        json={"package": pkg_payload, "public_key_pem": "caller-controlled-key"},
    )
    assert res_untrusted_key.status_code == 400
    assert (
        "AuthoritativeVerificationRequiresTrustedProviderInputs"
        in (res_untrusted_key.get_json()["error"])
    )

    # 2b. Fail-closed: default require_signature=True rejects missing trace bytes and signatures
    res_default = client.post(
        "/api/v1/evidence/verify",
        json={"package": pkg_payload},
    )
    assert res_default.status_code == 422
    assert res_default.get_json()["verified"] is False

    # 3. Trace byte parity check mismatch
    raw_b64 = base64.b64encode(b"some other trace content").decode("utf-8")
    res_mismatch = client.post(
        "/api/v1/evidence/verify",
        json={"package": pkg_payload, "raw_trace_bytes": raw_b64},
    )
    assert res_mismatch.status_code == 422
    assert res_mismatch.get_json()["verified"] is False
    assert any("TraceHashMismatch" in f for f in res_mismatch.get_json()["failures"])

    # 4. Invalid base64 trace
    res_bad_b64 = client.post(
        "/api/v1/evidence/verify",
        json={"package": pkg_payload, "raw_trace_bytes": "invalid base64!"},
    )
    assert res_bad_b64.status_code == 400


def test_evidence_package_unfinalized_run_reports_inconclusive(client, tmp_path: Path) -> None:
    """
    Verifies that an unfinalized run without finalization
    or computed outcome reports INCONCLUSIVE.
    """
    runs_dir = Path(config.RUN_LOG_DIR)
    run_id = f"run-inconclusive-{int(datetime.now(UTC).timestamp())}"

    from eval_runner.reference.local_run_store import LocalFileRunStore

    store = LocalFileRunStore(log_dir=runs_dir)
    store.create_run(run_id, scenario_id="test_scenario")

    now = datetime.now(UTC)
    store.append_events(
        run_id,
        [{"event": "node_execution", "timestamp": now.isoformat(), "data": {"passed": True}}],
    )

    res = client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res.status_code == 200
    pkg = res.get_json()
    assert pkg["verdict"]["verified_outcome"] == "PRELIMINARY"
    assert pkg["evidence_chain_valid"] is False


def test_evidence_routes_exhaustive_edge_cases(client, tmp_path: Path, monkeypatch) -> None:
    from unittest.mock import patch

    import eval_runner.console.routes.evidence as ev_module
    from eval_runner.reference.local_run_store import LocalFileRunStore

    runs_dir = Path(config.RUN_LOG_DIR)
    run_id = f"run-edge-{int(datetime.now(UTC).timestamp())}"

    store = LocalFileRunStore(log_dir=runs_dir)
    store.create_run(run_id, scenario_id="test_scenario")
    store.append_events(run_id, [{}])

    # Active context denial on get and list
    monkeypatch.setattr(ev_module, "_run_is_in_active_context", lambda rid: False)
    res_get_denied = client.get(f"/api/v1/evidence/packages/{run_id}")
    assert res_get_denied.status_code == 404

    store.save_run_manifest(run_id, {})
    res_list = client.get("/api/v1/evidence/packages")
    assert res_list.status_code == 200
    assert len(res_list.get_json()["packages"]) == 0
    monkeypatch.setattr(ev_module, "_run_is_in_active_context", lambda rid: True)

    # Invalid non-dict package payload in verify route
    res_verify_bad_pkg = client.post("/api/v1/evidence/verify", json={"package": "not-a-dict"})
    assert res_verify_bad_pkg.status_code == 400
    assert "package must be a JSON object" in res_verify_bad_pkg.get_json()["error"]

    # Invalid base64 in verify route
    res_verify_bad_b64 = client.post(
        "/api/v1/evidence/verify",
        json={"package": {}, "raw_trace_bytes": 12345},
    )
    assert res_verify_bad_b64.status_code == 400
    assert "Invalid base64 trace payload" in res_verify_bad_b64.get_json()["error"]

    # verify_trace_certificate ImportError and generic Exception handling
    (runs_dir / run_id / "run.jsonl").write_text("{}\n", encoding="utf-8")
    with patch.object(store, "get_manifest", return_value={"signature": "sig"}):
        with patch(
            "eval_runner.verifier.verify_trace_certificate", side_effect=ImportError("no verifier")
        ):
            pkg_imp_err = ev_module.build_verification_package(run_id, run_store=store)
            assert any(
                "not available" in e for e in pkg_imp_err["cryptographic_verification"]["errors"]
            )

        with patch(
            "eval_runner.verifier.verify_trace_certificate",
            side_effect=RuntimeError("verify crash"),
        ):
            pkg_err = ev_module.build_verification_package(run_id, run_store=store)
            assert any("verify crash" in e for e in pkg_err["cryptographic_verification"]["errors"])

    # Unsealed trace assertions are provider-owned observations for RCA.  They
    # remain PRELIMINARY and cannot be interpreted as certified assertions.
    (runs_dir / run_id / "run.jsonl").write_text(
        json.dumps({"event": "node_execution", "data": {"assertions": [{"passed": True}]}})
        + "\n"
        + json.dumps({"event": "run_end", "data": {}})
        + "\n",
        encoding="utf-8",
    )
    pkg_event_asserts = ev_module.build_verification_package(run_id, run_store=store)
    assert pkg_event_asserts["verdict"]["verified_outcome"] == "PRELIMINARY"
    assert pkg_event_asserts["verdict"]["assertions"] == [{"passed": True}]

    # Direct run_end assertions presence
    (runs_dir / run_id / "run.jsonl").write_text(
        json.dumps({"event": "run_end", "data": {"assertions": [{"passed": True}]}}) + "\n",
        encoding="utf-8",
    )
    pkg_direct_asserts = ev_module.build_verification_package(run_id, run_store=store)
    assert pkg_direct_asserts["verdict"]["verified_outcome"] == "PRELIMINARY"
    assert pkg_direct_asserts["verdict"]["assertions"] == [{"passed": True}]

    # Manifest data_block score fallback
    (runs_dir / run_id / "run.jsonl").write_text(
        json.dumps({"event": "run_end", "data": {"score": 0.88}}) + "\n",
        encoding="utf-8",
    )
    pkg_data_score = ev_module.build_verification_package(run_id, run_store=store)
    assert pkg_data_score["verdict"]["score"] is None

    # VERIFIED outcome score fallback to 1.0
    (runs_dir / run_id / "run.jsonl").write_text(
        json.dumps({"event": "run_end", "data": {}}) + "\n",
        encoding="utf-8",
    )
    with patch.object(store, "get_manifest", return_value={"signature": "sig"}):
        with patch(
            "eval_runner.verifier.verify_trace_certificate",
            return_value={
                "verified": True,
                "manifest_hash_match": True,
                "signer_identity": "signer",
            },
        ):
            pkg_verified_score = ev_module.build_verification_package(run_id, run_store=store)
            assert pkg_verified_score["verdict"]["verified_outcome"] == "PRELIMINARY"
            assert pkg_verified_score["verdict"]["score"] is None

    # Nonexistent RUN_LOG_DIR in list_verification_packages
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "nonexistent_runs_dir")
    res_nonexistent = client.get("/api/v1/evidence/packages")
    assert res_nonexistent.status_code == 200
