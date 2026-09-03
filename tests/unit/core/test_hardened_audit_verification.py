"""
tests/unit/core/test_hardened_audit_verification.py

Dedicated test suite verifying all hardened audit-defensibility and
trust boundary guarantees:
1. VerificationResult.attestation_grade is computed and evidence-derived.
2. compute_manifest_hash() covers manifest_id and metadata canonically.
3. index_events_by_seq() fails closed on duplicate sequence collisions.
4. FlightRecorder generates genuine cryptographic trace seal in trace_seal.json.
5. evaluate_scenario() enforces server-side preflight fingerprint validation.
6. compliance_packs test_pack fails closed when independent judge consensus is absent.
"""

import hashlib
import json
from unittest.mock import patch

import pytest
from flask import Flask

from agentv_runtime.contracts import (
    Verdict,
    VerificationResult,
)
from agentv_runtime.evidence_graph import index_events_by_seq
from agentv_runtime.manifest import ManifestBuilder
from eval_runner.console.routes.compliance_packs import compliance_packs_bp
from eval_runner.console.routes.scenarios import scenario_bp
from eval_runner.flight_recorder import FlightRecorderPlugin


def test_attestation_grade_evidence_derived():
    """Attestation grade requires VERIFIED verdict, live/hybrid mode, and signature verification."""
    # 1. Non-verified -> not_applicable
    vr_fail = VerificationResult(
        evaluation_run_id="run-1",
        scenario_version_id="sv-1",
        case_id="c-1",
        attempt_id="att-1",
        attempt_number=1,
        execution_mode="live",
        verdict=Verdict.NOT_VERIFIED,
        signature_verified=True,
        evidence_complete=True,
    )
    assert vr_fail.attestation_grade == "not_applicable"

    # 2. Live + Verified + Signed + Complete -> attested
    vr_attested = VerificationResult(
        evaluation_run_id="run-1",
        scenario_version_id="sv-1",
        case_id="c-1",
        attempt_id="att-1",
        attempt_number=1,
        execution_mode="live",
        verdict=Verdict.VERIFIED,
        signature_verified=True,
        evidence_complete=True,
    )
    assert vr_attested.attestation_grade == "attested"

    # 3. Live + Verified + Unsigned -> verifiable (never attested without signature)
    vr_unsigned = VerificationResult(
        evaluation_run_id="run-1",
        scenario_version_id="sv-1",
        case_id="c-1",
        attempt_id="att-1",
        attempt_number=1,
        execution_mode="live",
        verdict=Verdict.VERIFIED,
        signature_verified=False,
        evidence_complete=True,
    )
    assert vr_unsigned.attestation_grade == "verifiable"

    # 4. Live + Verified + Incomplete Evidence -> verifiable
    vr_incomplete = VerificationResult(
        evaluation_run_id="run-1",
        scenario_version_id="sv-1",
        case_id="c-1",
        attempt_id="att-1",
        attempt_number=1,
        execution_mode="live",
        verdict=Verdict.VERIFIED,
        signature_verified=True,
        evidence_complete=False,
    )
    assert vr_incomplete.attestation_grade == "verifiable"

    # 5. Simulated + Verified -> verifiable
    vr_sim = VerificationResult(
        evaluation_run_id="run-1",
        scenario_version_id="sv-1",
        case_id="c-1",
        attempt_id="att-1",
        attempt_number=1,
        execution_mode="simulated",
        verdict=Verdict.VERIFIED,
        signature_verified=True,
        evidence_complete=True,
    )
    assert vr_sim.attestation_grade == "verifiable"


def test_manifest_hash_includes_metadata_and_id():
    """compute_manifest_hash must cover manifest_id and metadata fields."""
    m1 = ManifestBuilder.build(
        scenario_data={"id": "scen_test", "version": "1.0.0"},
        tenant_id="t1",
        workspace_id="w1",
        metadata={"custom_audit_tag": "v1"},
    )
    m2 = ManifestBuilder.build(
        scenario_data={"id": "scen_test", "version": "1.0.0"},
        tenant_id="t1",
        workspace_id="w1",
        metadata={"custom_audit_tag": "v2"},  # Mutated metadata
    )

    hash1 = m1.compute_manifest_hash()
    hash2 = m2.compute_manifest_hash()

    assert hash1.startswith("sha3_256:")
    assert hash2.startswith("sha3_256:")
    # Mutating metadata MUST result in a different manifest hash
    assert hash1 != hash2


