"""
tests/unit/core/test_certification_service_and_trust_boundary.py

Comprehensive test suite verifying the authoritative CertificationService domain service
and hardened trust boundary contracts:
1. Inconclusive evaluation outcome fails closed (cannot be overridden by caller).
2. Prior run_manifest.json is never used as source of truth (no circular trust).
3. Failed evaluation outcome produces a failure attestation, never a compliance pass.
4. Provisional/simulated execution modes fail closed against authoritative certification.
5. Verification independently verifies cryptographic validity and evaluation verdict.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from flask import Flask

from agentv_runtime.finalization import EvaluatorFinalizationRecord
from agentv_runtime.manifest import compute_scenario_hash
from eval_runner import config
from eval_runner.console.routes.trust import trust_bp
from eval_runner.identity import IdentityService
from eval_runner.services.certification import (
    CertificationService,
    execute_industrial_certification,
)


@pytest.fixture
def cert_vault(tmp_path, monkeypatch):
    root = tmp_path / "project"
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
    IdentityService._provision_local_identity("test_signer")
    IdentityService._provision_local_identity("eval_kernel")

    return {"root": root, "runs": runs, "reports": reports, "trust": trust}


def _create_trace(
    runs_dir: Path,
    run_id: str,
    events: list[dict],
    auto_finalize: bool = True,
    scenario_data: Mapping[str, Any] | None = None,
) -> tuple[Path, Path]:
    vault = runs_dir / run_id
    vault.mkdir(parents=True, exist_ok=True)
    trace = vault / "run.jsonl"

    final_events = list(events)
    has_finalization = any(e.get("event") == "evaluator_finalization" for e in final_events)

    terminal_count = sum(
        1 for e in final_events if e.get("event") in ("session_decision", "evaluation_result")
    )
    if auto_finalize and not has_finalization and terminal_count == 1:
        scen_id = "scen_1"
        scen_hash = None
        if scenario_data:
            scen_id = scenario_data.get("id") or scenario_data.get("scenario_id") or scen_id
            scen_hash = compute_scenario_hash(scenario_data)
        else:
            for e in final_events:
                if e.get("event") in ("run_start", "start"):
                    scen_id = e.get("scenario_id") or scen_id
                    scen_hash = e.get("scenario_hash")
            if not scen_hash:
                scen_hash = compute_scenario_hash({"id": scen_id, "version": "1.0.0"})

        from agentv_runtime.evidence_graph import (
            build_evidence_graph_from_events,
            compute_evidence_graph_root,
        )
        from agentv_runtime.manifest import ExecutionManifest

        exec_manifest = ExecutionManifest(
            manifest_id=f"man_{run_id}",
            scenario_id=scen_id,
            scenario_version="1.0.0",
            scenario_hash=scen_hash,
        )
        exec_manifest_path = vault / "execution_manifest.json"
        exec_manifest_path.write_text(json.dumps(exec_manifest.to_dict()), encoding="utf-8")
        m_hash = exec_manifest.compute_manifest_hash()

        ev_graph = build_evidence_graph_from_events(final_events)
        ev_root = compute_evidence_graph_root(ev_graph)

        term_ev = next(
            e
            for e in reversed(final_events)
            if e.get("event") in ("session_decision", "evaluation_result")
        )
        data = term_ev.get("data", {}) if isinstance(term_ev.get("data"), dict) else term_ev
        dec_str = str(data.get("decision") or data.get("status") or "").upper()
        outcome = "pass" if dec_str == "PASS" else "fail"
        score = float(
            data.get("score")
            if data.get("score") is not None
            else (1.0 if outcome == "pass" else 0.0)
        )

        fin_rec = EvaluatorFinalizationRecord(
            finalization_id=f"fin_{run_id}",
            run_id=run_id,
            execution_manifest_hash=m_hash,
            scenario_id=scen_id,
            scenario_version="1.0.0",
            scenario_hash=scen_hash,
            evaluator_identity="eval_kernel",
            evaluator_config_hash="sha3_256:0000000000000000000000000000000000000000000000000000000000000000",
            required_oracle_ids=[],
            evidence_root_hash=ev_root,
            outcome=outcome,
            score=score,
        )
        fin_rec = fin_rec.sign()
        fin_dict = fin_rec.to_dict()
        final_events.append({"event": "evaluator_finalization", "data": fin_dict})

    with open(trace, "w", encoding="utf-8") as f:
        for ev in final_events:
            f.write(json.dumps(ev) + "\n")
    return vault, trace


def test_inconclusive_run_cannot_be_certified(cert_vault):
    """Missing or ambiguous terminal evaluation outcome must hard-fail certification."""
    run_id = "run-inconclusive-001"
    events = [
        {"event": "run_start", "execution_mode": "live", "data": {"execution_mode_declared": True}},
        {"event": "step_executed", "data": {"step": 1}},
    ]
    _create_trace(cert_vault["runs"], run_id, events)

    # Calling execute_industrial_certification without terminal outcome must raise ValueError
    with pytest.raises(ValueError, match="inconclusive outcome"):
        CertificationService.execute_industrial_certification(run_id=run_id)


def test_inconclusive_run_cannot_be_certified_with_caller_status_override(cert_vault):
    """Caller supplying status='pass' cannot bypass fail-closed inconclusive outcome check."""
    run_id = "run-inconclusive-override"
    events = [
        {"event": "run_start", "execution_mode": "live", "data": {"execution_mode_declared": True}},
        {"event": "step_executed", "data": {"step": 1}},
    ]
    _create_trace(cert_vault["runs"], run_id, events)

    with pytest.raises(ValueError, match="inconclusive outcome"):
        execute_industrial_certification(run_id=run_id, status="pass", score=1.0)


def test_previous_run_manifest_cannot_circularly_influence_certification(cert_vault):
    """A prior run_manifest.json with fake PASS status must NOT influence new certification."""
    run_id = "run-no-circular-trust"
    scen_data = {"id": "scen_fail", "version": "1.0.0"}
    # Raw trace indicates an authoritative FAIL
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_fail"},
        {"event": "assertion_evaluated", "assertion": "oracle_check", "passed": False},
        {"event": "session_decision", "data": {"decision": "FAIL", "score": 0.2}},
    ]
    vault, trace = _create_trace(cert_vault["runs"], run_id, events, scenario_data=scen_data)

    # Write a malicious / stale manifest in the vault claiming "certified" and score 1.0
    stale_manifest = vault / "run_manifest.json"
    stale_manifest.write_text(
        json.dumps(
            {
                "compliance_status": "pass",
                "compliance_score": 1.0,
                "status": "certified",
            }
        ),
        encoding="utf-8",
    )

    # Certification must derive outcome from the trace, recognizing FAIL
    res = CertificationService.execute_industrial_certification(
        run_id=run_id,
        scenario_data=scen_data,
    )
    assert res["certified"] is False
    assert res["status"] == "attested_failed"
    assert res["compliance_status"] == "fail"
    assert res["score"] == 0.2


def test_failed_evaluation_cannot_produce_pass_certificate(cert_vault):
    """Even if caller asks for status='pass', a failed evaluation fails closed."""
    run_id = "run-fail-closed-test"
    scen_data = {"id": "scen_fail2", "version": "1.0.0"}
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_fail2"},
        {"event": "assertion_evaluated", "assertion": "oracle_check", "passed": False},
        {"event": "evaluation_result", "data": {"status": "FAIL", "score": 0.0}},
    ]
    _create_trace(cert_vault["runs"], run_id, events, scenario_data=scen_data)

    res = execute_industrial_certification(
        run_id=run_id,
        status="pass",
        score=1.0,
        scenario_data=scen_data,
    )
    assert res["certified"] is False
    assert res["status"] == "attested_failed"
    assert res["compliance_status"] == "fail"
    assert res["score"] == 0.0


def test_provisional_simulated_mode_rejected_for_authoritative_certification(cert_vault):
    """Simulated or undeclared provisional runs cannot issue authoritative certificates."""
    run_id = "run-simulated-provisional"
    scen_data = {"id": "scen_sim", "version": "1.0.0"}
    events = [
        {
            "event": "run_start",
            "execution_mode": "simulated",
            "scenario_id": "scen_sim",
            "data": {"provisional": True},
        },
        {"event": "assertion_evaluated", "assertion": "oracle_check", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    _create_trace(cert_vault["runs"], run_id, events, scenario_data=scen_data)

    with pytest.raises(ValueError, match="is provisional"):
        execute_industrial_certification(run_id=run_id, scenario_data=scen_data)


def test_passing_authoritative_run_certified_successfully(cert_vault):
    """Passing live run is properly certified with genuine signature."""
    run_id = "run-passing-live"
    scen_data = {"id": "scen_pass", "version": "1.0.0"}
    events = [
        {
            "event": "run_start",
            "execution_mode": "live",
            "scenario_id": "scen_pass",
            "data": {"execution_mode_declared": True},
        },
        {"event": "assertion_evaluated", "assertion": "oracle_check", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    _create_trace(cert_vault["runs"], run_id, events, scenario_data=scen_data)

    res = execute_industrial_certification(
        run_id=run_id,
        identity_id="system_id",
        policy_ref="NIST-AI-100",
        scenario_data=scen_data,
    )
    assert res["certified"] is True
    assert res["status"] == "certified"
    assert res["compliance_status"] == "pass"
    assert res["score"] == 1.0
    assert "trace_hash" in res["manifest"]


def test_public_verification_endpoint_semantics(cert_vault):
    """GET /v1/verify/<run_id> independently reports cryptographic and evaluation compliance."""
    app = Flask(__name__)
    app.register_blueprint(trust_bp)

    client = app.test_client()

    run_id = "run-verify-endpoint"
    scen_data = {"id": "scen_verify", "version": "1.0.0"}
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_verify"},
        {"event": "assertion_evaluated", "assertion": "oracle_check", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 0.98}},
    ]
    _create_trace(cert_vault["runs"], run_id, events, scenario_data=scen_data)

    execute_industrial_certification(
        run_id=run_id,
        identity_id="system_id",
        scenario_data=scen_data,
    )

    res = client.get(f"/api/v1/verify/{run_id}")
    assert res.status_code == 200
    data = res.get_json()
    assert data["verified"] is True
    assert data["cryptographically_valid"] is True
    assert data["evaluation_passed"] is True
    assert data["certificate_authoritative"] is True


def test_invalid_run_ids_rejected(cert_vault):
    """Verify invalid and path-traversal run IDs are rejected with ValueError."""
    for bad_id in ("", 123, "../escape", "run/nested", "run\\slashes"):
        with pytest.raises(ValueError, match="Invalid or unsafe run_id"):
            execute_industrial_certification(run_id=bad_id)  # type: ignore


def test_metadata_binding_with_corrupt_lines_and_attributes(cert_vault):
    """Verify metadata extraction extracts bound scenario and agent identity attributes."""
    run_id = "run-meta-binding"
    scen_data = {"id": "scen_1", "version": "1.0.0"}
    events = [
        {
            "event": "run_start",
            "execution_mode": "live",
            "scenario_id": "scen_1",
            "agent_id": "ag_1",
        },
        {"event": "assertion_evaluated", "assertion": "oracle_check", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    vault, trace = _create_trace(cert_vault["runs"], run_id, events, scenario_data=scen_data)

    # Prepend empty lines to verify blank line resilience in trace parser
    original_text = trace.read_text(encoding="utf-8")
    trace.write_text("\n\n" + original_text, encoding="utf-8")

    res = execute_industrial_certification(
        run_id=run_id,
        identity_id="system_id",
        scenario_data=scen_data,
    )
    assert res["certified"] is True
    assert res["manifest"]["metadata"]["scenario_id"] == "scen_1"
    assert res["manifest"]["metadata"]["agent_id"] == "ag_1"


def test_count_assertion_and_evidence_nodes_branches(tmp_path):
    # 1. Nonexistent trace
    nonexistent = tmp_path / "nonexistent.jsonl"
    assert CertificationService.count_assertion_and_evidence_nodes(nonexistent) == 0

    # 2. Trace with blank lines, corrupt lines, and substantive evidence events
    trace_file = tmp_path / "test_trace.jsonl"
    lines = [
        "",
        "   ",
        "corrupt-non-json-line",
        json.dumps({"event": "step_executed"}),
        json.dumps({"event": "other", "assertion": "a1"}),
        json.dumps({"event": "custom_event", "data": {"oracle_results": [{"passed": True}]}}),
        json.dumps({"event": "custom_event2", "metrics": [{"score": 1.0}]}),
        json.dumps({"event": "unrelated_event", "data": {"unrelated": 123}}),
    ]
    trace_file.write_text("\n".join(lines), encoding="utf-8")
    count = CertificationService.count_assertion_and_evidence_nodes(trace_file)
    assert count == 4


def test_extract_finalization_record_branches(tmp_path):
    # 1. Nonexistent trace returns None
    assert CertificationService.extract_finalization_record(tmp_path / "none.jsonl") is None

    # 2. Trace with run_end carrying finalization payload
    priv = IdentityService.get_private_key("system_id")
    rec = EvaluatorFinalizationRecord(
        finalization_id="fin_embedded",
        run_id="run_embedded",
        execution_manifest_hash="sha3_256:1111",
        scenario_id="scen_emb",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:2222",
        evaluator_identity="system_id",
        evaluator_config_hash="sha3_256:3333",
        required_oracle_ids=[],
        evidence_root_hash="sha3_256:4444",
        outcome="pass",
        score=1.0,
        terminal_seq=1,
    ).sign(priv)

    trace_file = tmp_path / "emb_trace.jsonl"
    lines = [
        "",
        "corrupt line",
        json.dumps({"event": "run_start", "scenario_id": "scen_emb"}),
        json.dumps({"event": "run_end", "data": {"finalization": rec.to_dict()}}),
    ]
    trace_file.write_text("\n".join(lines), encoding="utf-8")
    extracted = CertificationService.extract_finalization_record(trace_file)
    assert extracted is not None
    assert extracted.finalization_id == "fin_embedded"

    # 3. Hash mismatch in finalization raises ValueError
    corrupt_rec_dict = rec.to_dict()
    corrupt_rec_dict["finalization_hash"] = "sha3_256:" + "0" * 64
    trace_bad = tmp_path / "bad_trace.jsonl"
    trace_bad.write_text(
        json.dumps({"event": "evaluator_finalization", "data": corrupt_rec_dict}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="FinalizationHashMismatch"):
        CertificationService.extract_finalization_record(trace_bad)


def test_certification_scenario_id_mismatch(cert_vault):
    run_id = "run-scen-id-mismatch"
    scen_data = {"id": "scen_expected", "version": "1.0.0"}
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_expected"},
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    _create_trace(cert_vault["runs"], run_id, events, scenario_data=scen_data)

    # Calling certification with scenario_data having different id raises ScenarioIdMismatch
    mismatched_scen = {"id": "scen_different", "version": "1.0.0"}
    with pytest.raises(ValueError, match="ScenarioIdMismatch"):
        execute_industrial_certification(
            run_id=run_id,
            identity_id="system_id",
            scenario_data=mismatched_scen,
        )


def test_certification_corrupt_manifest_file(cert_vault):
    run_id = "run-corrupt-manifest"
    scen_data = {"id": "scen_manifest", "version": "1.0.0"}
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_manifest"},
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    vault, _ = _create_trace(cert_vault["runs"], run_id, events, scenario_data=scen_data)

    # Overwrite execution_manifest.json with corrupt non-JSON content
    manifest_file = vault / "execution_manifest.json"
    manifest_file.write_text("not-a-valid-json", encoding="utf-8")

    with pytest.raises(ValueError, match="Expecting value|Invalid execution manifest"):
        execute_industrial_certification(
            run_id=run_id,
            identity_id="system_id",
            scenario_data=scen_data,
        )


def test_certification_manifest_non_value_error(cert_vault, monkeypatch):
    """Verify behavior when execution_manifest processing raises non-ValueError."""
    run_id = "run-manifest-type-error"
    scen_data = {"id": "scen_manifest", "version": "1.0.0"}
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_manifest"},
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    _create_trace(cert_vault["runs"], run_id, events, scenario_data=scen_data)

    from agentv_runtime.manifest import ExecutionManifest

    def _raise_type_error(*args, **kwargs):
        raise TypeError("Corrupt manifest schema data type")

    monkeypatch.setattr(ExecutionManifest, "from_dict", _raise_type_error)

    with pytest.raises(ValueError, match="Invalid execution manifest in"):
        execute_industrial_certification(
            run_id=run_id,
            identity_id="system_id",
            scenario_data=scen_data,
        )


def test_certification_unresolvable_scenario(cert_vault):
    run_id = "run-unresolvable-scen"
    events = [
        {
            "event": "run_start",
            "execution_mode": "live",
            "scenario_id": "scen_unknown_never_exists",
        },
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    _create_trace(
        cert_vault["runs"],
        run_id,
        events,
        scenario_data={"id": "scen_unknown_never_exists", "version": "1.0.0"},
    )

    # Do not pass scenario_data, forcing resolution from disk which fails
    with pytest.raises(ValueError, match="cannot resolve authoritative scenario definition"):
        execute_industrial_certification(
            run_id=run_id,
            identity_id="system_id",
            scenario_data=None,
        )


def test_read_run_truth_level_edge_cases(cert_vault, monkeypatch):
    """Verify edge cases and resilience in read_run_truth_level."""
    assert CertificationService.read_run_truth_level("") == (None, False)
    assert CertificationService.read_run_truth_level("../unsafe_run") == (None, False)
    assert CertificationService.read_run_truth_level("nonexistent_run_dir") == (None, False)

    # Sub-case: run_start with no execution_mode declared
    run_no_mode = "run-no-mode"
    v_no_mode = cert_vault["runs"] / run_no_mode
    v_no_mode.mkdir(parents=True, exist_ok=True)
    (v_no_mode / "run.jsonl").write_text(
        json.dumps({"event": "run_start", "data": {}}) + "\n", encoding="utf-8"
    )
    mode_nm, prov_nm = CertificationService.read_run_truth_level(run_no_mode)
    assert mode_nm == "unknown"
    assert prov_nm is True

    run_id = "run-truth-corrupt"
    vault = cert_vault["runs"] / run_id
    vault.mkdir(parents=True, exist_ok=True)
    trace = vault / "run.jsonl"
    with open(trace, "w", encoding="utf-8") as f:
        f.write("not-valid-json\n")
        f.write(json.dumps({"event": "heartbeat", "data": {}}) + "\n")
        f.write(json.dumps({"event": "step", "data": {}}) + "\n")

    mode, is_prov = CertificationService.read_run_truth_level(run_id)
    assert mode == "unknown"
    assert is_prov is True

    def _raise_open(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr("builtins.open", _raise_open)
    mode_err, prov_err = CertificationService.read_run_truth_level(run_id)
    assert mode_err == "unknown"
    assert prov_err is True


def test_count_assertion_and_evidence_nodes_exception_fallback(tmp_path, monkeypatch):
    """Verify count_assertion_and_evidence_nodes handles read errors cleanly."""
    target_trace = tmp_path / "dummy_trace.jsonl"
    target_trace.write_text("dummy", encoding="utf-8")

    def _raise_open(*args, **kwargs):
        raise OSError("Disk failure")

    monkeypatch.setattr("builtins.open", _raise_open)
    count = CertificationService.count_assertion_and_evidence_nodes(target_trace)
    assert count == 0


def test_extract_finalization_record_edge_cases(cert_vault, monkeypatch):
    """Verify edge cases for extract_finalization_record."""
    run_id = "run-fin-toplevel"
    vault = cert_vault["runs"] / run_id
    vault.mkdir(parents=True, exist_ok=True)
    trace = vault / "run.jsonl"

    fin_rec = EvaluatorFinalizationRecord(
        finalization_id="fin_toplevel",
        run_id=run_id,
        execution_manifest_hash="sha3_256:" + "1" * 64,
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:" + "2" * 64,
        evaluator_identity="eval_kernel",
        evaluator_config_hash="sha3_256:" + "3" * 64,
        required_oracle_ids=[],
        evidence_root_hash="sha3_256:" + "4" * 64,
        outcome="pass",
        score=1.0,
    ).sign()

    # ev["data"] is dict without finalization; ev["finalization"] has the finalization payload
    trace.write_text(
        json.dumps(
            {"event": "run_end", "data": {"status": "ok"}, "finalization": fin_rec.to_dict()}
        )
        + "\n",
        encoding="utf-8",
    )
    extracted = CertificationService.extract_finalization_record(trace)
    assert extracted is not None
    assert extracted.finalization_id == "fin_toplevel"

    # Sub-case B: Hash mismatch in finalization record
    fin_dict_bad_hash = fin_rec.to_dict()
    fin_dict_bad_hash["finalization_hash"] = "sha3_256:" + "0" * 64
    trace_bad_hash = vault / "bad_hash.jsonl"
    trace_bad_hash.write_text(
        json.dumps({"event": "evaluator_finalization", "data": fin_dict_bad_hash}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="FinalizationHashMismatch"):
        CertificationService.extract_finalization_record(trace_bad_hash)

    # Sub-case C: Evaluator identity not authorized in external trust root
    fin_untrusted = EvaluatorFinalizationRecord(
        finalization_id="fin_untrusted",
        run_id=run_id,
        execution_manifest_hash="sha3_256:" + "1" * 64,
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:" + "2" * 64,
        evaluator_identity="unauthorized_evaluator",
        evaluator_config_hash="sha3_256:" + "3" * 64,
        required_oracle_ids=[],
        evidence_root_hash="sha3_256:" + "4" * 64,
        outcome="pass",
        score=1.0,
    )
    fin_untrusted_dict = fin_untrusted.to_dict()
    fin_untrusted_dict["finalization_hash"] = fin_untrusted.compute_finalization_hash()
    fin_untrusted_dict["evaluator_signature"] = "dummy_sig"

    trace_untrusted = vault / "untrusted.jsonl"
    trace_untrusted.write_text(
        json.dumps({"event": "evaluator_finalization", "data": fin_untrusted_dict}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="EvaluatorIdentityUntrusted"):
        CertificationService.extract_finalization_record(trace_untrusted)

    # Sub-case D: Evaluator signature invalid
    fin_bad_sig = fin_rec.to_dict()
    fin_bad_sig["evaluator_signature"] = (
        "aW52YWxpZF9zaWduYXR1cmVfYnl0ZXNfZm9yX2VkMjU1MTlfMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAw"
    )
    trace_bad_sig = vault / "bad_sig.jsonl"
    trace_bad_sig.write_text(
        json.dumps({"event": "evaluator_finalization", "data": fin_bad_sig}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="EvaluatorSignatureInvalid"):
        CertificationService.extract_finalization_record(trace_bad_sig)

    # Sub-case E: Non-ValueError exception returns None
    def _raise_io(*args, **kwargs):
        raise OSError("Read failed")

    monkeypatch.setattr("builtins.open", _raise_io)
    assert CertificationService.extract_finalization_record(trace) is None


def test_extract_computed_run_outcome_edge_cases(cert_vault):
    """Verify extract_computed_run_outcome boundary conditions and defenses."""
    run_id = "run-outcome-edges"
    vault = cert_vault["runs"] / run_id
    vault.mkdir(parents=True, exist_ok=True)
    trace = vault / "run.jsonl"

    fin_rec = EvaluatorFinalizationRecord(
        finalization_id="fin_outcome",
        run_id=run_id,
        execution_manifest_hash="sha3_256:" + "1" * 64,
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:" + "2" * 64,
        evaluator_identity="eval_kernel",
        evaluator_config_hash="sha3_256:" + "3" * 64,
        required_oracle_ids=[],
        evidence_root_hash="sha3_256:" + "4" * 64,
        outcome="pass",
        score=1.0,
    ).sign()

    # Sub-case A: Non-finalization event appended after finalization marker
    with open(trace, "w", encoding="utf-8") as f:
        f.write("corrupt-line\n")
        f.write(json.dumps({"event": "evaluator_finalization", "data": fin_rec.to_dict()}) + "\n")
        f.write(json.dumps({"event": "tamper_post_final", "data": {}}) + "\n")

    status, score = CertificationService.extract_computed_run_outcome(vault, trace)
    assert status == "inconclusive"
    assert score == 0.0

    # Sub-case B: Finalization in ev["finalization"] with ev["data"] having no finalization
    trace_run_end_top = vault / "run_end_top.jsonl"
    with open(trace_run_end_top, "w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {"event": "run_end", "data": {"status": "ok"}, "finalization": fin_rec.to_dict()}
            )
            + "\n"
        )
    s_top, sc_top = CertificationService.extract_computed_run_outcome(vault, trace_run_end_top)
    assert s_top == "pass"
    assert sc_top == 1.0

    # Sub-case B2: Finalization in ev["data"]["finalization"]
    trace_run_end_data = vault / "run_end_data.jsonl"
    with open(trace_run_end_data, "w", encoding="utf-8") as f:
        f.write(
            json.dumps({"event": "run_end", "data": {"finalization": fin_rec.to_dict()}}) + "\n"
        )
    s_data, sc_data = CertificationService.extract_computed_run_outcome(vault, trace_run_end_data)
    assert s_data == "pass"
    assert sc_data == 1.0

    # Sub-case C: Duplicate finalization records in trace
    trace_multi_fin = vault / "multi_fin.jsonl"
    with open(trace_multi_fin, "w", encoding="utf-8") as f:
        f.write(json.dumps({"event": "evaluator_finalization", "data": fin_rec.to_dict()}) + "\n")
        f.write(json.dumps({"event": "evaluator_finalization", "data": fin_rec.to_dict()}) + "\n")
    s_multi, _ = CertificationService.extract_computed_run_outcome(vault, trace_multi_fin)
    assert s_multi == "inconclusive"

    # Sub-case D: Multiple terminal events without finalization
    trace_multi_term = vault / "multi_term.jsonl"
    with open(trace_multi_term, "w", encoding="utf-8") as f:
        f.write(json.dumps({"event": "session_decision", "data": {"status": "pass"}}) + "\n")
        f.write(json.dumps({"event": "session_decision", "data": {"status": "pass"}}) + "\n")
    s_term, _ = CertificationService.extract_computed_run_outcome(vault, trace_multi_term)
    assert s_term == "inconclusive"

    # Sub-case E: Untrusted evaluator in finalization
    fin_unauth = fin_rec.to_dict()
    fin_unauth["evaluator_identity"] = "untrusted_evaluator"
    fin_unauth["finalization_hash"] = EvaluatorFinalizationRecord.from_dict(
        fin_unauth, require_authoritative=False
    ).compute_finalization_hash()
    trace_unauth = vault / "unauth.jsonl"
    trace_unauth.write_text(
        json.dumps({"event": "evaluator_finalization", "data": fin_unauth}) + "\n",
        encoding="utf-8",
    )
    s_ua, _ = CertificationService.extract_computed_run_outcome(vault, trace_unauth)
    assert s_ua == "inconclusive"

    # Sub-case F: Malformed finalization payload causing exception in from_dict
    trace_malformed_fin = vault / "malformed_fin.jsonl"
    trace_malformed_fin.write_text(
        json.dumps({"event": "evaluator_finalization", "data": {"not_valid": True}}) + "\n",
        encoding="utf-8",
    )
    s_mal, _ = CertificationService.extract_computed_run_outcome(vault, trace_malformed_fin)
    assert s_mal == "inconclusive"

    # Sub-case G: Status evaluation_invalid
    trace_invalid = vault / "invalid.jsonl"
    trace_invalid.write_text(
        json.dumps({"event": "session_decision", "data": {"status": "evaluation_invalid"}}) + "\n",
        encoding="utf-8",
    )
    s_inv, sc_inv = CertificationService.extract_computed_run_outcome(vault, trace_invalid)
    assert s_inv == "fail"
    assert sc_inv == 0.0

    # Sub-case H: Contradictory decisions between prior event and finalization
    trace_contradict = vault / "contradict.jsonl"
    with open(trace_contradict, "w", encoding="utf-8") as f:
        f.write(json.dumps({"event": "session_decision", "data": {"status": "fail"}}) + "\n")
        f.write(json.dumps({"event": "evaluator_finalization", "data": fin_rec.to_dict()}) + "\n")
    s_con, _ = CertificationService.extract_computed_run_outcome(vault, trace_contradict)
    assert s_con == "inconclusive"

    # Sub-case I: IO error / nonexistent file
    s_err, _ = CertificationService.extract_computed_run_outcome(vault, vault / "nonexistent.jsonl")
    assert s_err == "inconclusive"


def test_execute_industrial_certification_boundary_branches(cert_vault, monkeypatch):
    """Verify execution certification boundary branches and validations."""
    with pytest.raises(FileNotFoundError, match="Run vault not found"):
        execute_industrial_certification("nonexistent_run_404")

    run_id_no_fin = "run-no-fin"
    events_no_fin = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_1"},
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    _create_trace(
        cert_vault["runs"],
        run_id_no_fin,
        events_no_fin,
        auto_finalize=False,
        scenario_data={"id": "scen_1", "version": "1.0.0"},
    )
    with pytest.raises(
        ValueError, match="missing mandatory authoritative EvaluatorFinalizationRecord"
    ):
        execute_industrial_certification(
            run_id_no_fin, scenario_data={"id": "scen_1", "version": "1.0.0"}
        )

    run_id_mismatch = "run-mismatch-id"
    scen_data = {"id": "scen_1", "version": "1.0.0"}
    vault_mismatch, _ = _create_trace(
        cert_vault["runs"],
        run_id_mismatch,
        events_no_fin,
        auto_finalize=True,
        scenario_data=scen_data,
    )
    m_path = vault_mismatch / "execution_manifest.json"
    from agentv_runtime.manifest import ExecutionManifest

    m_obj = ExecutionManifest.from_dict(json.loads(m_path.read_text(encoding="utf-8")))
    m_hash = m_obj.compute_manifest_hash()

    from agentv_runtime.evidence_graph import (
        build_evidence_graph_from_events,
        compute_evidence_graph_root,
    )

    ev_graph = build_evidence_graph_from_events(events_no_fin)
    ev_root = compute_evidence_graph_root(ev_graph)

    fin_wrong_run = EvaluatorFinalizationRecord(
        finalization_id="fin_wrong",
        run_id="DIFFERENT_RUN_ID",
        execution_manifest_hash=m_hash,
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash=compute_scenario_hash(scen_data),
        evaluator_identity="eval_kernel",
        evaluator_config_hash="sha3_256:" + "0" * 64,
        required_oracle_ids=[],
        evidence_root_hash=ev_root,
        outcome="pass",
        score=1.0,
    ).sign()

    trace_mismatch = vault_mismatch / "run.jsonl"
    with open(trace_mismatch, "w", encoding="utf-8") as f:
        for ev in events_no_fin:
            f.write(json.dumps(ev) + "\n")
        f.write(
            json.dumps({"event": "evaluator_finalization", "data": fin_wrong_run.to_dict()}) + "\n"
        )

    with pytest.raises(ValueError, match="FinalizationRunIdMismatch"):
        execute_industrial_certification(run_id_mismatch, scenario_data=scen_data)

    run_id_embedded = "run-embedded-scen"
    events_embedded = [
        {
            "event": "run_start",
            "execution_mode": "live",
            "scenario_id": "scen_embedded",
            "scenario_data": {"id": "scen_embedded", "version": "1.0.0"},
        },
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    _create_trace(
        cert_vault["runs"],
        run_id_embedded,
        events_embedded,
        auto_finalize=True,
        scenario_data={"id": "scen_embedded", "version": "1.0.0"},
    )
    res_emb = execute_industrial_certification(run_id_embedded, scenario_data=None)
    assert res_emb["status"] == "certified"

    run_id_ev_mismatch = "run-ev-root-mismatch"
    vault_ev, _ = _create_trace(
        cert_vault["runs"],
        run_id_ev_mismatch,
        events_no_fin,
        auto_finalize=True,
        scenario_data=scen_data,
    )
    fin_bad_ev = EvaluatorFinalizationRecord(
        finalization_id="fin_bad_ev",
        run_id=run_id_ev_mismatch,
        execution_manifest_hash=m_hash,
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash=compute_scenario_hash(scen_data),
        evaluator_identity="eval_kernel",
        evaluator_config_hash="sha3_256:" + "0" * 64,
        required_oracle_ids=[],
        evidence_root_hash="sha3_256:" + "f" * 64,
        outcome="pass",
        score=1.0,
    ).sign()
    trace_bad_ev = vault_ev / "run.jsonl"
    with open(trace_bad_ev, "w", encoding="utf-8") as f:
        for ev in events_no_fin:
            f.write(json.dumps(ev) + "\n")
        f.write(
            json.dumps({"event": "evaluator_finalization", "data": fin_bad_ev.to_dict()}) + "\n"
        )

    with pytest.raises(ValueError, match="EvidenceRootMismatch"):
        execute_industrial_certification(run_id_ev_mismatch, scenario_data=scen_data)

    from agentv_runtime import evidence_graph

    orig_build = evidence_graph.build_evidence_graph_from_events

    def _mock_build_evidence_graph(*args, **kwargs):
        g = orig_build(*args, **kwargs)
        g["is_complete_provenance"] = False
        return g

    monkeypatch.setattr(
        evidence_graph, "build_evidence_graph_from_events", _mock_build_evidence_graph
    )
    run_id_prov = "run-prov-violation"
    _create_trace(
        cert_vault["runs"],
        run_id_prov,
        events_no_fin,
        auto_finalize=True,
        scenario_data=scen_data,
    )
    with pytest.raises(ValueError, match="DirectProvenanceViolation"):
        execute_industrial_certification(run_id_prov, scenario_data=scen_data)
    monkeypatch.setattr(evidence_graph, "build_evidence_graph_from_events", orig_build)

    from eval_runner import loader

    monkeypatch.setattr(loader, "load_scenario", lambda sid: {"id": sid, "version": "1.0.0"})

    run_id_load = "run-load-scen"
    _create_trace(
        cert_vault["runs"],
        run_id_load,
        events_no_fin,
        auto_finalize=True,
        scenario_data=scen_data,
    )
    res_loaded = execute_industrial_certification(run_id_load, scenario_data=None)
    assert res_loaded["status"] == "certified"

    monkeypatch.setattr(loader, "load_scenario", lambda sid: [{"id": sid, "version": "1.0.0"}])
    run_id_load_list = "run-load-scen-list"
    _create_trace(
        cert_vault["runs"],
        run_id_load_list,
        events_no_fin,
        auto_finalize=True,
        scenario_data=scen_data,
    )
    res_loaded_list = execute_industrial_certification(run_id_load_list, scenario_data=None)
    assert res_loaded_list["status"] == "certified"

    run_id_no_m = "run-no-manifest"
    vault_no_m, _ = _create_trace(
        cert_vault["runs"],
        run_id_no_m,
        events_no_fin,
        auto_finalize=True,
        scenario_data=scen_data,
    )
    (vault_no_m / "execution_manifest.json").unlink()
    with pytest.raises(ValueError, match="ExecutionManifestMissing"):
        execute_industrial_certification(run_id_no_m, scenario_data=scen_data)

    run_id_m_mismatch = "run-manifest-mismatch"
    vault_mm, _ = _create_trace(
        cert_vault["runs"],
        run_id_m_mismatch,
        events_no_fin,
        auto_finalize=True,
        scenario_data=scen_data,
    )
    fin_bad_m = EvaluatorFinalizationRecord(
        finalization_id="fin_bad_m",
        run_id=run_id_m_mismatch,
        execution_manifest_hash="sha3_256:" + "0" * 64,
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash=compute_scenario_hash(scen_data),
        evaluator_identity="eval_kernel",
        evaluator_config_hash="sha3_256:" + "0" * 64,
        required_oracle_ids=[],
        evidence_root_hash=ev_root,
        outcome="pass",
        score=1.0,
    ).sign()
    trace_mm = vault_mm / "run.jsonl"
    with open(trace_mm, "w", encoding="utf-8") as f:
        for ev in events_no_fin:
            f.write(json.dumps(ev) + "\n")
        f.write(json.dumps({"event": "evaluator_finalization", "data": fin_bad_m.to_dict()}) + "\n")

    with pytest.raises(ValueError, match="ManifestHashMismatch"):
        execute_industrial_certification(run_id_m_mismatch, scenario_data=scen_data)

    run_id_scen_hash_mismatch = "run-scen-hash-mismatch"
    _create_trace(
        cert_vault["runs"],
        run_id_scen_hash_mismatch,
        events_no_fin,
        auto_finalize=True,
        scenario_data=scen_data,
    )
    scen_tampered = dict(scen_data)
    scen_tampered["description"] = "tampered content that changes hash"
    with pytest.raises(ValueError, match="ScenarioHashMismatch"):
        execute_industrial_certification(run_id_scen_hash_mismatch, scenario_data=scen_tampered)


def test_certification_metadata_binding_read_and_parse_error(cert_vault, monkeypatch):
    """Verify resilience when metadata binding encounters unparseable trace lines or read errors."""
    run_id = "run-meta-resilience"
    events = [
        {"event": "run_start", "execution_mode": "live", "scenario_id": "scen_1"},
        {"event": "assertion_evaluated", "assertion": "oracle_1", "passed": True},
        {"event": "session_decision", "data": {"decision": "PASS", "score": 1.0}},
    ]
    vault, _ = _create_trace(
        cert_vault["runs"],
        run_id,
        events,
        auto_finalize=True,
        scenario_data={"id": "scen_1", "version": "1.0.0"},
    )
    # Remove execution_manifest so certification fails safely at line 617 after metadata binding
    (vault / "execution_manifest.json").unlink()

    # Case 1: Corrupt line during metadata binding pass
    trace = vault / "run.jsonl"
    lines = trace.read_text(encoding="utf-8").splitlines()
    lines.insert(1, "corrupt-non-json-line")
    trace.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="ExecutionManifestMissing"):
        execute_industrial_certification(run_id, scenario_data={"id": "scen_1", "version": "1.0.0"})

    # Case 2: Read error during metadata binding pass
    orig_open = open

    def _selective_open(file, *args, **kwargs):
        filepath = str(file)
        if "run.jsonl" in filepath and ("r" in args or kwargs.get("mode", "r").startswith("r")):
            import inspect

            stack = inspect.stack()
            frame = next(
                (s for s in stack if s.function == "execute_industrial_certification"), None
            )
            # Lines 465-515 represent the metadata binding read block
            if frame and frame.lineno in range(465, 515):
                raise OSError("Simulated metadata read error")
        return orig_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _selective_open)
    with pytest.raises(ValueError, match="EvidenceRootMismatch|ExecutionManifestMissing"):
        execute_industrial_certification(run_id, scenario_data={"id": "scen_1", "version": "1.0.0"})
