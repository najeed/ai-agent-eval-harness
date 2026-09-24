"""
tests/unit/core/test_trace_integrity_and_lifecycle_gates.py

Unit and integration tests for trace stream integrity, fail-closed lifecycle gates,
split evidence chain rejection, unsigned package rejection, and certification
identity auto-provisioning guards.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agentv_runtime.evidence_graph import (
    build_evidence_graph_from_events,
    compute_evidence_graph_root,
    index_events_by_seq,
)
from agentv_runtime.manifest import ExecutionManifest
from agentv_runtime.package import VerificationPackage
from eval_runner import config
from eval_runner.certification_lock import PerRunCertificationLock
from eval_runner.identity import IdentityService
from eval_runner.run_lifecycle import (
    RunLifecycleState,
    get_run_lifecycle_state,
)
from eval_runner.verifier import (
    CertificationFailedError,
    TraceVerifier,
    VerificationAuthority,
)


def test_duplicate_sequence_numbers_fail_closed():
    """Duplicate _seq numbers in trace events must raise ValueError during index creation."""
    events_with_lines = [
        ({"event": "run_start", "_seq": 1}, '{"event": "run_start", "_seq": 1}'),
        (
            {"event": "assertion_evaluated", "_seq": 1, "assertion": "o1", "passed": True},
            '{"event": "assertion_evaluated", "_seq": 1, "assertion": "o1", "passed": true}',
        ),
    ]
    with pytest.raises(ValueError, match="Duplicate sequence number _seq=1 detected"):
        index_events_by_seq(events_with_lines)


def test_trace_stream_split_chain_violation_rejection():
    """Reject split-evidence attacks where raw_trace_events count diverges from raw_trace_bytes."""
    raw_trace_bytes = (
        b'{"event": "run_start", "_seq": 1}\n'
        b'{"event": "assertion_evaluated", "_seq": 2, "assertion": "oracle_1", "passed": true}\n'
        b'{"event": "run_end", "_seq": 3}\n'
    )
    trace_hash = f"sha3_256:{hashlib.sha3_256(raw_trace_bytes).hexdigest()}"

    split_raw_events = [
        {"event": "run_start", "_seq": 1},
        {"event": "assertion_evaluated", "_seq": 2, "assertion": "oracle_1", "passed": True},
        {
            "event": "extra_fabricated_assertion",
            "_seq": 3,
            "assertion": "oracle_2",
            "passed": True,
        },
        {"event": "run_end", "_seq": 4},
    ]

    parsed_stream = [
        (json.loads(line), line.decode("utf-8").strip())
        for line in raw_trace_bytes.splitlines()
        if line.strip()
    ]
    ev_graph = build_evidence_graph_from_events(parsed_stream, required_oracle_ids=["oracle_1"])
    ev_root = compute_evidence_graph_root(ev_graph)

    manifest = ExecutionManifest(
        manifest_id="m1",
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        tenant_id="t1",
        workspace_id="ws1",
        agent_config={},
        runtime_config={},
        environment={},
        created_at="2026-09-01T00:00:00Z",
        created_by="system",
        metadata={},
    )

    pkg = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        manifest_id="m1",
        manifest_hash=manifest.compute_manifest_hash(),
        execution_identity={"worker": "w1"},
        trace_hash=trace_hash,
        trace_seal={"digest": trace_hash},
        evidence_root_hash=ev_root,
        required_oracle_ids=["oracle_1"],
        executed_oracle_results=[
            {
                "oracle_id": "oracle_1",
                "outcome": "PASS",
                "resolver": "builtin_v1",
                "evidence_refs": ["ref_1"],
            }
        ],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )

    res = VerificationAuthority.verify_package_artifacts(
        pkg,
        raw_trace_bytes=raw_trace_bytes,
        raw_trace_events=split_raw_events,
        canonical_manifest=manifest,
        require_signature=False,
    )
    assert res["verified"] is False
    assert any("TraceStreamSplitChainViolation" in f for f in res["failures"])


def test_fail_closed_lifecycle_transition_in_certification_lock(tmp_path):
    """Lifecycle transition failure in PerRunCertificationLock must close fd and unlink lock."""
    run_id = "run-fail-lock-01"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    with patch.object(config, "RUN_LOG_DIR", tmp_path):
        lock = PerRunCertificationLock(run_id=run_id)
        with patch(
            "eval_runner.run_lifecycle.transition_run_lifecycle",
            side_effect=RuntimeError("Simulated lifecycle store failure"),
        ):
            with pytest.raises(RuntimeError, match="Simulated lifecycle store failure"):
                lock.acquire()

        assert lock._fd is None
        assert not lock.lock_file.exists()


def test_fail_closed_lifecycle_transition_in_sign_trace(tmp_path):
    """sign_trace must fail closed and rollback if transitioning to FINALIZING fails."""
    run_id = "run-fail-sign-01"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_file = run_dir / "run.jsonl"
    trace_file.write_text(
        '{"event": "run_start", "_seq": 1}\n{"event": "run_end", "_seq": 2, "decision": "PASS"}\n',
        encoding="utf-8",
    )

    with (
        patch.object(config, "PROJECT_ROOT", tmp_path),
        patch.object(config, "RUN_LOG_DIR", tmp_path),
        patch(
            "eval_runner.run_lifecycle.transition_run_lifecycle",
            side_effect=RuntimeError("Lifecycle backend offline"),
        ),
    ):
        with pytest.raises(CertificationFailedError, match="LifecycleTransitionFailed"):
            TraceVerifier.sign_trace(
                trace_path=str(trace_file),
                run_id=run_id,
            )


def test_unsigned_verification_package_rejected_in_verify_trace(tmp_path):
    """verify_trace must reject manifests embedding an unsigned VerificationPackage."""
    run_id = "run-unsigned-pkg-01"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_file = run_dir / "run.jsonl"
    trace_content = (
        '{"event": "run_start", "_seq": 1}\n{"event": "run_end", "_seq": 2, "decision": "PASS"}\n'
    )
    trace_file.write_text(trace_content, encoding="utf-8")

    trace_hash = TraceVerifier.compute_signature(trace_file)

    pkg_unsigned = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        manifest_id="m1",
        manifest_hash="sha3_256:m",
        execution_identity={"run_id": run_id},
        trace_hash=trace_hash,
        trace_seal={"digest": trace_hash},
        evidence_root_hash="sha3_256:ev",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
        signature=None,  # Unsigned!
    )

    from cryptography.hazmat.primitives.asymmetric import ed25519

    from agentv_runtime.canonical import canonical_json_encode

    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()

    manifest_data = {
        "vc_version": "3.0.0",
        "harness_version": "2.0.0",
        "timestamp": "2026-09-01T00:00:00Z",
        "run_id": run_id,
        "trace_hash": trace_hash,
        "verification_package": pkg_unsigned.to_dict(),
    }
    manifest_bytes = canonical_json_encode(manifest_data)
    sig_hex = priv_key.sign(manifest_bytes).hex()

    manifest_data["provenance_chain"] = [
        {
            "identity": "system_id",
            "role": "Evaluator",
            "signature": sig_hex,
            "algorithm": "ED25519",
        }
    ]
    manifest_file = run_dir / "run_manifest.json"
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    with (
        patch.object(config, "PROJECT_ROOT", tmp_path),
        patch.object(config, "RUN_LOG_DIR", tmp_path),
        patch("eval_runner.identity.IdentityService.get_public_key", return_value=pub_key),
    ):
        is_valid = TraceVerifier.verify_trace(
            trace_path=str(trace_file),
            manifest_path=str(manifest_file),
            verify_ledger=False,
        )
        assert is_valid is False


def test_certification_identities_auto_provisioning_blocked(tmp_path):
    """IdentityService must refuse auto-provisioning for any certification identity."""
    certification_identities = [
        "system_id",
        "eval_kernel",
        "certification_authority",
        "evaluator",
        "attestation_signer",
        "cert_authority_v1",
    ]
    with (
        patch.object(config, "ALLOW_SYSTEM_IDENTITY_PROVISIONING", False),
        patch.object(config, "TRUST_ROOT", tmp_path / "empty_trust_root"),
    ):
        for ident in certification_identities:
            with pytest.raises(
                PermissionError, match="Security Policy Violation: Auto-provisioning"
            ):
                IdentityService.get_private_key(ident, auto_provision=True)


def test_run_manifest_existence_does_not_mark_run_as_sealed(tmp_path):
    """Existence of run_manifest.json must NOT mark an unsealed run as SEALED."""
    run_id = "run-open-with-manifest"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = run_dir / "run_manifest.json"
    manifest_file.write_text('{"manifest_id": "m1"}', encoding="utf-8")

    with patch.object(config, "RUN_LOG_DIR", tmp_path):
        state = get_run_lifecycle_state(run_id)
        assert state == RunLifecycleState.OPEN
        assert state != RunLifecycleState.SEALED


def test_manifest_to_json_compatible_types_and_errors():
    """Test all branches of _to_json_compatible in manifest.py."""
    from agentv_runtime.manifest import _to_json_compatible

    # 1. Reject callables
    with pytest.raises(ValueError, match="LossyScenarioError: Unsupported callable object"):
        _to_json_compatible(lambda x: x)

    # 2. Sort set items deterministically
    sorted_set = _to_json_compatible({"banana", "apple", "cherry"})
    assert sorted_set == ["apple", "banana", "cherry"]

    # 3. Handle object with .to_dict()
    class CustomObj:
        def to_dict(self):
            return {"key": "val", "nested_set": {"z", "a"}}

    res_dict = _to_json_compatible(CustomObj())
    assert res_dict == {"key": "val", "nested_set": ["a", "z"]}

    # 4. Reject arbitrary objects: their string representation is not a
    # cross-process canonical certification input.
    class Arbitrary:
        def __str__(self):
            return "arbitrary_value"

    with pytest.raises(TypeError, match="Unsupported non-canonical value"):
        _to_json_compatible(Arbitrary())


def test_compute_preflight_fingerprint_all_fields_and_permutations():
    """Test compute_preflight_fingerprint parameter branches and sensitivity."""
    from agentv_runtime.manifest import compute_preflight_fingerprint

    base_pfp = compute_preflight_fingerprint(
        scenario_id="scen-01",
        scen_hash="sha3_256:abc",
        endpoint="http://agent:8000",
        protocol="http_rest",
        max_turns=10,
        agent_config={"model": "gpt-4o"},
        runtime_config={"signing_backend": "ed25519"},
        scenario_version="1.2.0",
        tenant_id="tenant-alpha",
        workspace_id="ws-beta",
        seed=42,
        execution_mode="live",
        evaluators=["evaluator_1", "evaluator_2"],
    )
    assert isinstance(base_pfp, str) and len(base_pfp) == 64

    # Changing tenant alters fingerprint
    diff_tenant = compute_preflight_fingerprint(
        scenario_id="scen-01",
        scen_hash="sha3_256:abc",
        tenant_id="tenant-gamma",
    )
    assert diff_tenant != base_pfp

    # Changing execution_mode alters fingerprint
    diff_mode = compute_preflight_fingerprint(
        scenario_id="scen-01",
        scen_hash="sha3_256:abc",
        execution_mode="hybrid",
    )
    assert diff_mode != base_pfp

    # Changing evaluators alters fingerprint
    diff_eval = compute_preflight_fingerprint(
        scenario_id="scen-01",
        scen_hash="sha3_256:abc",
        evaluators=["other_eval"],
    )
    assert diff_eval != base_pfp

    # Fallback populates endpoint and protocol in agent_config when absent
    pfp_override = compute_preflight_fingerprint(
        scenario_id="scen-01",
        endpoint="http://override:9000",
        protocol="GRPC",
        max_turns=25,
        agent_config={},
        runtime_config={},
    )
    assert isinstance(pfp_override, str)


def test_verifier_sign_trace_fail_closed_on_sealed_transition(tmp_path):
    """sign_trace must fail closed if transitioning to SEALED fails."""
    run_id = "run-fail-sealed-01"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_file = run_dir / "run.jsonl"
    trace_file.write_text(
        '{"event": "run_start", "_seq": 1}\n{"event": "run_end", "_seq": 2, "decision": "PASS"}\n',
        encoding="utf-8",
    )

    from eval_runner.run_lifecycle import transition_run_lifecycle as original_transition

    def mock_transition(rid, state, metadata=None):
        if state == RunLifecycleState.SEALED:
            raise RuntimeError("Database connection severed during SEALED transition")
        return original_transition(rid, state, metadata)

    with (
        patch.object(config, "PROJECT_ROOT", tmp_path),
        patch.object(config, "RUN_LOG_DIR", tmp_path),
        patch("eval_runner.run_lifecycle.transition_run_lifecycle", side_effect=mock_transition),
    ):
        with pytest.raises(CertificationFailedError, match="LifecycleTransitionFailed"):
            TraceVerifier.sign_trace(
                trace_path=str(trace_file),
                run_id=run_id,
            )


def test_verifier_sign_trace_fail_closed_on_unusable_signing_capability(tmp_path):
    """sign_trace must fail closed if identity key exposes no usable signing capability."""
    run_id = "run-fail-capability-01"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace_file = run_dir / "run.jsonl"
    trace_file.write_text(
        '{"event": "run_start", "_seq": 1}\n{"event": "run_end", "_seq": 2, "decision": "PASS"}\n',
        encoding="utf-8",
    )

    class DummyNonSigningKey:
        pass

    with (
        patch.object(config, "PROJECT_ROOT", tmp_path),
        patch.object(config, "RUN_LOG_DIR", tmp_path),
        patch(
            "eval_runner.identity.IdentityService.get_private_key",
            return_value=DummyNonSigningKey(),
        ),
    ):
        with pytest.raises(CertificationFailedError, match="exposes no usable signing capability"):
            TraceVerifier.sign_trace(
                trace_path=str(trace_file),
                run_id=run_id,
            )


def test_verify_package_artifacts_trace_hash_mismatch_and_parsing_failure():
    """verify_package_artifacts must report TraceHashMismatch and TraceStreamParsingFailed."""
    raw_trace_bytes = b'{"event": "run_start", "_seq": 1}\n'
    pkg = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        manifest_id="m1",
        manifest_hash="sha3_256:man",
        execution_identity={"worker": "w1"},
        trace_hash="sha3_256:wronghash00000000000000000000000000000000000000000000000000000000",
        trace_seal={
            "digest": "sha3_256:wronghash00000000000000000000000000000000000000000000000000000000"
        },
        evidence_root_hash="sha3_256:ev",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )

    res = VerificationAuthority.verify_package_artifacts(
        pkg,
        raw_trace_bytes=raw_trace_bytes,
        raw_trace_events=[{"event": "run_start", "_seq": 1}],
        canonical_manifest=None,
        require_signature=False,
    )
    assert res["verified"] is False
    assert any("TraceHashMismatch" in f for f in res["failures"])

    # Malformed UTF-8 trace bytes
    bad_bytes = b"\xff\xfe\x00\x01\x80\x81"
    bad_hash = f"sha3_256:{hashlib.sha3_256(bad_bytes).hexdigest()}"
    pkg_bad = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        manifest_id="m1",
        manifest_hash="sha3_256:man",
        execution_identity={"worker": "w1"},
        trace_hash=bad_hash,
        trace_seal={"digest": bad_hash},
        evidence_root_hash="sha3_256:ev",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )
    res_bad = VerificationAuthority.verify_package_artifacts(
        pkg_bad,
        raw_trace_bytes=bad_bytes,
        raw_trace_events=[],
        canonical_manifest=None,
        require_signature=False,
    )
    assert any("TraceStreamParsingFailed" in f for f in res_bad["failures"])


def test_verify_package_trace_hash_mismatch_and_stream_events_fallback():
    """verify_package must report TraceHashMismatch and handle raw_trace_events fallback."""
    raw_trace_bytes = b'{"event": "run_start", "_seq": 1}\n'
    pkg = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        manifest_id="m1",
        manifest_hash="sha3_256:man",
        execution_identity={"worker": "w1"},
        trace_hash="sha3_256:wronghash00000000000000000000000000000000000000000000000000000000",
        trace_seal={
            "digest": "sha3_256:wronghash00000000000000000000000000000000000000000000000000000000"
        },
        evidence_root_hash="sha3_256:ev",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )
    res = VerificationAuthority.verify_package(
        pkg,
        raw_trace_bytes=raw_trace_bytes,
        require_signature=False,
    )
    assert res["verified"] is False
    assert any("TraceHashMismatch" in f for f in res["failures"])

    # Exercise raw_trace_events with dict and non-dict items when raw_trace_bytes is None
    events = [{"event": "run_start", "_seq": 1}, "plain_string_event"]
    res_evs = VerificationAuthority.verify_package(
        pkg,
        raw_trace_bytes=None,
        raw_trace_events=events,
        require_signature=False,
    )
    assert isinstance(res_evs, dict)


def test_certification_lock_os_error_resilience(tmp_path):
    """
    Certification lock acquire must survive OSErrors during fd close
    and file unlink on transition failure.
    """
    run_id = "run-os-err-lock-01"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    with patch.object(config, "RUN_LOG_DIR", tmp_path):
        lock = PerRunCertificationLock(run_id=run_id)
        with (
            patch(
                "eval_runner.run_lifecycle.transition_run_lifecycle",
                side_effect=RuntimeError("Lifecycle crash"),
            ),
            patch("os.close", side_effect=OSError("EBADF")),
            patch("pathlib.Path.unlink", side_effect=OSError("EPERM")),
        ):
            with pytest.raises(RuntimeError, match="Lifecycle crash"):
                lock.acquire()

        assert lock._fd is None


def test_resolve_execution_configs_comprehensive():
    """Test resolve_execution_configs edge cases, precedence, and custom configuration merging."""
    from eval_runner.console.routes.scenarios import resolve_execution_configs

    # 1. Defaults when empty
    ac_def, rc_def = resolve_execution_configs({}, None)
    assert ac_def["agent_name"] == "default_agent"
    assert ac_def["protocol"] == "http_rest"
    assert ac_def["endpoint"] == "http://localhost:8000"
    assert ac_def["model"] == "gpt-4o"
    assert rc_def["max_turns"] == 10
    assert rc_def["signing_backend"] == "ed25519"
    assert rc_def["policy_evaluator"] == "standard"

    # 2. Scenario data precedence and custom keys
    scen_data = {
        "metadata": {"agent_name": "scen_agent", "endpoint": "http://scen:8000"},
        "agent_config": {"model": "claude-3-5-sonnet", "custom_agent_opt": 123},
        "runtime_config": {"max_turns": 20, "custom_rt_opt": "enabled"},
    }
    user_payload = {
        "agent_config": {"endpoint": "http://override:8000"},
        "runtime_config": {"max_turns": 50},
        "max_turns": 30,
    }
    ac, rc = resolve_execution_configs(user_payload, scen_data)
    assert ac["endpoint"] == "http://override:8000"
    assert ac["model"] == "claude-3-5-sonnet"
    assert ac["custom_agent_opt"] == 123
    assert rc["max_turns"] == 50
    assert rc["custom_rt_opt"] == "enabled"


def test_run_lifecycle_sealed_fallback(tmp_path):
    """Fallback marker check in get_run_lifecycle_state: if .sealed exists, state is SEALED."""
    run_id = "run-sealed-fallback"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / ".sealed").touch()

    with patch.object(config, "RUN_LOG_DIR", tmp_path):
        state = get_run_lifecycle_state(run_id)
        assert state == RunLifecycleState.SEALED


def test_verify_package_empty_lines_in_stream():
    """
    verify_package and verify_package_artifacts must cleanly ignore
    blank/whitespace lines in trace bytes.
    """
    raw_trace_bytes = b'{"_seq": 1, "event": "run_start"}\n\n   \n{"_seq": 2, "event": "run_end"}\n'
    trace_hash = f"sha3_256:{hashlib.sha3_256(raw_trace_bytes).hexdigest()}"

    events = [
        {"_seq": 1, "event": "run_start"},
        {"_seq": 2, "event": "run_end"},
    ]
    parsed_stream = [
        (json.loads(line), line.decode("utf-8").strip())
        for line in raw_trace_bytes.splitlines()
        if line.strip()
    ]
    ev_graph = build_evidence_graph_from_events(parsed_stream)
    ev_root = compute_evidence_graph_root(ev_graph)

    pkg = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        manifest_id="m1",
        manifest_hash="sha3_256:man",
        execution_identity={"worker": "w1"},
        trace_hash=trace_hash,
        trace_seal={"digest": trace_hash, "event_count": 2},
        evidence_root_hash=ev_root,
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )

    res_art = VerificationAuthority.verify_package_artifacts(
        pkg,
        raw_trace_bytes=raw_trace_bytes,
        raw_trace_events=events,
        canonical_manifest=None,
        require_signature=False,
    )
    assert not any("TraceStreamParsingFailed" in f for f in res_art["failures"])

    res_pkg = VerificationAuthority.verify_package(
        pkg,
        raw_trace_bytes=raw_trace_bytes,
        raw_trace_events=events,
        require_signature=False,
    )
    assert not any("TraceStreamParsingFailed" in f for f in res_pkg["failures"])


def test_scenarios_readiness_and_evaluate_endpoints_with_fingerprint(tmp_path, monkeypatch):
    """Test /api/scenarios/readiness and /api/v1/evaluate preflight fingerprint validation."""
    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")
    from eval_runner.console.app import create_app

    scen_dir = tmp_path / "scenarios"
    scen_dir.mkdir(parents=True, exist_ok=True)
    scen_file = scen_dir / "test_fingerprint_scen.json"
    scen_data = {
        "aes_version": 1.4,
        "metadata": {
            "id": "test_fingerprint_scen",
            "version": "1.0.0",
            "name": "Fingerprint Scenario",
            "compliance_level": "Standard",
        },
        "workflow": {
            "nodes": [
                {
                    "id": "n1",
                    "task_description": "probe",
                    "required_tools": [],
                    "expected_outcome": [],
                }
            ],
            "edges": [],
        },
        "evaluation": {
            "consensus": {
                "strategy": "Majority_Vote",
                "min_judges": 1,
                "judge_panel": ["Luna-1"],
            }
        },
        "industry": "finance",
    }
    scen_file.write_text(json.dumps(scen_data), encoding="utf-8")

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    dist_dir = tmp_path / "ui" / "visual-console" / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text(
        "<!DOCTYPE html><html><body>Visual Console</body></html>", encoding="utf-8"
    )

    with (
        patch.object(config, "PROJECT_ROOT", tmp_path),
        patch.object(config, "RUN_LOG_DIR", runs_dir),
        patch("eval_runner.reference.inprocess_backend.InProcessExecutionBackend.submit"),
    ):
        app = create_app()
        app.secret_key = "test_secret_key"
        client = app.test_client()

        # 1. Readiness check returns manifest and preflight_fingerprint
        readiness_res = client.post(
            "/api/scenarios/readiness",
            json={
                "scenario_id": "test_fingerprint_scen",
                "agent_config": {"endpoint": "http://localhost:8000", "protocol": "http_rest"},
                "runtime_config": {"max_turns": 10},
            },
        )
        assert readiness_res.status_code == 200
        r_json = readiness_res.get_json()
        assert "preflight_fingerprint" in r_json
        assert "manifest" in r_json
        server_pfp = r_json["preflight_fingerprint"]

        # 2. Evaluate with invalid/mismatched preflight fingerprint returns 400
        bad_eval_res = client.post(
            "/api/v1/evaluate",
            json={
                "path": str(scen_file),
                "agent_config": {"endpoint": "http://localhost:8000", "protocol": "http_rest"},
                "runtime_config": {"max_turns": 10},
                "preflight_fingerprint": (
                    "bad_fingerprint_0000000000000000000000000000000000000000000000000000"
                ),
            },
        )
        assert bad_eval_res.status_code == 400
        bad_json = bad_eval_res.get_json()
        assert "PreflightFingerprintMismatch" in bad_json["error"]

        # 3. Evaluate with matching preflight fingerprint succeeds
        good_eval_res = client.post(
            "/api/v1/evaluate",
            json={
                "path": str(scen_file),
                "agent_config": {"endpoint": "http://localhost:8000", "protocol": "http_rest"},
                "runtime_config": {"max_turns": 10},
                "preflight_fingerprint": server_pfp,
            },
        )
        print("GOOD EVAL DEBUG:", good_eval_res.get_json())
        assert good_eval_res.status_code == 200
        good_json = good_eval_res.get_json()
        assert good_json["status"] == "started"


def test_manifest_content_hash_properties():
    """Verify ExecutionManifest content_hash and compute_content_hash aliases."""
    manifest = ExecutionManifest(
        manifest_id="m-hash-test",
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        tenant_id="t1",
        workspace_id="ws1",
        agent_config={},
        runtime_config={},
        environment={},
        created_at="2026-09-01T00:00:00Z",
        created_by="system",
        metadata={},
    )
    expected_hash = manifest.compute_manifest_hash()
    assert manifest.content_hash == expected_hash
    assert manifest.compute_content_hash() == expected_hash
    restored = ExecutionManifest.from_dict(manifest.to_dict())
    assert restored.content_hash == expected_hash


def test_run_lifecycle_os_error_handling(tmp_path):
    """
    Verify get_run_lifecycle_state logs error and fails closed to INVALID
    when marker read raises OSError.
    """
    run_id = "run-os-err-test"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    marker_file = run_dir / ".run_lifecycle"
    marker_file.write_text("ACTIVE", encoding="utf-8")

    with patch.object(config, "RUN_LOG_DIR", tmp_path):
        with patch("pathlib.Path.read_text", side_effect=OSError("Disk read error")):
            state = get_run_lifecycle_state(run_id)
            assert state == RunLifecycleState.INVALID


def test_identity_provisioning_allowed_in_dev(monkeypatch, tmp_path):
    """Verify that when ALLOW_SYSTEM_IDENTITY_PROVISIONING=True, PermissionError is not raised."""
    monkeypatch.setattr(config, "ALLOW_SYSTEM_IDENTITY_PROVISIONING", True)
    monkeypatch.setattr(config, "TRUST_ROOT", tmp_path / "empty_trust_root")

    # Without auto_provision, should return None instead of raising PermissionError
    res = IdentityService.get_private_key("system_id", auto_provision=False)
    assert res is None

    res_cert = IdentityService.get_private_key("certification_authority", auto_provision=False)
    assert res_cert is None


def test_verify_trace_certificate_malformed_json_line(tmp_path):
    """
    Verify that malformed JSON in trace triggers Malformed trace record error
    in verify_trace_certificate.
    """
    from eval_runner.verifier import verify_trace_certificate

    trace_file = tmp_path / "corrupt_trace.jsonl"
    trace_file.write_text('{"event": "run_start", "_seq": 1}\nNOT_VALID_JSON\n', encoding="utf-8")

    cert_data = {
        "scenario_id": "s1",
        "scenario_version": "1.0.0",
        "scenario_hash": "sha3_256:scen",
        "trace_hash": f"sha3_256:{hashlib.sha3_256(trace_file.read_bytes()).hexdigest()}",
        "evidence_root_hash": "sha3_256:mock_root",
        "verdict": "PASS",
        "signer": {"identity": "ca", "algorithm": "ED25519", "signature": "00"},
    }

    result = verify_trace_certificate(
        run_id="run-malformed-line",
        trace_bytes=trace_file.read_bytes(),
        cert_data=cert_data,
    )
    assert result["verified"] is False
    assert any("Malformed trace record at line 2" in err for err in result["errors"])


def test_verification_authority_verify_package_split_chain_and_parsing_error():
    """
    Verify verify_package detects split-chain violations, parsing failures,
    and invalid seal counts.
    """
    raw_trace_bytes = b'{"event": "run_start", "_seq": 1}\n{"event": "run_end", "_seq": 2}\n'
    trace_hash = f"sha3_256:{hashlib.sha3_256(raw_trace_bytes).hexdigest()}"

    manifest = ExecutionManifest(
        manifest_id="m-pkg-split",
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        tenant_id="t1",
        workspace_id="ws1",
        agent_config={},
        runtime_config={},
        environment={},
        created_at="2026-09-01T00:00:00Z",
        created_by="system",
        metadata={},
    )

    pkg = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        manifest_id="m-pkg-split",
        manifest_hash=manifest.compute_manifest_hash(),
        execution_identity={"system_id": "system_id"},
        trace_hash=trace_hash,
        evidence_root_hash="sha3_256:root",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"verdict": "PASS"},
        signer_identity="system_id",
        algorithm="ed25519",
        signature="00" * 64,
        trace_seal={"trace_digest": trace_hash, "event_count": "not_an_int"},
    )

    # 1. Split-chain violation: caller passes 3 events but byte stream has 2
    res_split = VerificationAuthority.verify_package(
        package=pkg,
        raw_trace_bytes=raw_trace_bytes,
        raw_trace_events=[{"_seq": 1}, {"_seq": 2}, {"_seq": 3}],
        canonical_manifest=manifest,
    )
    assert any("TraceStreamSplitChainViolation" in f for f in res_split["failures"])

    # 2. Trace stream parsing failure with invalid JSON line in bytes
    corrupt_bytes = b'{"event": "run_start"}\n{invalid_json}\n'
    res_parse = VerificationAuthority.verify_package(
        package=pkg,
        raw_trace_bytes=corrupt_bytes,
        canonical_manifest=manifest,
    )
    assert any("TraceStreamParsingFailed" in f for f in res_parse["failures"])


def test_scenarios_readiness_loader_fallback_and_error(tmp_path, monkeypatch):
    """
    Verify check_execution_readiness fallback when loader raises exception,
    and debug log on read failure.
    """
    from eval_runner.console.app import create_app

    monkeypatch.setenv("AGENTV_TEST_AUTH_BYPASS", "1")

    scen_dir = tmp_path / "scenarios"
    scen_dir.mkdir(parents=True, exist_ok=True)
    scen_file = scen_dir / "fallback_scen.json"
    scen_file.write_text(
        json.dumps({"id": "fallback_scen", "metadata": {"id": "fallback_scen"}}), encoding="utf-8"
    )

    dist_dir = tmp_path / "ui" / "visual-console" / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text(
        "<!DOCTYPE html><html><body>Visual Console</body></html>", encoding="utf-8"
    )

    with patch.object(config, "PROJECT_ROOT", tmp_path):
        app = create_app()
        app.secret_key = "test_key"
        client = app.test_client()

        # 1. When loader.load_scenario fails, fallback to json.load succeeds
        with patch(
            "eval_runner.loader.load_scenario", side_effect=Exception("Simulated loader failure")
        ):
            res = client.post(
                "/api/scenarios/readiness",
                json={
                    "scenario_id": "fallback_scen",
                    "path": str(scen_file),
                },
            )
            assert res.status_code == 200
            rj = res.get_json()
            assert rj["scenario_id"] == "fallback_scen"

        # 2. When both loader and json.load fail, logger.debug is called and check fails
        with (
            patch("eval_runner.loader.load_scenario", side_effect=Exception("Loader fail")),
            patch("builtins.open", side_effect=OSError("Read fail")),
        ):
            res2 = client.post(
                "/api/scenarios/readiness",
                json={
                    "scenario_id": "fallback_scen",
                    "path": str(scen_file),
                },
            )
            assert res2.status_code == 200
            rj2 = res2.get_json()
            assert rj2["ready"] is False


def test_run_lifecycle_comprehensive_coverage(tmp_path):
    """Verify 100% coverage of all execution branches and edge cases in run_lifecycle."""
    from eval_runner.run_lifecycle import (
        RunLifecycleState,
        TraceClosedError,
        assert_can_write_trace,
        can_write_trace,
        get_run_lifecycle_state,
        transition_run_lifecycle,
    )

    with patch.object(config, "RUN_LOG_DIR", tmp_path):
        # 1. get_run_lifecycle_state with None or 'unknown'
        assert get_run_lifecycle_state("") == RunLifecycleState.OPEN
        assert get_run_lifecycle_state("unknown") == RunLifecycleState.OPEN

        # 2. transition_run_lifecycle with None or 'unknown'
        assert transition_run_lifecycle("", RunLifecycleState.FINALIZING) == RunLifecycleState.OPEN
        assert (
            transition_run_lifecycle("unknown", RunLifecycleState.SEALED) == RunLifecycleState.OPEN
        )

        # 3. can_write_trace with None or 'unknown'
        can_w, r = can_write_trace("")
        assert can_w is True
        assert r == ""

        # 4. Marker file with raw non-JSON string
        run_id = "run-raw-state-test"
        run_dir = tmp_path / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / ".run_lifecycle").write_text("FINALIZING", encoding="utf-8")
        assert get_run_lifecycle_state(run_id) == RunLifecycleState.FINALIZING

        # 5. Illegal transition backwards (e.g. FINALIZING -> OPEN) raises ValueError
        with pytest.raises(ValueError, match="IllegalLifecycleTransition"):
            transition_run_lifecycle(run_id, RunLifecycleState.OPEN)

        # 6. can_write_trace and assert_can_write_trace in FINALIZING state
        can_w2, reason2 = can_write_trace(run_id)
        assert can_w2 is False
        assert "FINALIZING" in reason2
        with pytest.raises(TraceClosedError, match="FINALIZING"):
            assert_can_write_trace(run_id)

        # 7. Transition to SEALED
        transition_run_lifecycle(run_id, RunLifecycleState.SEALED)
        assert get_run_lifecycle_state(run_id) == RunLifecycleState.SEALED
        can_w3, reason3 = can_write_trace(run_id)
        assert can_w3 is False
        assert "SEALED" in reason3
        with pytest.raises(TraceClosedError, match="SEALED"):
            assert_can_write_trace(run_id)

        # 8. Handling OSError when writing .sealed marker
        run_id2 = "run-sealed-oserror"
        run_dir2 = tmp_path / run_id2
        run_dir2.mkdir(parents=True, exist_ok=True)
        transition_run_lifecycle(run_id2, RunLifecycleState.FINALIZING)
        orig_path_open = Path.open

        def mock_path_open(self, *args, **kwargs):
            if self.name == ".sealed":
                raise OSError("Disk full")
            return orig_path_open(self, *args, **kwargs)

        with patch("pathlib.Path.open", side_effect=mock_path_open, autospec=True):
            transition_run_lifecycle(run_id2, RunLifecycleState.SEALED)

        # 9. Active certification lock blocks trace writing
        run_id3 = "run-locked-test"
        with patch(
            "eval_runner.certification_lock.PerRunCertificationLock.is_locked", return_value=True
        ):
            can_w4, reason4 = can_write_trace(run_id3)
            assert can_w4 is False
            assert "locked for certification" in reason4
            with pytest.raises(TraceClosedError, match="locked for certification"):
                assert_can_write_trace(run_id3)

        # 10. Open run that is not locked can write trace
        run_id4 = "run-open-clean"
        can_w5, reason5 = can_write_trace(run_id4)
        assert can_w5 is True
        assert reason5 == ""
        assert_can_write_trace(run_id4)

        # 11. Corrupt/empty/invalid marker files fail closed to RunLifecycleState.INVALID
        run_corrupt = "run-corrupt-marker"
        corrupt_dir = tmp_path / run_corrupt
        corrupt_dir.mkdir(parents=True, exist_ok=True)
        (corrupt_dir / ".run_lifecycle").write_text("{not: valid json!", encoding="utf-8")
        assert get_run_lifecycle_state(run_corrupt) == RunLifecycleState.INVALID

        run_empty = "run-empty-marker"
        empty_dir = tmp_path / run_empty
        empty_dir.mkdir(parents=True, exist_ok=True)
        (empty_dir / ".run_lifecycle").write_text("   ", encoding="utf-8")
        assert get_run_lifecycle_state(run_empty) == RunLifecycleState.INVALID

        run_nondict = "run-nondict-marker"
        nondict_dir = tmp_path / run_nondict
        nondict_dir.mkdir(parents=True, exist_ok=True)
        (nondict_dir / ".run_lifecycle").write_text('["item1", "item2"]', encoding="utf-8")
        assert get_run_lifecycle_state(run_nondict) == RunLifecycleState.INVALID

        run_badstate = "run-badstate-marker"
        badstate_dir = tmp_path / run_badstate
        badstate_dir.mkdir(parents=True, exist_ok=True)
        (badstate_dir / ".run_lifecycle").write_text('{"state": "NON_EXISTENT"}', encoding="utf-8")
        assert get_run_lifecycle_state(run_badstate) == RunLifecycleState.INVALID

        run_dir_marker = "run-dir-marker"
        dir_marker_dir = tmp_path / run_dir_marker
        (dir_marker_dir / ".run_lifecycle").mkdir(parents=True, exist_ok=True)
        assert get_run_lifecycle_state(run_dir_marker) == RunLifecycleState.INVALID

        # 12. Cannot transition out of INVALID state
        with pytest.raises(ValueError, match="IllegalLifecycleTransition.*corrupted/untrusted"):
            transition_run_lifecycle(run_corrupt, RunLifecycleState.FINALIZING)

        # 13. Cannot write trace when in INVALID state
        can_w_inv, reason_inv = can_write_trace(run_corrupt)
        assert can_w_inv is False
        assert "INVALID" in reason_inv
        with pytest.raises(TraceClosedError, match="INVALID"):
            assert_can_write_trace(run_corrupt)


def test_identity_env_and_default_signer(monkeypatch, tmp_path):
    """Verify get_public_key from environment variable and get_default_signer resolution."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    from eval_runner.identity import get_default_signer

    # 1. get_public_key from environment variable
    pk = ed25519.Ed25519PrivateKey.generate().public_key()
    pem = pk.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    monkeypatch.setenv("AES_PUBLIC_KEY_CUSTOM_ID", pem)
    loaded_pk = IdentityService.get_public_key("custom_id")
    assert loaded_pk is not None

    # Invalid public key in env logs warning and falls through
    monkeypatch.setenv("AES_PUBLIC_KEY_BAD_ID", "INVALID_PEM_DATA")
    loaded_bad = IdentityService.get_public_key("bad_id")
    assert loaded_bad is None

    # 2. get_default_signer NullSigningBackend
    monkeypatch.delenv("FLIGHT_RECORDER_KEY_PATH", raising=False)
    signer_null = get_default_signer()
    assert signer_null is not None

    # 3. get_default_signer with key_path
    key_file = tmp_path / "test.key"
    key_file.write_text("fake_key", encoding="utf-8")
    monkeypatch.setenv("FLIGHT_RECORDER_KEY_PATH", str(key_file))
    signer_local = get_default_signer()
    assert signer_local is not None