def test_evidence_graph_rejects_duplicate_sequence_numbers():
    """index_events_by_seq must fail closed on sequence collision."""
    good_events = [
        ({"_seq": 1, "event": "start"}, '{"_seq": 1, "event": "start"}'),
        ({"_seq": 2, "event": "step"}, '{"_seq": 2, "event": "step"}'),
    ]
    idx = index_events_by_seq(good_events)
    assert len(idx) == 2
    assert 1 in idx and 2 in idx

    duplicate_events = [
        ({"_seq": 1, "event": "start"}, '{"_seq": 1, "event": "start"}'),
        ({"_seq": 1, "event": "clobber"}, '{"_seq": 1, "event": "clobber"}'),
    ]
    with pytest.raises(ValueError, match="Duplicate sequence number _seq=1 detected"):
        index_events_by_seq(duplicate_events)


def test_flight_recorder_cryptographic_trace_seal(tmp_path):
    """finalize_run creates a genuine cryptographic trace digest in trace_seal.json."""
    fr = FlightRecorderPlugin(log_dir=tmp_path)
    run_id = "run-crypto-seal-01"

    # Log some events
    from eval_runner.events import CoreEvents, Event

    fr.handle_event(Event(name=CoreEvents.RUN_START, data={"run_id": run_id, "_seq": 1}))
    fr.handle_event(
        Event(name=CoreEvents.STEP_START, data={"run_id": run_id, "_seq": 2, "step": "done"})
    )
    fr.finalize_run(run_id=run_id)

    seal_path = tmp_path / run_id / "trace_seal.json"
    assert seal_path.exists()
    seal_data = json.loads(seal_path.read_text(encoding="utf-8"))

    assert seal_data["status"] == "finalized"
    assert seal_data["run_id"] == run_id
    assert seal_data["algorithm"] == "sha3_256"
    assert "trace_digest" in seal_data
    assert seal_data["trace_digest"].startswith("sha3_256:")
    assert seal_data["event_count"] >= 2


def test_server_side_preflight_fingerprint_enforcement(tmp_path, monkeypatch):
    """POST /api/v1/evaluate rejects mismatched preflight fingerprint."""
    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
    app = Flask(__name__)
    app.secret_key = "test_key"
    app.register_blueprint(scenario_bp, url_prefix="/api")

    scen_data = {
        "aes_version": 1.4,
        "metadata": {
            "id": "sec_01",
            "name": "Sec Scenario",
            "compliance_level": "Regulatory_Audit",
            "standards_registry": ["NIST_AI_RMF"],
            "description": "Desc",
            "complexity": "low",
            "capabilities": ["default_http_agent"],
        },
        "workflow": {
            "entry_point": "n1",
            "nodes": [
                {
                    "id": "n1",
                    "task_description": "start task",
                    "required_tools": [],
                    "success_criteria": [],
                }
            ],
            "edges": [],
        },
        "evaluation": {"assertions": []},
    }
    scen_file = tmp_path / "test_scen.json"
    scen_file.write_text(json.dumps(scen_data), encoding="utf-8")

    import eval_runner.loader
    from agentv_runtime.manifest import compute_scenario_hash

    loaded_scen = eval_runner.loader.load_scenario(str(scen_file))

    # Compute expected fingerprint matching check_execution_readiness
    raw_fp = {
        "scenario_id": "sec_01",
        "scen_hash": compute_scenario_hash(loaded_scen),
        "endpoint": "http://localhost:8000",
        "protocol": "http_rest",
        "max_turns": 10,
    }
    valid_fp = hashlib.sha3_256(json.dumps(raw_fp, sort_keys=True).encode("utf-8")).hexdigest()

    client = app.test_client()

    # 1. Invalid fingerprint -> 400 Mismatch
    res_mismatch = client.post(
        "/api/v1/evaluate",
        json={"path": str(scen_file), "preflight_fingerprint": "bad_fingerprint_hash_000"},
    )
    assert res_mismatch.status_code == 400
    assert "PreflightFingerprintMismatch" in res_mismatch.get_json()["error"]

    # 2. Matching fingerprint -> 200 Started
    with patch(
        "eval_runner.reference.inprocess_backend.InProcessExecutionBackend.submit",
        return_value="queued",
    ):
        res_valid = client.post(
            "/api/v1/evaluate",
            json={"path": str(scen_file), "preflight_fingerprint": valid_fp},
        )
        assert res_valid.status_code == 200
        assert res_valid.get_json()["status"] == "started"


