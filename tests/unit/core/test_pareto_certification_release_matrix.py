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

    if write_manifest:
        exec_manifest = ExecutionManifest(
            manifest_id=f"man_{run_id}",
            scenario_id=scen_id,
            scenario_version=scen_ver,
            scenario_hash=scen_hash,
        )
        (vault / "execution_manifest.json").write_text(
            json.dumps(exec_manifest.to_dict()), encoding="utf-8"
        )
        exec_manifest.compute_manifest_hash()

    final_events = list(events)
    if evaluator_finalization is not None:
        fin_dict = evaluator_finalization.to_dict()
        if not fin_dict.get("finalization_hash"):
            fin_dict["finalization_hash"] = evaluator_finalization.compute_finalization_hash()
        final_events.append({"event": "evaluator_finalization", "data": fin_dict})

    with open(trace, "w", encoding="utf-8") as f:
        for ev in final_events:
            f.write(json.dumps(ev) + "\n")

    return vault, trace


# ==============================================================================
# Vector 1: Missing EvaluatorFinalizationRecord fails closed
# ==============================================================================


def test_matrix_vector_1_missing_evaluator_finalization_fails_closed(matrix_env):
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
# Vector 2: EvaluatorFinalizationRecord with altered scenario_hash fails closed
# ==============================================================================


def test_matrix_vector_2_altered_scenario_hash_fails_closed(matrix_env):
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
# Vector 3: EvaluatorFinalizationRecord with tampered finalization_hash fails closed
# ==============================================================================


def test_matrix_vector_3_tampered_finalization_hash_fails_closed(matrix_env):
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
        finalization_hash="sha3_256:forged_hash_value_that_does_not_match_computed",
    )
    vault, trace = _build_test_run(
        matrix_env["runs"], run_id, events, scen_data, evaluator_finalization=fin_rec
    )

    with pytest.raises(ValueError, match="inconclusive outcome"):
        execute_industrial_certification(run_id=run_id, scenario_data=scen_data)


# ==============================================================================
# Vector 4: EvaluatorFinalizationRecord with missing required oracle fails closed
# ==============================================================================


def test_matrix_vector_4_missing_required_oracle_fails_closed(matrix_env):
    run_id = "run-v4-missing-oracle"
    scen_data = {"id": "scen_v4", "version": "1.0.0"}
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
# Vector 5: Trace append during FINALIZING / SEALED lifecycle state raises TraceClosedError
# ==============================================================================


def test_matrix_vector_5_trace_append_blocked_during_finalizing_or_sealed(matrix_env):
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
# Vector 6: Per-run certification lock acquisition: active PID blocks, dead PID recovers
# ==============================================================================


def test_matrix_vector_6_lock_fencing_active_pid_blocks_and_dead_pid_recovers(matrix_env):
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
# Vector 7: VerificationPackage verification fails closed if scenario or manifest hash is altered
# ==============================================================================


def test_matrix_vector_7_verification_package_fails_on_altered_scenario_or_manifest(matrix_env):
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
# Vector 8: VerificationPackage verification with authentic vs altered external trust anchor
# ==============================================================================


def test_matrix_vector_8_external_trust_anchor_verification(matrix_env):
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