@pytest.mark.asyncio
async def test_runner_sanitizes_callable_metadata(tmp_path, monkeypatch):
    """Verify runner.run() strips callables from metadata to prevent LossyScenarioError."""
    import eval_runner.config as config
    from eval_runner.runner import DefaultRunner

    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    runner = DefaultRunner()

    scenario = {
        "id": "scen_callable_test",
        "workflow": {"nodes": []},
        "success_criteria": {"mode": "all"},
    }

    # Pass metadata containing a callable dispatch function in args dict
    def dummy_callback():
        pass

    metadata = {
        "args": {
            "func": dummy_callback,
            "path": "industries/telecom/scenarios",
            "format": "jsonl",
        },
        "extra_callable": dummy_callback,
        "clean_meta": "valid_value",
    }

    results = await runner.run(
        scenario,
        attempts=1,
        run_id="run-callable-sanitize-test",
        metadata=metadata,
    )
    assert results is not None
    # Verify manifest was written and has no callables
    manifest_path = tmp_path / "runs" / "run-callable-sanitize-test" / "execution_manifest.json"
    assert manifest_path.exists()
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "func" not in manifest_data["metadata"]["args"]
    assert "extra_callable" not in manifest_data["metadata"]
    assert manifest_data["metadata"]["args"]["path"] == "industries/telecom/scenarios"
    assert manifest_data["metadata"]["clean_meta"] == "valid_value"