def test_compliance_pack_fail_closed_on_missing_consensus(tmp_path, monkeypatch):
    """Compliance pack checks do not fall back to author compliance_score."""
    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
    root = tmp_path / "root"
    root.mkdir()
    runs = root / "runs"
    runs.mkdir()
    reports = root / "reports"
    reports.mkdir()
    certs_dir = reports / "certificates"
    certs_dir.mkdir(parents=True)
    packs_dir = root / "results" / "compliance_packs"
    packs_dir.mkdir(parents=True)

    from eval_runner import config

    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs)
    monkeypatch.setattr(config, "REPORTS_DIR", reports)
    monkeypatch.setattr("eval_runner.console.routes.compliance_packs.PACKS_DIR", packs_dir)

    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(compliance_packs_bp, url_prefix="/api")

    run_id = "test_run_fail_closed"
    run_dir = runs / run_id
    run_dir.mkdir()
    trace = run_dir / "run.jsonl"
    trace.write_text(json.dumps({"run_id": run_id, "status": "COMPLETED"}) + "\n", encoding="utf-8")

    # Author supplied a compliance_score float, but NO independent consensus evaluation
    vc_file = certs_dir / f"{run_id}_vc.json"
    vc_file.write_text(
        json.dumps({"compliance_score": 1.0}),  # Self-attested score only
        encoding="utf-8",
    )

    pack = {
        "id": "FAIL-CLOSED-PACK",
        "name": "Fail Closed Pack",
        "checks": [
            {"type": "rubric_required", "params": {"rubric": "safety_rubric", "min_score": 0.8}},
            {"type": "ija_threshold", "params": {"min_value": 0.75}},
        ],
        "version": 1,
    }
    (packs_dir / "FAIL-CLOSED-PACK.json").write_text(json.dumps(pack), encoding="utf-8")

    with patch(
        "eval_runner.console.routes.compliance_packs.resolve_trace_path", return_value=trace
    ):
        client = app.test_client()
        res = client.post(f"/api/v1/compliance-packs/FAIL-CLOSED-PACK/test?run_id={run_id}")
        data = res.get_json()

        assert res.status_code == 200
        assert data["overall_pass"] is False
        # Both checks must FAIL because independent judge consensus is absent
        assert data["checks"][0]["status"] == "FAIL"
        assert "not evaluated" in data["checks"][0]["details"]
        assert data["checks"][1]["status"] == "FAIL"
        assert "missing" in data["checks"][1]["details"].lower()


def test_verification_package_canonical_hash():
    """VerificationPackage must compute deterministic SHA3-256 root hash."""
    from agentv_runtime.package import VerificationPackage

    pkg1 = VerificationPackage(
        scenario_id="scen_audit_01",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:abc1",
        manifest_id="mf_audit_01",
        manifest_hash="sha3_256:def1",
        execution_identity={"runtime_version": "1.4.0"},
        trace_hash="sha3_256:1234",
        trace_seal={"digest": "sha3_256:1234", "event_count": 10},
        evidence_root_hash="sha3_256:5678",
        required_oracle_ids=["oracle_1", "oracle_2"],
        executed_oracle_results=[{"metric": "oracle_1", "passed": True}],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )
    h1 = pkg1.compute_package_hash()
    assert len(h1) == 64

    # Package hash must be deterministic across instances with same data
    pkg2 = VerificationPackage.from_dict(pkg1.to_dict())
    assert pkg2.compute_package_hash() == h1


def test_node_verdict_conjunctive_success():
    """NodeVerdict.overall must require all components to be explicitly pass or not_applicable."""
    from eval_runner.execution_ir import NodeVerdict

    # 1. All pass -> success
    v_pass = NodeVerdict(execution="success", verification="pass", policy="pass", parity="pass")
    assert v_pass.overall == "success"
    assert v_pass.success is True

    # 2. Unexpected/unverified string -> fail-closed (never success)
    v_unverified = NodeVerdict(
        execution="success", verification="unknown_string", policy="pass", parity="pass"
    )
    assert v_unverified.overall == "verification_failed"
    assert v_unverified.success is False

    # 3. Policy denied -> policy_denied
    v_denied = NodeVerdict(execution="success", verification="pass", policy="denied", parity="pass")
    assert v_denied.overall == "policy_denied"
    assert v_denied.success is False


