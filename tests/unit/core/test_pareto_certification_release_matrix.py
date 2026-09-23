"""
tests/unit/core/test_pareto_certification_release_matrix.py

Authoritative 8-Point Adversarial Acceptance Matrix for Pareto Certification Blockers:
1. Missing EvaluatorFinalizationRecord fails closed.
2. EvaluatorFinalizationRecord with altered scenario_hash fails closed (ScenarioHashMismatch).
3. EvaluatorFinalizationRecord with tampered finalization_hash fails closed.
4. EvaluatorFinalizationRecord with missing required oracle fails closed (MissingRequiredOracles).
5. Trace append during FINALIZING / SEALED lifecycle state raises TraceClosedError.
6. Per-run certification lock acquisition: active PID causes TimeoutError, dead PID recovered.
7. VerificationPackage artifact verification fails closed if scenario or manifest hash altered.
8. VerificationPackage signature verification succeeds with authentic external trust anchor
   and fails closed if anchor is altered.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from agentv_runtime.evidence_graph import (
    build_evidence_graph_from_events,
    compute_evidence_graph_root,
)
from agentv_runtime.finalization import EvaluatorFinalizationRecord
from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash
from agentv_runtime.package import VerificationPackage
from eval_runner import config
from eval_runner.certification_lock import PerRunCertificationLock
from eval_runner.identity import IdentityService
from eval_runner.run_lifecycle import (
    RunLifecycleState,
    TraceClosedError,
    assert_can_write_trace,
    transition_run_lifecycle,
)
from eval_runner.services.certification import (
    execute_industrial_certification,
)
from eval_runner.verifier import VerificationAuthority


@pytest.fixture
def matrix_env(tmp_path, monkeypatch):
    root = tmp_path / "matrix_proj"
    runs = root / "runs"
    reports = root / "reports"
    trust = root / ".aes" / "keys"
    runs.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    trust.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    monkeypatch.setattr(config, "RUN_LOG_DIR", runs)
    monkeypatch.setattr(config, "REPORTS_DIR", reports)
    monkeypatch.setattr(config, "TRUST_ROOT", trust)

    IdentityService._provision_local_identity("system_id")
    IdentityService._provision_local_identity("attacker_id")
    IdentityService._provision_local_identity("eval_kernel")

    return {"root": root, "runs": runs, "reports": reports, "trust": trust}


def _build_test_run(
    runs_dir: Path,
    run_id: str,
    events: list[dict[str, Any]],
    scenario_data: Mapping[str, Any],
    evaluator_finalization: EvaluatorFinalizationRecord | None = None,
    write_manifest: bool = True,
) -> tuple[Path, Path]:
    vault = runs_dir / run_id
    vault.mkdir(parents=True, exist_ok=True)
    trace = vault / "run.jsonl"

    scen_id = scenario_data.get("id") or scenario_data.get("scenario_id") or "scen_matrix"
    scen_ver = scenario_data.get("version") or scenario_data.get("scenario_version") or "1.0.0"
    scen_hash = compute_scenario_hash(scenario_data)

    req_oracles = list(
        scenario_data.get("required_oracles")
        or scenario_data.get("required_oracle_ids")
        or (scenario_data.get("metadata") or {}).get("required_oracles")
        or (scenario_data.get("metadata") or {}).get("required_oracle_ids")
        or (evaluator_finalization.required_oracle_ids if evaluator_finalization else [])
        or []
    )
    exec_manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id=scen_id,
        scenario_version=scen_ver,
        scenario_hash=scen_hash,
        metadata={"required_oracle_ids": req_oracles} if req_oracles else {},
        runtime_config={"required_oracle_ids": req_oracles} if req_oracles else {},
    )
    if write_manifest:
        (vault / "execution_manifest.json").write_text(
            json.dumps(exec_manifest.to_dict()), encoding="utf-8"
        )

    final_events = list(events)
    if evaluator_finalization is not None:
        if write_manifest and evaluator_finalization.execution_manifest_hash == "sha3_256:dummy":
            from dataclasses import replace

            evaluator_finalization = replace(
                evaluator_finalization,
                execution_manifest_hash=exec_manifest.compute_manifest_hash(),
            )
        if not evaluator_finalization.evaluator_signature:
            evaluator_finalization = evaluator_finalization.sign()
        fin_dict = evaluator_finalization.to_dict()
        final_events.append({"event": "evaluator_finalization", "data": fin_dict})

    with open(trace, "w", encoding="utf-8") as f:
        for ev in final_events:
            f.write(json.dumps(ev) + "\n")

    return vault, trace


# ==============================================================================
# Missing EvaluatorFinalizationRecord fails closed
# ==============================================================================


def test_missing_evaluator_finalization_fails_closed(matrix_env):
    run_id = "run-v1-missing-fin"
    scen_data = {"id": "scen_v1", "version": "1.0.0"}
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_v1"},
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    # No evaluator_finalization record attached
    _build_test_run(matrix_env["runs"], run_id, events, scen_data, evaluator_finalization=None)

    with pytest.raises(
        ValueError, match="missing mandatory authoritative EvaluatorFinalizationRecord"
    ):
        execute_industrial_certification(run_id=run_id, scenario_data=scen_data)


# ==============================================================================
# EvaluatorFinalizationRecord with altered scenario_hash fails closed
# ==============================================================================


def test_altered_scenario_hash_fails_closed(matrix_env):
    run_id = "run-v2-tampered-scen-hash"
    scen_data = {"id": "scen_v2", "version": "1.0.0", "params": {"safe": True}}
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_v2"},
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    ev_graph = build_evidence_graph_from_events(events)
    ev_root = compute_evidence_graph_root(ev_graph)

    fin_rec = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash="sha3_256:dummy",
        scenario_id="scen_v2",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:" + "0" * 64,  # Malicious / tampered scenario hash
        evaluator_identity="eval_kernel",
        evaluator_config_hash="sha3_256:0000000000000000000000000000000000000000000000000000000000000000",
        required_oracle_ids=[],
        evidence_root_hash=ev_root,
        outcome="pass",
        score=1.0,
    )
    _build_test_run(matrix_env["runs"], run_id, events, scen_data, evaluator_finalization=fin_rec)

    with pytest.raises(ValueError, match="ScenarioHashMismatch"):
        execute_industrial_certification(run_id=run_id, scenario_data=scen_data)


# ==============================================================================
# EvaluatorFinalizationRecord with tampered finalization_hash fails closed
# ==============================================================================


def test_tampered_finalization_hash_fails_closed(matrix_env):
    run_id = "run-v3-tampered-fin-hash"
    scen_data = {"id": "scen_v3", "version": "1.0.0"}
    scen_hash = compute_scenario_hash(scen_data)
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_v3"},
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    ev_graph = build_evidence_graph_from_events(events)
    ev_root = compute_evidence_graph_root(ev_graph)

    fin_rec = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash="sha3_256:dummy",
        scenario_id="scen_v3",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        evaluator_identity="eval_kernel",
        evaluator_config_hash="sha3_256:0000000000000000000000000000000000000000000000000000000000000000",
        required_oracle_ids=[],
        evidence_root_hash=ev_root,
        outcome="pass",
        score=1.0,
    )
    # Sign legitimately first, then tamper the finalization_hash to simulate in-flight tampering
    fin_rec = fin_rec.sign()
    from dataclasses import replace

    tampered_fin_rec = replace(
        fin_rec,
        finalization_hash="sha3_256:forged_hash_value_that_does_not_match_computed",
    )
    vault, trace = _build_test_run(
        matrix_env["runs"],
        run_id,
        events,
        scen_data,
        evaluator_finalization=tampered_fin_rec,
    )

    with pytest.raises(ValueError, match="inconclusive outcome"):
        execute_industrial_certification(run_id=run_id, scenario_data=scen_data)


# ==============================================================================
# EvaluatorFinalizationRecord with missing required oracle fails closed
# ==============================================================================


def test_missing_required_oracle_fails_closed(matrix_env):
    run_id = "run-v4-missing-oracle"
    scen_data = {
        "id": "scen_v4",
        "version": "1.0.0",
        "required_oracles": ["oracle_1", "oracle_2_missing"],
    }
    scen_hash = compute_scenario_hash(scen_data)
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_v4"},
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    # Build evidence graph with both oracles required
    ev_graph = build_evidence_graph_from_events(
        events, required_oracle_ids=["oracle_1", "oracle_2_missing"]
    )
    ev_root = compute_evidence_graph_root(ev_graph)

    exec_manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id="scen_v4",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        metadata={"required_oracle_ids": ["oracle_1", "oracle_2_missing"]},
        runtime_config={"required_oracle_ids": ["oracle_1", "oracle_2_missing"]},
    )
    vault = matrix_env["runs"] / run_id
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "execution_manifest.json").write_text(
        json.dumps(exec_manifest.to_dict()), encoding="utf-8"
    )
    m_hash = exec_manifest.compute_manifest_hash()

    fin_rec = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash=m_hash,
        scenario_id="scen_v4",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        evaluator_identity="eval_kernel",
        evaluator_config_hash="sha3_256:0000000000000000000000000000000000000000000000000000000000000000",
        required_oracle_ids=["oracle_1", "oracle_2_missing"],
        evidence_root_hash=ev_root,
        outcome="pass",
        score=1.0,
    )
    _build_test_run(
        matrix_env["runs"],
        run_id,
        events,
        scen_data,
        evaluator_finalization=fin_rec,
        write_manifest=False,
    )

    with pytest.raises(ValueError, match="MissingRequiredOracles"):
        execute_industrial_certification(run_id=run_id, scenario_data=scen_data)


# ==============================================================================
# Trace append during FINALIZING / SEALED lifecycle state raises TraceClosedError
# ==============================================================================


def test_trace_append_blocked_during_finalizing_or_sealed(matrix_env):
    run_id = "run-v5-lifecycle-guard"

    # Initially OPEN: writes permitted
    assert_can_write_trace(run_id)

    # Transition to FINALIZING: writes must be blocked
    transition_run_lifecycle(run_id, RunLifecycleState.FINALIZING)
    with pytest.raises(TraceClosedError, match="trace writes prohibited"):
        assert_can_write_trace(run_id)

    # Transition to SEALED: writes remain blocked
    transition_run_lifecycle(run_id, RunLifecycleState.SEALED)
    with pytest.raises(TraceClosedError, match="cryptographically immutable"):
        assert_can_write_trace(run_id)


# ==============================================================================
# Per-run certification lock acquisition: active PID blocks, dead PID recovers
# ==============================================================================


def test_lock_fencing_active_pid_blocks_and_dead_pid_recovers(matrix_env):
    run_id = "run-v6-fenced-locking"
    vault = matrix_env["runs"] / run_id
    vault.mkdir(parents=True, exist_ok=True)
    lock_file = vault / ".certification.lock"

    # Active PID lock blocks concurrent acquisition
    active_pid = os.getpid()
    lock_file.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "pid": active_pid,
                "timestamp": str(time.time()),
                "lease_seconds": 60,
                "fencing_token": "fence_active",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(TimeoutError, match="CertificationLockConflict"):
        with PerRunCertificationLock(run_id, timeout_seconds=0.1):
            pass

    # Dead PID lock is safely reclaimed
    dead_pid = 999999
    lock_file.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "pid": dead_pid,
                "timestamp": str(time.time()),
                "lease_seconds": 60,
                "fencing_token": "fence_dead",
            }
        ),
        encoding="utf-8",
    )

    with PerRunCertificationLock(run_id, timeout_seconds=1.0) as acquired_lock:
        assert acquired_lock.fencing_token.startswith("fence_")
        assert lock_file.exists()


# ==============================================================================
# VerificationPackage verification fails closed if scenario or manifest hash is altered
# ==============================================================================


def test_verification_package_fails_on_altered_scenario_or_manifest(matrix_env):
    run_id = "run-v7-pkg-tamper"
    scen_data = {"id": "scen_v7", "version": "1.0.0", "param_x": 100}
    scen_hash = compute_scenario_hash(scen_data)
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_v7"},
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    ev_graph = build_evidence_graph_from_events(events)
    ev_root = compute_evidence_graph_root(ev_graph)

    exec_manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id="scen_v7",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
    )
    vault = matrix_env["runs"] / run_id
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "execution_manifest.json").write_text(
        json.dumps(exec_manifest.to_dict()), encoding="utf-8"
    )
    m_hash = exec_manifest.compute_manifest_hash()

    fin_rec = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash=m_hash,
        scenario_id="scen_v7",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        evaluator_identity="eval_kernel",
        evaluator_config_hash="sha3_256:0000000000000000000000000000000000000000000000000000000000000000",
        required_oracle_ids=[],
        evidence_root_hash=ev_root,
        outcome="pass",
        score=1.0,
    )
    vault, trace = _build_test_run(
        matrix_env["runs"],
        run_id,
        events,
        scen_data,
        evaluator_finalization=fin_rec,
        write_manifest=False,
    )

    cert_res = execute_industrial_certification(
        run_id=run_id,
        identity_id="system_id",
        scenario_data=scen_data,
    )
    assert cert_res["certified"] is True
    pkg_dict = cert_res["manifest"]["verification_package"]
    pkg = VerificationPackage.from_dict(pkg_dict)

    trace_events = [
        json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines() if line.strip()
    ]

    # Valid package verification against authentic root
    valid_res = VerificationAuthority.verify_package_artifacts(
        package=pkg,
        raw_trace_bytes=trace.read_bytes(),
        raw_trace_events=trace_events,
        canonical_manifest=exec_manifest,
        scenario_data=scen_data,
        trust_root=matrix_env["trust"],
    )
    assert valid_res["verified"] is True, f"Failures: {valid_res.get('failures')}"

    # Tampered scenario artifact verification fails closed
    tampered_scen = dict(scen_data)
    tampered_scen["param_x"] = 999
    tampered_scen_res = VerificationAuthority.verify_package_artifacts(
        package=pkg,
        raw_trace_bytes=trace.read_bytes(),
        raw_trace_events=trace_events,
        canonical_manifest=exec_manifest,
        scenario_data=tampered_scen,
        trust_root=matrix_env["trust"],
    )
    assert tampered_scen_res["verified"] is False
    assert any("ScenarioHashMismatch" in f for f in tampered_scen_res["failures"])

    # Tampered manifest hash fails closed
    from dataclasses import replace

    tampered_pkg = replace(pkg, manifest_hash="sha3_256:" + "f" * 64)
    tampered_manifest_res = VerificationAuthority.verify_package_artifacts(
        package=tampered_pkg,
        raw_trace_bytes=trace.read_bytes(),
        raw_trace_events=trace_events,
        canonical_manifest=exec_manifest,
        scenario_data=scen_data,
        trust_root=matrix_env["trust"],
    )
    assert tampered_manifest_res["verified"] is False
    assert any("ManifestHashMismatch" in f for f in tampered_manifest_res["failures"])


# ==============================================================================
# VerificationPackage verification with authentic vs altered external trust anchor
# ==============================================================================


def test_external_trust_anchor_verification(matrix_env):
    run_id = "run-v8-anchor-verify"
    scen_data = {"id": "scen_v8", "version": "1.0.0"}
    scen_hash = compute_scenario_hash(scen_data)
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_v8"},
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    ev_graph = build_evidence_graph_from_events(events)
    ev_root = compute_evidence_graph_root(ev_graph)

    exec_manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id="scen_v8",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
    )
    vault = matrix_env["runs"] / run_id
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "execution_manifest.json").write_text(
        json.dumps(exec_manifest.to_dict()), encoding="utf-8"
    )
    m_hash = exec_manifest.compute_manifest_hash()

    fin_rec = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash=m_hash,
        scenario_id="scen_v8",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        evaluator_identity="eval_kernel",
        evaluator_config_hash="sha3_256:0000000000000000000000000000000000000000000000000000000000000000",
        required_oracle_ids=[],
        evidence_root_hash=ev_root,
        outcome="pass",
        score=1.0,
    )
    _build_test_run(
        matrix_env["runs"],
        run_id,
        events,
        scen_data,
        evaluator_finalization=fin_rec,
        write_manifest=False,
    )

    cert_res = execute_industrial_certification(
        run_id=run_id,
        identity_id="system_id",
        scenario_data=scen_data,
    )
    assert cert_res["certified"] is True
    pkg_dict = cert_res["manifest"]["verification_package"]
    pkg = VerificationPackage.from_dict(pkg_dict)

    # Resolve legitimate public key from trust root
    system_pub_key = IdentityService.get_public_key("system_id", auto_provision=False)
    assert system_pub_key is not None
    from cryptography.hazmat.primitives import serialization

    system_pub_pem = system_pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    # Verification with authentic trust anchor succeeds
    assert (
        pkg.verify_signature(
            public_key_pem=system_pub_pem,
            trust_root=matrix_env["trust"],
        )
        is True
    )

    sig_only_res = VerificationAuthority.verify_package_signature_only(
        pkg,
        public_key_pem=system_pub_pem,
    )
    assert sig_only_res["verified"] is True

    # Verification with altered trust anchor (from attacker_id) fails closed
    attacker_pub_key = IdentityService.get_public_key("attacker_id", auto_provision=False)
    assert attacker_pub_key is not None
    attacker_pub_pem = attacker_pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    assert (
        pkg.verify_signature(
            public_key_pem=attacker_pub_pem,
            trust_root=matrix_env["trust"],
        )
        is False
    )

    sig_only_attacker = VerificationAuthority.verify_package_signature_only(
        pkg,
        public_key_pem=attacker_pub_pem,
    )
    assert sig_only_attacker["verified"] is False


# ==============================================================================
# Evaluator finalization must be authenticated; unauthorized identity
#       or tampered signature fails closed.
# ==============================================================================


def test_untrusted_evaluator_identity_fails_closed(matrix_env):
    run_id = "run-p0-1-untrusted-eval"
    scen_data = {"id": "scen_p0_1", "version": "1.0.0"}
    scen_hash = compute_scenario_hash(scen_data)
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_p0_1"},
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    ev_graph = build_evidence_graph_from_events(events)
    ev_root = compute_evidence_graph_root(ev_graph)

    exec_manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id="scen_p0_1",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
    )
    m_hash = exec_manifest.compute_manifest_hash()

    # Create a rogue identity outside the trust root
    fin_rec = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash=m_hash,
        scenario_id="scen_p0_1",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        evaluator_identity="untrusted_attacker_evaluator",
        evaluator_config_hash="sha3_256:0000000000000000000000000000000000000000000000000000000000000000",
        required_oracle_ids=[],
        evidence_root_hash=ev_root,
        outcome="pass",
        score=1.0,
    )
    # Manually sign with attacker key, but untrusted identity has no key in TRUST_ROOT
    from cryptography.hazmat.primitives.asymmetric import ed25519

    rogue_priv = ed25519.Ed25519PrivateKey.generate()
    fin_rec = fin_rec.sign(rogue_priv)

    _build_test_run(
        matrix_env["runs"],
        run_id,
        events,
        scen_data,
        evaluator_finalization=fin_rec,
        write_manifest=True,
    )

    with pytest.raises(ValueError, match="inconclusive outcome"):
        execute_industrial_certification(run_id=run_id, scenario_data=scen_data)


def test_tampered_evaluator_signature_fails_closed(matrix_env):
    run_id = "run-p0-1-tampered-sig"
    scen_data = {"id": "scen_p0_1_sig", "version": "1.0.0"}
    scen_hash = compute_scenario_hash(scen_data)
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_p0_1_sig"},
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    ev_graph = build_evidence_graph_from_events(events)
    ev_root = compute_evidence_graph_root(ev_graph)

    exec_manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id="scen_p0_1_sig",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
    )
    m_hash = exec_manifest.compute_manifest_hash()

    fin_rec = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash=m_hash,
        scenario_id="scen_p0_1_sig",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        evaluator_identity="eval_kernel",
        evaluator_config_hash="sha3_256:0000000000000000000000000000000000000000000000000000000000000000",
        required_oracle_ids=[],
        evidence_root_hash=ev_root,
        outcome="pass",
        score=1.0,
    )
    fin_rec = fin_rec.sign()
    from dataclasses import replace

    # Tamper the signature bytes
    corrupted_sig = "deadbeef" * 16
    tampered_fin = replace(fin_rec, evaluator_signature=corrupted_sig)

    _build_test_run(
        matrix_env["runs"],
        run_id,
        events,
        scen_data,
        evaluator_finalization=tampered_fin,
        write_manifest=True,
    )

    with pytest.raises(ValueError, match="inconclusive outcome"):
        execute_industrial_certification(run_id=run_id, scenario_data=scen_data)


# ==============================================================================
# Evidence root cross-check must fail closed if evidence_root_hash != recomputed
# ==============================================================================


def test_evidence_root_mismatch_fails_closed(matrix_env):
    run_id = "run-p0-2-root-mismatch"
    scen_data = {"id": "scen_p0_2", "version": "1.0.0"}
    scen_hash = compute_scenario_hash(scen_data)
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_p0_2"},
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    exec_manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id="scen_p0_2",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
    )
    m_hash = exec_manifest.compute_manifest_hash()

    fin_rec = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash=m_hash,
        scenario_id="scen_p0_2",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        evaluator_identity="eval_kernel",
        evaluator_config_hash="sha3_256:0000000000000000000000000000000000000000000000000000000000000000",
        required_oracle_ids=[],
        evidence_root_hash="sha3_256:0000000000000000000000000000000000000000000000000000000000000000",
        outcome="pass",
        score=1.0,
    )
    fin_rec = fin_rec.sign()

    _build_test_run(
        matrix_env["runs"],
        run_id,
        events,
        scen_data,
        evaluator_finalization=fin_rec,
        write_manifest=True,
    )

    with pytest.raises(ValueError, match="EvidenceRootMismatch"):
        execute_industrial_certification(run_id=run_id, scenario_data=scen_data)


# ==============================================================================
# Required-oracle completeness must require explicit PASS result state
# ==============================================================================


def test_required_oracle_failed_outcome_blocks_certification(matrix_env):
    run_id = "run-p0-3-oracle-failed"
    scen_data = {
        "id": "scen_p0_3",
        "version": "1.0.0",
        "required_oracles": ["required_check_1"],
    }
    scen_hash = compute_scenario_hash(scen_data)
    # Required oracle is present but has outcome="FAIL"
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_p0_3"},
        {
            "event": "assertion_evaluated",
            "assertion": "required_check_1",
            "passed": False,
            "outcome": "FAIL",
        },
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    ev_graph = build_evidence_graph_from_events(events, required_oracle_ids=["required_check_1"])
    ev_root = compute_evidence_graph_root(ev_graph)

    exec_manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id="scen_p0_3",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        metadata={"required_oracle_ids": ["required_check_1"]},
        runtime_config={"required_oracle_ids": ["required_check_1"]},
    )
    m_hash = exec_manifest.compute_manifest_hash()

    fin_rec = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash=m_hash,
        scenario_id="scen_p0_3",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        evaluator_identity="eval_kernel",
        evaluator_config_hash="sha3_256:0000000000000000000000000000000000000000000000000000000000000000",
        required_oracle_ids=["required_check_1"],
        evidence_root_hash=ev_root,
        outcome="pass",
        score=1.0,
    )
    fin_rec = fin_rec.sign()

    vault = matrix_env["runs"] / run_id
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "execution_manifest.json").write_text(
        json.dumps(exec_manifest.to_dict()), encoding="utf-8"
    )

    _build_test_run(
        matrix_env["runs"],
        run_id,
        events,
        scen_data,
        evaluator_finalization=fin_rec,
        write_manifest=False,
    )

    with pytest.raises(ValueError, match="MissingRequiredOracles"):
        execute_industrial_certification(run_id=run_id, scenario_data=scen_data)


# ==============================================================================
# Multi-node evidence graph never collapses distinct node executions
# ==============================================================================


def test_multi_node_preserves_distinct_executions():
    events = [
        {"event": "run_start", "_seq": 1},
        {
            "event": "execution_graph_node",
            "_seq": 2,
            "data": {
                "node_id": "node_A",
                "oracle_results": [
                    {
                        "oracle_id": "check_latency",
                        "passed": True,
                        "outcome": "PASS",
                    }
                ],
            },
        },
        {
            "event": "execution_graph_node",
            "_seq": 3,
            "data": {
                "node_id": "node_B",
                "oracle_results": [
                    {"oracle_id": "check_latency", "passed": True, "outcome": "PASS"}
                ],
            },
        },
        {"event": "run_end", "_seq": 4},
    ]
    graph = build_evidence_graph_from_events(events)
    # Must contain 2 distinct nodes keyed by (check_latency, node_A) and (check_latency, node_B)
    nodes = graph["nodes"]
    assert len(nodes) == 2
    node_ids = {n.get("node") for n in nodes}
    assert node_ids == {"node_A", "node_B"}
    assert graph["evidence_count"] == 2


# ==============================================================================
# Physical execution_manifest.json is mandatory; missing manifest fails closed
# ==============================================================================


def test_missing_execution_manifest_artifact_fails_closed(matrix_env):
    run_id = "run-p0-5-missing-manifest-file"
    scen_data = {"id": "scen_p0_5", "version": "1.0.0"}
    scen_hash = compute_scenario_hash(scen_data)
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_p0_5"},
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    ev_graph = build_evidence_graph_from_events(events)
    ev_root = compute_evidence_graph_root(ev_graph)

    fin_rec = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash="sha3_256:0000000000000000000000000000000000000000000000000000000000000000",
        scenario_id="scen_p0_5",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        evaluator_identity="eval_kernel",
        evaluator_config_hash="sha3_256:0000000000000000000000000000000000000000000000000000000000000000",
        required_oracle_ids=[],
        evidence_root_hash=ev_root,
        outcome="pass",
        score=1.0,
    )
    fin_rec = fin_rec.sign()

    vault, _ = _build_test_run(
        matrix_env["runs"],
        run_id,
        events,
        scen_data,
        evaluator_finalization=fin_rec,
        write_manifest=False,  # Deliberately omit physical execution_manifest.json
    )
    # Ensure physical file is absent
    assert not (vault / "execution_manifest.json").exists()

    with pytest.raises(ValueError, match="ExecutionManifestMissing"):
        execute_industrial_certification(run_id=run_id, scenario_data=scen_data)


# ==============================================================================
# Terminal reconciliation rejects contradictory prior decisions
# ==============================================================================


def test_contradictory_terminal_decision_fails_as_inconclusive(matrix_env):
    run_id = "run-p0-6-contradictory-terminal"
    scen_data = {"id": "scen_p0_6", "version": "1.0.0"}
    scen_hash = compute_scenario_hash(scen_data)
    # Prior terminal event says "FAIL", but finalization record says "pass"
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_p0_6"},
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "FAIL", "score": 0.0}},
    ]
    ev_graph = build_evidence_graph_from_events(events)
    ev_root = compute_evidence_graph_root(ev_graph)

    exec_manifest = ExecutionManifest(
        manifest_id=f"man_{run_id}",
        scenario_id="scen_p0_6",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
    )
    m_hash = exec_manifest.compute_manifest_hash()

    fin_rec = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash=m_hash,
        scenario_id="scen_p0_6",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        evaluator_identity="eval_kernel",
        evaluator_config_hash="sha3_256:0000000000000000000000000000000000000000000000000000000000000000",
        required_oracle_ids=[],
        evidence_root_hash=ev_root,
        outcome="pass",
        score=1.0,
    )
    fin_rec = fin_rec.sign()

    _build_test_run(
        matrix_env["runs"],
        run_id,
        events,
        scen_data,
        evaluator_finalization=fin_rec,
        write_manifest=True,
    )

    with pytest.raises(ValueError, match="inconclusive outcome"):
        execute_industrial_certification(run_id=run_id, scenario_data=scen_data)


# ==============================================================================
# Production startup fails closed when Visual Console bundle is missing
# ==============================================================================


def test_production_mode_fails_closed_without_gui(monkeypatch, tmp_path):
    from eval_runner.console.app import create_app

    monkeypatch.setenv("AGENTV_ENV", "production")
    # Point UI_BUILD_DIR to empty directory where dist/index.html does NOT exist
    fake_empty_dist = tmp_path / "non_existent_dist"
    monkeypatch.setattr("eval_runner.console.app.UI_BUILD_DIR", fake_empty_dist)

    with pytest.raises(RuntimeError, match="Visual Console frontend bundle missing"):
        create_app()


# ==============================================================================
# Control plane endpoints excluded from default OSS console registration
# ==============================================================================


def test_control_plane_endpoints_excluded_from_oss_console(monkeypatch):
    from eval_runner.console.app import create_app

    monkeypatch.delenv("AGENTV_ENV", raising=False)
    app = create_app()

    client = app.test_client()
    # /api/v1/publish and /api/v1/compliance-packs should 404 (not registered in OSS console)
    pub_res = client.post("/api/v1/publish", json={})
    assert pub_res.status_code == 404

    packs_res = client.get("/api/v1/compliance-packs")
    assert packs_res.status_code == 404