def test_verification_authority_package_validation():
    """VerificationAuthority validates package consistency and missing required oracles."""
    from agentv_runtime.package import VerificationPackage
    from eval_runner.verifier import VerificationAuthority

    # Valid package with all required oracles executed
    pkg_valid = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        manifest_id="m1",
        manifest_hash="sha3_256:man",
        execution_identity={"evaluator": "test"},
        trace_hash="sha3_256:trace",
        trace_seal={"digest": "sha3_256:trace"},
        evidence_root_hash="sha3_256:ev",
        required_oracle_ids=["req_oracle_1"],
        executed_oracle_results=[{"metric": "req_oracle_1", "passed": True}],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )
    res_valid = VerificationAuthority.verify_package(pkg_valid, require_signature=False)
    assert res_valid["verified"] is True
    assert res_valid["status"] == "CERTIFIED"

    # Incomplete package: missing required oracle
    pkg_missing_oracle = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        manifest_id="m1",
        manifest_hash="sha3_256:man",
        execution_identity={"evaluator": "test"},
        trace_hash="sha3_256:trace",
        trace_seal={"digest": "sha3_256:trace"},
        evidence_root_hash="sha3_256:ev",
        required_oracle_ids=["req_oracle_1", "missing_oracle_2"],
        executed_oracle_results=[{"metric": "req_oracle_1", "passed": True}],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )
    res_missing = VerificationAuthority.verify_package(pkg_missing_oracle, require_signature=False)
    assert res_missing["verified"] is False
    assert res_missing["status"] == "UNVERIFIED"
    assert any("MissingRequiredOracles" in f for f in res_missing["failures"])


def test_contracts_verification_result_fail_closed_defaults():
    """VerificationResult defaults signature_verified and evidence_complete to False."""
    vr = VerificationResult(
        evaluation_run_id="run-def",
        scenario_version_id="sv-def",
        case_id="c-def",
        attempt_id="att-def",
        attempt_number=1,
        execution_mode="live",
        verdict=Verdict.VERIFIED,
    )
    assert vr.signature_verified is False
    assert vr.evidence_complete is False
    assert vr.attestation_grade == "verifiable"


def test_verification_authority_split_and_manifest_tamper_detection():
    """P0.3: Split package verification and manifest hash tamper detection."""
    import hashlib

    from agentv_runtime.evidence_graph import (
        build_evidence_graph_from_events,
        compute_evidence_graph_root,
    )
    from agentv_runtime.manifest import ExecutionManifest
    from agentv_runtime.package import VerificationPackage
    from eval_runner.verifier import VerificationAuthority

    manifest = ExecutionManifest(
        manifest_id="m1",
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        tenant_id="t1",
        workspace_id="ws1",
        agent_config={"model": "gpt-4"},
        runtime_config={},
        environment={},
        created_at="2026-09-01T00:00:00Z",
        created_by="system",
        metadata={},
    )
    m_hash = manifest.compute_manifest_hash()

    raw_trace_bytes = b'{"event": "run_start", "_seq": 1}\n{"event": "run_end", "_seq": 2}\n'
    trace_hash = f"sha3_256:{hashlib.sha3_256(raw_trace_bytes).hexdigest()}"
    raw_events = [
        {"event": "run_start", "_seq": 1, "data": {}},
        {"event": "run_end", "_seq": 2, "data": {}},
    ]
    ev_graph = build_evidence_graph_from_events(raw_events)
    ev_root = compute_evidence_graph_root(ev_graph)

    pkg = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        manifest_id="m1",
        manifest_hash=m_hash,
        execution_identity={"evaluator": "test"},
        trace_hash=trace_hash,
        trace_seal={"digest": trace_hash},
        evidence_root_hash=ev_root,
        required_oracle_ids=["oracle_1"],
        executed_oracle_results=[{"metric": "oracle_1", "passed": True}],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )

    # 1. verify_package_signature_only without signature -> UNSIGNED
    sig_res = VerificationAuthority.verify_package_signature_only(pkg)
    assert sig_res["verified"] is False
    assert sig_res["status"] == "UNSIGNED"

    # 2. verify_package_artifacts with matching evidence -> CERTIFIED
    art_res = VerificationAuthority.verify_package_artifacts(
        pkg,
        raw_trace_bytes=raw_trace_bytes,
        raw_trace_events=raw_events,
        canonical_manifest=manifest,
        require_signature=False,
    )
    assert art_res["verified"] is True
    assert art_res["status"] == "CERTIFIED"

    # 3. Tamper manifest only: change tenant_id -> ManifestHashMismatch -> UNVERIFIED
    tampered_manifest = ExecutionManifest(
        manifest_id="m1",
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        tenant_id="tampered_tenant",
        workspace_id="ws1",
        agent_config={"model": "gpt-4"},
        runtime_config={},
        environment={},
        created_at="2026-09-01T00:00:00Z",
        created_by="system",
        metadata={},
    )
    tampered_res = VerificationAuthority.verify_package_artifacts(
        pkg,
        raw_trace_bytes=raw_trace_bytes,
        raw_trace_events=raw_events,
        canonical_manifest=tampered_manifest,
        require_signature=False,
    )
    assert tampered_res["verified"] is False
    assert tampered_res["status"] == "UNVERIFIED"
    assert any("ManifestHashMismatch" in f for f in tampered_res["failures"])

    # 4. Missing raw trace bytes or events -> fails closed
    missing_bytes_res = VerificationAuthority.verify_package_artifacts(
        pkg,
        raw_trace_bytes=None,  # type: ignore
        raw_trace_events=raw_events,
        canonical_manifest=manifest,
        require_signature=False,
    )
    assert missing_bytes_res["verified"] is False
    assert any("TraceBytesMissing" in f for f in missing_bytes_res["failures"])


def test_certification_outcome_extraction_authoritative_precedence(tmp_path):
    """R1 / S1: Authoritative failure decision is never bypassed by passed=True."""
    import json

    from eval_runner.services.certification import CertificationService

    # Trace containing passed=True but authoritative failure decision="POLICY_BREACH"
    trace_file = tmp_path / "run.jsonl"
    records = [
        {"event": "run_start", "_seq": 1},
        {
            "event": "evaluation_verdict",
            "passed": True,  # Non-authoritative heuristic field
            "decision": "POLICY_BREACH",  # Authoritative terminal failure
            "verdict": "FAIL",
            "score": 0.0,
            "_seq": 2,
        },
        {"event": "run_end", "_seq": 3},
    ]
    trace_file.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

    status, score = CertificationService.extract_computed_run_outcome(tmp_path, trace_file)
    assert status == "fail"
    assert score == 0.0


def test_zero_config_bootstrap_admin_key_and_cookie_security(tmp_path):
    """Component 1: Zero-config bootstrap key generation and secure session cookie flags."""
    from unittest.mock import patch

    from eval_runner import config
    from eval_runner.console.app import create_app

    keys_dir = tmp_path / ".aes" / "keys"
    boot_file = keys_dir / "bootstrap.key"

    with (
        patch.object(config, "PROJECT_ROOT", tmp_path),
        patch.object(config, "SERVICE_API_KEY", ""),
        patch.object(config, "DASHBOARD_API_KEY", ""),
        patch.dict(
            "os.environ",
            {
                "AGENTV_ENV": "development",
                "SERVICE_API_KEY": "",
                "DASHBOARD_API_KEY": "",
            },
            clear=False,
        ),
    ):
        # Create app without pre-configured keys
        app = create_app()
        assert boot_file.exists()
        generated_key = boot_file.read_text(encoding="utf-8").strip()
        assert len(generated_key) >= 32
        assert config.SERVICE_API_KEY == generated_key
        assert config.DASHBOARD_API_KEY == generated_key
        assert app.config["SESSION_COOKIE_HTTPONLY"] is True
        assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_verify_package_artifacts_scenario_mismatch_detected():
    """Verify verify_package_artifacts rejects mismatched scenario data."""
    from agentv_runtime.package import VerificationPackage
    from eval_runner.verifier import VerificationAuthority

    pkg = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:original_hash",
        manifest_id="m1",
        manifest_hash="sha3_256:manifest_hash",
        execution_identity={"evaluator": "test"},
        trace_hash="sha3_256:trace",
        trace_seal={"digest": "sha3_256:trace"},
        evidence_root_hash="sha3_256:ev",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )
    mismatched_scenario = {"id": "mismatched_scenario_xyz", "version": "99.0"}
    res = VerificationAuthority.verify_package_artifacts(
        pkg,
        raw_trace_bytes=b"",
        raw_trace_events=[],
        canonical_manifest=None,
        scenario_data=mismatched_scenario,
        require_signature=False,
    )
    assert res["verified"] is False
    assert any("ScenarioHashMismatch" in f for f in res["failures"])


def test_verify_trace_certificate_incomplete_provenance_fails(tmp_path):
    """Verify verify_trace_certificate fails if is_complete_provenance is False."""
    import json
    from unittest.mock import patch

    from eval_runner import config
    from eval_runner.verifier import TraceVerifier

    trace_file = tmp_path / "test.jsonl"
    trace_file.write_text('{"event": "start", "_seq": 1}\n', encoding="utf-8")
    actual_hash = TraceVerifier.compute_signature(trace_file)

    manifest_file = tmp_path / "test_manifest.json"
    manifest_data = {
        "vc_version": "3.0.0",
        "trace_hash": actual_hash,
        "evidence_root_hash": "sha3_256:fake_root",
        "trace_path": str(trace_file),
        "timestamp": "2026-09-01T00:00:00+00:00",
        "signature": "fake_sig",
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    with (
        patch.object(config, "PROJECT_ROOT", tmp_path),
        patch(
            "agentv_runtime.evidence_graph.compute_evidence_graph_root",
            return_value="sha3_256:fake_root",
        ),
        patch(
            "agentv_runtime.evidence_graph.build_evidence_graph_from_events",
            return_value={"is_complete_provenance": False},
        ),
    ):
        is_valid = TraceVerifier.verify_trace(
            trace_path=str(trace_file),
            manifest_path=str(manifest_file),
        )
        assert is_valid is False


def test_verification_authority_verify_package_scenario_hash_match():
    """
    Verify VerificationAuthority.verify_package passes scenario check when scenario_data matches.
    Kills mutant 125: if computed_scen_hash != pkg.scenario_hash -> (==).
    """
    from agentv_runtime.manifest import compute_scenario_hash
    from agentv_runtime.package import VerificationPackage
    from eval_runner.verifier import VerificationAuthority

    scen = {"scenario_id": "test_scen_pkg", "steps": [{"step": 1}]}
    scen_hash = compute_scenario_hash(scen)
    pkg = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        manifest_id="m1",
        manifest_hash="sha3_256:man",
        execution_identity={"evaluator": "test"},
        trace_hash="sha3_256:trace",
        trace_seal={"digest": "sha3_256:trace"},
        evidence_root_hash="sha3_256:ev",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )
    res = VerificationAuthority.verify_package(pkg, scenario_data=scen, require_signature=False)
    assert not any("ScenarioHashMismatch" in f for f in res["failures"])


def test_verification_authority_artifacts_missing_provenance_defaults_true():
    """
    Verify verify_package_artifacts defaults is_complete_provenance to True
    when missing from graph dict.
    Kills mutant 158: if not ev_graph.get('is_complete_provenance', True) -> False.
    """
    import hashlib
    from unittest.mock import patch

    from agentv_runtime.package import VerificationPackage
    from eval_runner.verifier import VerificationAuthority

    raw_bytes = b'{"event": "start", "_seq": 1}\n'
    raw_hash = f"sha3_256:{hashlib.sha3_256(raw_bytes).hexdigest()}"
    dummy_root = "sha3_256:0000000000000000000000000000000000000000000000000000000000000000"
    pkg = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        manifest_id="man-01",
        manifest_hash="sha3_256:man",
        execution_identity={"evaluator": "test"},
        trace_hash=raw_hash,
        trace_seal={"digest": raw_hash},
        evidence_root_hash=dummy_root,
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )
    graph_without_key = {"root_hash": dummy_root}
    with (
        patch(
            "agentv_runtime.evidence_graph.compute_evidence_graph_root",
            return_value=dummy_root,
        ),
        patch(
            "agentv_runtime.evidence_graph.build_evidence_graph_from_events",
            return_value=graph_without_key,
        ),
    ):
        res = VerificationAuthority.verify_package_artifacts(
            pkg,
            raw_trace_bytes=raw_bytes,
            raw_trace_events=[{"event": "start", "_seq": 1}],
            canonical_manifest=None,
            require_signature=False,
        )
        assert not any("DirectProvenanceViolation" in f for f in res["failures"])
