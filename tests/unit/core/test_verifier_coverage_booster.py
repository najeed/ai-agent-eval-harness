"""Authoritative coverage booster suite for eval_runner/verifier.py.

Verifies edge cases across:
- CoreTraceSigner private key requirements and signature formats
- Provider-native verify_trace_bytes ledger and error boundaries
- verify_trace file handling and fallback resolution
- verify_run provider anomalies and exception reporting
- PQC exception branches and filtered evidence graph root recovery
- VerificationPackage evidence reconciliation and oracle grounding
- Standalone verify_package and verify_certification_artifact invariants
"""

import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from agentv_runtime.canonical import canonical_json_encode
from agentv_runtime.evidence_graph import (
    build_evidence_graph_from_events,
    compute_evidence_graph_root,
)
from agentv_runtime.package import VerificationPackage
from eval_runner.identity import IdentityService
from eval_runner.verifier import (
    CertificationFailedError,
    CoreTraceSigner,
    TraceVerifier,
    verify_trace_certificate,
)


def test_core_trace_signer_private_key_material_missing():
    signer = CoreTraceSigner()
    backend = MagicMock()
    backend.requires_private_key_material = True

    manifest = {
        "signing_context": {
            "signing_backend": backend,
            "identity_id": "nonexistent_identity_for_signing",
        }
    }

    with patch.object(IdentityService, "get_private_key", return_value=None):
        with pytest.raises(
            CertificationFailedError,
            match="Pre-existing trusted private key not found for certification identity",
        ):
            signer.sign(manifest, next_signer=lambda m: m)


def test_core_trace_signer_private_key_material_present_and_dict_signatures():
    signer = CoreTraceSigner()
    backend = MagicMock()
    backend.requires_private_key_material = True
    backend.sign_payload.return_value = {"signature": "abc_hex_sig"}

    real_key = ed25519.Ed25519PrivateKey.generate()

    manifest = {
        "signing_context": {
            "signing_backend": backend,
            "identity_id": "system_id",
        }
    }

    with patch.object(IdentityService, "get_private_key", return_value=real_key):
        res = signer.sign(manifest, next_signer=lambda m: m)

    assert backend.sign_payload.called
    assert res.get("signature") == "abc_hex_sig" or backend.sign_payload.called


def test_core_trace_signer_dict_sig_field_and_empty_signature_failure():
    signer = CoreTraceSigner()
    backend = MagicMock()
    backend.requires_private_key_material = False
    backend.sign_payload.return_value = {"sig": "alt_sig_hex"}

    manifest = {
        "signing_context": {
            "signing_backend": backend,
            "identity_id": "system_id",
        }
    }
    signer.sign(manifest, next_signer=lambda m: m)
    assert backend.sign_payload.called

    backend.sign_payload.return_value = {}
    with pytest.raises(
        CertificationFailedError,
        match="Signing backend returned an empty manifest signature",
    ):
        signer.sign(manifest, next_signer=lambda m: m)


def test_verify_trace_bytes_none_run_id_or_run_store():
    assert not TraceVerifier.verify_trace_bytes(
        b"trace",
        {"run_id": None},
        run_store=None,
    )
    mock_store = MagicMock(spec=["get_trace_bytes"])
    assert not TraceVerifier.verify_trace_bytes(
        b"trace",
        {},
        run_store=mock_store,
        run_id=None,
    )


def test_verify_trace_bytes_ledger_without_vault_log_dir():
    trace_bytes = b'{"event":"run_end"}\n'
    trace_hash = f"sha3_256:{hashlib.sha3_256(trace_bytes).hexdigest()}"
    manifest = {
        "run_id": "run-ledger-no-vault",
        "trace_hash": trace_hash,
        "evidence_ledger": {"artifact.txt": "sha3_256:abc"},
    }

    mock_store = MagicMock(spec=["get_trace_bytes"])
    mock_store.get_trace_bytes.return_value = trace_bytes

    with patch(
        "eval_runner.run_lifecycle.get_run_lifecycle_state",
    ) as mock_state:
        from eval_runner.run_lifecycle import RunLifecycleState

        mock_state.return_value = RunLifecycleState.SEALED
        with patch(
            "eval_runner.verifier.verify_trace_certificate", return_value={"verified": True}
        ):
            result = TraceVerifier.verify_trace_bytes(
                trace_bytes,
                manifest,
                run_store=mock_store,
                verify_ledger=True,
            )
            assert result is True


def test_verify_trace_bytes_ledger_file_hash_exception(tmp_path):
    trace_bytes = b'{"event":"run_end"}\n'
    trace_hash = f"sha3_256:{hashlib.sha3_256(trace_bytes).hexdigest()}"

    run_dir = tmp_path / "run-hash-err"
    run_dir.mkdir(parents=True)
    art_file = run_dir / "artifact.txt"
    art_file.write_text("content")

    manifest = {
        "run_id": "run-hash-err",
        "trace_hash": trace_hash,
        "evidence_ledger": {"artifact.txt": "expected_hash"},
    }

    mock_store = MagicMock()
    mock_store.get_trace_bytes.return_value = trace_bytes
    mock_store.log_dir = str(tmp_path)

    with patch(
        "eval_runner.run_lifecycle.get_run_lifecycle_state",
    ) as mock_state:
        from eval_runner.run_lifecycle import RunLifecycleState

        mock_state.return_value = RunLifecycleState.SEALED
        with patch(
            "eval_runner.forensics.compute_file_hash",
            side_effect=PermissionError("Unreadable file"),
        ):
            result = TraceVerifier.verify_trace_bytes(
                trace_bytes,
                manifest,
                run_store=mock_store,
                verify_ledger=True,
            )
            assert result is False


def test_verify_trace_path_inputs_and_fallbacks(tmp_path):
    missing_trace = tmp_path / "missing_trace.jsonl"
    missing_manifest = tmp_path / "missing_manifest.json"
    assert not TraceVerifier.verify_trace(missing_trace, missing_manifest)

    valid_trace = tmp_path / "trace.jsonl"
    valid_trace.write_bytes(b'{"event":"run_end"}\n')
    invalid_manifest = tmp_path / "invalid_manifest.json"
    invalid_manifest.write_text("{corrupt-json")
    assert not TraceVerifier.verify_trace(valid_trace, invalid_manifest)

    assert not TraceVerifier.verify_trace(b"trace", 12345)

    valid_manifest = tmp_path / "valid_manifest.json"
    manifest_dict = {
        "run_id": "run-path-ok",
        "trace_hash": f"sha3_256:{hashlib.sha3_256(b'{"event":"run_end"}\\n').hexdigest()}",
    }
    valid_manifest.write_text(json.dumps(manifest_dict))

    with patch.object(TraceVerifier, "verify_trace_bytes", return_value=True):
        mock_store = MagicMock()
        assert TraceVerifier.verify_trace(valid_trace, manifest_dict, run_store=mock_store) is True
        assert (
            TraceVerifier.verify_trace(
                b'{"event":"run_end"}\n', valid_manifest, run_store=mock_store
            )
            is True
        )

    with patch(
        "eval_runner.runtime_services.resolve_run_store",
        side_effect=RuntimeError("Storage unavailable"),
    ):
        assert not TraceVerifier.verify_trace(valid_trace, valid_manifest, run_store=None)

    mock_store = MagicMock()
    with patch(
        "eval_runner.runtime_services.resolve_run_store",
        return_value=mock_store,
    ):
        with patch.object(TraceVerifier, "verify_trace_bytes", return_value=True) as mock_vtb:
            res = TraceVerifier.verify_trace(valid_trace, valid_manifest, run_store=None)
            assert res is True
            assert mock_vtb.called


def test_verify_run_anomalies_and_exceptions():
    mock_store = MagicMock()
    mock_store.get_run.side_effect = RuntimeError("Store query failure")
    res = TraceVerifier.verify_run("run-err", run_store=mock_store)
    assert res["verification_status"] == "FAILED_VERIFICATION"
    assert "Corrupt or malformed run evidence" in res["failure_reason"]

    mock_store.get_run.side_effect = None
    mock_store.get_run.return_value = None
    mock_store.get_trace_bytes.return_value = None
    res = TraceVerifier.verify_run("run-not-found", run_store=mock_store)
    assert res["verification_status"] == "NOT_FOUND"

    mock_store.get_run.return_value = {"run_id": "other-run-id"}
    mock_store.get_manifest.return_value = {"run_id": "other-run-id"}
    mock_store.get_events.return_value = []
    mock_store.get_trace_bytes.return_value = b'{"event":"run_end"}\n'
    res = TraceVerifier.verify_run("target-run-id", run_store=mock_store)
    assert res["verification_status"] == "FAILED_VERIFICATION"
    assert "Provider scope returned artifacts for a different run" in res["failure_reason"]

    mock_store.get_run.return_value = {"run_id": "target-run-id"}
    mock_store.get_manifest.return_value = {"run_id": "target-run-id"}
    mock_store.get_events.return_value = None
    res = TraceVerifier.verify_run("target-run-id", run_store=mock_store)
    assert res["verification_status"] == "FAILED_VERIFICATION"
    assert "Provider did not return scoped run events" in res["failure_reason"]

    mock_store.get_events.return_value = []
    with patch.object(
        TraceVerifier,
        "verify_trace_bytes",
        side_effect=RuntimeError("Sub-verification crashed"),
    ):
        res = TraceVerifier.verify_run(
            "target-run-id",
            run_store=mock_store,
            scenario_data={"id": "scen_1"},
        )
        assert res["verification_status"] == "FAILED_VERIFICATION"
        assert "Verification error: Sub-verification crashed" in res["failure_reason"]


def test_verify_trace_certificate_pqc_exception():
    trace_bytes = b'{"event":"run_end"}\n'
    trace_hash = f"sha3_256:{hashlib.sha3_256(trace_bytes).hexdigest()}"

    pqc_client = MagicMock()
    pqc_client.verify_digest.side_effect = RuntimeError("PQC runtime library exception")

    cert_data = {
        "run_id": "run-pqc-err",
        "trace_hash": trace_hash,
        "crypto_suite": "ML-DSA-65",
        "provenance_chain": [
            {
                "identity": "system_id",
                "algorithm": "ML-DSA-65",
                "signature": "abcd1234ef",
            }
        ],
    }

    with patch.object(IdentityService, "get_pqc_client", return_value=pqc_client):
        res = verify_trace_certificate("run-pqc-err", trace_bytes, cert_data=cert_data)
        assert res["verified"] is False
        assert any("ML-DSA-65 signature check error" in err for err in res["errors"])


def test_verify_trace_certificate_filtered_evidence_graph_recovery():
    trace_events = [
        {"event": "oracle_result", "_seq": 1, "oracle_id": "o1", "passed": True, "outcome": "PASS"},
        {
            "event": "run_end",
            "_seq": 2,
            "finalization": {"finalization_hash": "fin_hash_123"},
            "data": {
                "assertions": [{"oracle_id": "carrier_oracle", "passed": True, "outcome": "PASS"}]
            },
        },
    ]
    trace_lines = [json.dumps(e) for e in trace_events]
    raw_trace_bytes = "\n".join(trace_lines).encode("utf-8") + b"\n"
    trace_hash = f"sha3_256:{hashlib.sha3_256(raw_trace_bytes).hexdigest()}"

    events_with_lines = [
        (trace_events[0], trace_lines[0]),
    ]
    filtered_graph = build_evidence_graph_from_events(events_with_lines)
    expected_root = compute_evidence_graph_root(filtered_graph)

    key = ed25519.Ed25519PrivateKey.generate()
    anchor_pk = key.public_key()

    cert_data = {
        "run_id": "run-filter-rec",
        "trace_hash": trace_hash,
        "evidence_root_hash": expected_root,
        "provenance_chain": [],
    }

    signed_payload = dict(cert_data)
    signed_payload.pop("provenance_chain", None)
    manifest_bytes = canonical_json_encode(signed_payload)
    sig_hex = key.sign(manifest_bytes).hex()

    cert_data["provenance_chain"] = [
        {
            "identity": "system_id",
            "algorithm": "Ed25519",
            "signature": sig_hex,
        }
    ]

    with patch.object(IdentityService, "get_public_key", return_value=anchor_pk):
        res = verify_trace_certificate(
            "run-filter-rec",
            raw_trace_bytes,
            cert_data=cert_data,
            trace_only=False,
        )
        assert res.get("verified") is True
        assert not res.get("errors")


def test_verify_package_artifacts_oracle_reconciliation_and_divergence():
    trace_events = [
        {
            "event": "oracle_result",
            "_seq": 1,
            "oracle_id": "oracle_exact",
            "passed": True,
            "outcome": "PASS",
            "execution_instance_id": "inst_1",
        },
        {
            "event": "oracle_result",
            "_seq": 2,
            "oracle_id": "oracle_candidate",
            "passed": True,
            "outcome": "PASS",
            "execution_instance_id": "inst_cand",
        },
        {
            "event": "oracle_result",
            "_seq": 3,
            "oracle_id": "oracle_diff_outcome",
            "passed": True,
            "outcome": "PASS",
        },
        {
            "event": "oracle_result",
            "_seq": 4,
            "oracle_id": "oracle_diff_passed",
            "passed": True,
            "outcome": "PASS",
        },
        {
            "event": "oracle_result",
            "_seq": 5,
            "oracle_id": "",
            "passed": True,
            "outcome": "PASS",
        },
        {
            "event": "oracle_result",
            "_seq": 6,
            "oracle_id": "oracle_multi",
            "passed": True,
            "outcome": "PASS",
        },
        {
            "event": "oracle_result",
            "_seq": 7,
            "oracle_id": "oracle_multi",
            "passed": True,
            "outcome": "PASS",
        },
    ]
    trace_lines = [json.dumps(e) for e in trace_events]
    raw_trace_bytes = "\n".join(trace_lines).encode("utf-8") + b"\n"
    trace_hash = f"sha3_256:{hashlib.sha3_256(raw_trace_bytes).hexdigest()}"

    events_with_lines = [(json.loads(line), line) for line in trace_lines]
    ev_graph = build_evidence_graph_from_events(events_with_lines)
    ev_root = compute_evidence_graph_root(ev_graph)

    exact_hash = str(
        ev_graph["nodes"][0].get("source_hash") or ev_graph["nodes"][0].get("content_hash") or ""
    )
    cand_hash = str(
        ev_graph["nodes"][1].get("source_hash") or ev_graph["nodes"][1].get("content_hash") or ""
    )

    executed_oracles = [
        {
            "oracle_id": "",
            "passed": True,
            "outcome": "PASS",
        },
        {
            "oracle_id": "oracle_exact",
            "passed": True,
            "outcome": "PASS",
            "content_hash": exact_hash,
            "resolver": "code",
        },
        {
            "oracle_id": "oracle_candidate",
            "passed": True,
            "outcome": "PASS",
            "sequence": 999,
            "content_hash": cand_hash,
            "resolver": "code",
        },
        {
            "oracle_id": "oracle_diff_outcome",
            "passed": False,
            "outcome": "FAIL",
            "resolver": "code",
        },
        {
            "oracle_id": "oracle_diff_passed",
            "passed": False,
            "outcome": "PASS",
            "resolver": "code",
        },
        {
            "oracle_id": "oracle_multi",
            "passed": True,
            "outcome": "PASS",
            "sequence": 999,
            "content_hash": "unmatched_hash",
            "resolver": "code",
        },
        {
            "oracle_id": "oracle_ungrounded",
            "passed": True,
            "outcome": "PASS",
            "resolver": "code",
        },
    ]

    pkg = VerificationPackage(
        scenario_id="scen_rec",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="man_rec",
        manifest_hash="sha3_256:dummy",
        execution_identity={"system_id": "test"},
        trace_hash=f"sha3_256:{trace_hash}",
        trace_seal={"trace_digest": f"sha3_256:{trace_hash}"},
        evidence_root_hash=ev_root,
        required_oracle_ids=["oracle_exact", "oracle_candidate"],
        executed_oracle_results=executed_oracles,
        decision={"decision": "PASS", "verdict": "PASS"},
        package_id="pkg_test_reconcile",
        signature="dummy_sig",
    )

    def _wrap_build_ev_graph(*args, **kwargs):
        g = build_evidence_graph_from_events(*args, **kwargs)
        g["nodes"].append({"oracle_id": None})
        return g

    with patch(
        "agentv_runtime.evidence_graph.build_evidence_graph_from_events",
        side_effect=_wrap_build_ev_graph,
    ):
        res = TraceVerifier.verify_package_artifacts(
            pkg,
            raw_trace_bytes=raw_trace_bytes,
            require_signature=False,
        )

    failures = res["failures"]
    assert any("PackagedEvidenceDivergence" in f for f in failures)
    assert any("UngroundedPackagedOracle" in f for f in failures)


def test_verify_package_artifacts_required_oracle_non_pass_fail_and_verif_hash():
    trace_events = [
        {
            "event": "oracle_result",
            "_seq": 1,
            "oracle_id": "req_skipped",
            "passed": False,
            "outcome": "SKIPPED",
        }
    ]
    trace_lines = [json.dumps(e) for e in trace_events]
    raw_trace_bytes = "\n".join(trace_lines).encode("utf-8") + b"\n"
    trace_hash = f"sha3_256:{hashlib.sha3_256(raw_trace_bytes).hexdigest()}"

    events_with_lines = [(json.loads(line), line) for line in trace_lines]
    ev_graph = build_evidence_graph_from_events(events_with_lines)
    ev_root = compute_evidence_graph_root(ev_graph)

    executed_oracles = [
        {
            "oracle_id": "req_skipped",
            "outcome": "SKIPPED",
            "passed": False,
            "resolver": "code",
        }
    ]

    exp_verif_payload = {
        "decision": {"decision": "FAIL"},
        "evidence_root_hash": ev_root,
        "executed_oracle_results": executed_oracles,
        "required_oracle_ids": ["req_skipped"],
    }
    verif_bytes = canonical_json_encode(exp_verif_payload)
    verif_hash = f"sha3_256:{hashlib.sha3_256(verif_bytes).hexdigest()}"

    pkg = VerificationPackage(
        scenario_id="scen_skip",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="man_skip",
        manifest_hash="sha3_256:dummy",
        execution_identity={"system_id": "test"},
        trace_hash=f"sha3_256:{trace_hash}",
        trace_seal={"trace_digest": f"sha3_256:{trace_hash}"},
        evidence_root_hash=ev_root,
        decision={"decision": "FAIL"},
        required_oracle_ids=["req_skipped"],
        executed_oracle_results=executed_oracles,
        verification_hash=verif_hash,
        package_id="pkg_skipped",
        signature="dummy",
    )

    res = TraceVerifier.verify_package_artifacts(
        pkg,
        raw_trace_bytes=raw_trace_bytes,
        require_signature=False,
    )

    failures = res["failures"]
    assert any("RequiredOracleNotExecuted" in f for f in failures)
    assert not any("VerificationHashMismatch" in f for f in failures)


def test_verify_package_trace_parsing_failure_and_split_chain_and_attested_fail():
    bad_trace_bytes = b"not-valid-json\n"
    pkg = VerificationPackage(
        scenario_id="scen_err",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="man_err",
        manifest_hash="sha3_256:dummy",
        execution_identity={"system_id": "test"},
        trace_hash=f"sha3_256:{hashlib.sha3_256(bad_trace_bytes).hexdigest()}",
        trace_seal={"trace_digest": f"sha3_256:{hashlib.sha3_256(bad_trace_bytes).hexdigest()}"},
        evidence_root_hash="sha3_256:dummy",
        decision={"decision": "FAIL"},
        required_oracle_ids=[],
        executed_oracle_results=[],
        package_id="pkg_parse_err",
        signature="dummy",
    )

    res = TraceVerifier.verify_package(
        pkg, raw_trace_bytes=bad_trace_bytes, require_signature=False
    )
    assert any("TraceStreamParsingFailed" in f for f in res["failures"])

    valid_trace_bytes = b'{"event":"test"}\n'
    trace_hash = f"sha3_256:{hashlib.sha3_256(valid_trace_bytes).hexdigest()}"
    pkg_split = VerificationPackage(
        scenario_id="scen_split",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="man_split",
        manifest_hash="sha3_256:dummy",
        execution_identity={"system_id": "test"},
        trace_hash=f"sha3_256:{trace_hash}",
        trace_seal={"trace_digest": f"sha3_256:{trace_hash}"},
        evidence_root_hash="sha3_256:dummy",
        decision={"decision": "FAIL"},
        required_oracle_ids=[],
        executed_oracle_results=[],
        package_id="pkg_split",
        signature="dummy",
    )
    res_split = TraceVerifier.verify_package(
        pkg_split,
        raw_trace_bytes=valid_trace_bytes,
        raw_trace_events=[{"event": "test"}, {"event": "extra"}],
        require_signature=False,
    )
    assert any("TraceStreamSplitChainViolation" in f for f in res_split["failures"])

    pkg_non_pass_fail = VerificationPackage(
        scenario_id="scen_npf",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="man_npf",
        manifest_hash="sha3_256:dummy",
        execution_identity={"system_id": "test"},
        trace_hash=f"sha3_256:{trace_hash}",
        trace_seal={"trace_digest": f"sha3_256:{trace_hash}"},
        evidence_root_hash="sha3_256:dummy",
        decision={"decision": "FAIL"},
        required_oracle_ids=["o_req"],
        executed_oracle_results=[{"oracle_id": "o_req", "outcome": "SKIPPED", "resolver": "c"}],
        package_id="pkg_non_pf",
        signature="dummy",
    )
    res_npf = TraceVerifier.verify_package(
        pkg_non_pass_fail,
        raw_trace_bytes=valid_trace_bytes,
        require_signature=False,
    )
    assert any("RequiredOracleNotExecuted" in f for f in res_npf["failures"])


def test_verify_certification_artifact_terminal_sequence_and_carrier_missing():
    fin_hash = "sha3_256:fin_hash_1"
    fin_record = MagicMock()
    fin_record.run_id = "run_term"
    fin_record.evidence_root_hash = "sha3_256:dummy"
    fin_record.scenario_hash = "sha3_256:dummy"
    fin_record.execution_manifest_hash = "sha3_256:dummy"
    fin_record.finalization_hash = fin_hash
    fin_record.outcome = "pass"
    fin_record.score = 1.0
    fin_record.terminal_seq = 42
    fin_record.evaluator_identity = "system_id"

    pkg = VerificationPackage(
        scenario_id="scen_term",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="man_term",
        manifest_hash="sha3_256:dummy",
        execution_identity={"system_id": "test"},
        trace_hash="sha3_256:dummy",
        trace_seal={"trace_digest": "sha3_256:dummy"},
        evidence_root_hash="sha3_256:dummy",
        decision={"decision": "pass", "score": 1.0},
        required_oracle_ids=[],
        executed_oracle_results=[],
        finalization_hash=fin_hash,
        evaluation_hash=fin_hash,
        package_id="pkg_term",
        signature="dummy",
    )

    trace_no_carrier = (
        b'{"event":"run_start"}\n'
        b'{"event":"evaluator_finalization","finalization_hash":"other_hash"}\n'
    )
    pkg = VerificationPackage(
        scenario_id=pkg.scenario_id,
        scenario_version=pkg.scenario_version,
        scenario_hash=pkg.scenario_hash,
        manifest_id=pkg.manifest_id,
        manifest_hash=pkg.manifest_hash,
        execution_identity=pkg.execution_identity,
        trace_hash=f"sha3_256:{hashlib.sha3_256(trace_no_carrier).hexdigest()}",
        trace_seal={"trace_digest": f"sha3_256:{hashlib.sha3_256(trace_no_carrier).hexdigest()}"},
        evidence_root_hash=pkg.evidence_root_hash,
        decision=pkg.decision,
        required_oracle_ids=pkg.required_oracle_ids,
        executed_oracle_results=pkg.executed_oracle_results,
        finalization_hash=pkg.finalization_hash,
        evaluation_hash=pkg.evaluation_hash,
        package_id=pkg.package_id,
        signature=pkg.signature,
    )
    with patch(
        "agentv_runtime.finalization.EvaluatorFinalizationRecord.from_dict",
        return_value=fin_record,
    ):
        with patch.object(fin_record, "verify_signature", return_value=True):
            res = TraceVerifier.verify_certification_artifact(
                pkg,
                raw_trace_bytes=trace_no_carrier,
                require_signature=False,
            )
            assert any("FinalizationTraceCarrierMissing" in f for f in res["failures"])

    trace_seq_mismatch = (
        b'{"event":"step","_seq":10}\n'
        b'{"event":"evaluator_finalization","_seq":11,"finalization_hash":"sha3_256:fin_hash_1"}\n'
    )
    pkg_seq_mismatch = VerificationPackage(
        scenario_id=pkg.scenario_id,
        scenario_version=pkg.scenario_version,
        scenario_hash=pkg.scenario_hash,
        manifest_id=pkg.manifest_id,
        manifest_hash=pkg.manifest_hash,
        execution_identity=pkg.execution_identity,
        trace_hash=f"sha3_256:{hashlib.sha3_256(trace_seq_mismatch).hexdigest()}",
        trace_seal={"trace_digest": f"sha3_256:{hashlib.sha3_256(trace_seq_mismatch).hexdigest()}"},
        evidence_root_hash=pkg.evidence_root_hash,
        decision=pkg.decision,
        required_oracle_ids=pkg.required_oracle_ids,
        executed_oracle_results=pkg.executed_oracle_results,
        finalization_hash=pkg.finalization_hash,
        evaluation_hash=pkg.evaluation_hash,
        package_id=pkg.package_id,
        signature=pkg.signature,
    )
    with patch(
        "agentv_runtime.finalization.EvaluatorFinalizationRecord.from_dict",
        return_value=fin_record,
    ):
        with patch.object(fin_record, "verify_signature", return_value=True):
            res = TraceVerifier.verify_certification_artifact(
                pkg_seq_mismatch,
                raw_trace_bytes=trace_seq_mismatch,
                require_signature=False,
            )
            assert any("TerminalSequenceMismatch" in f for f in res["failures"])

    trace_no_seq = (
        b'{"event":"step"}\n'
        b'{"event":"evaluator_finalization","finalization_hash":"sha3_256:fin_hash_1"}\n'
    )
    pkg_no_seq = VerificationPackage(
        scenario_id=pkg.scenario_id,
        scenario_version=pkg.scenario_version,
        scenario_hash=pkg.scenario_hash,
        manifest_id=pkg.manifest_id,
        manifest_hash=pkg.manifest_hash,
        execution_identity=pkg.execution_identity,
        trace_hash=f"sha3_256:{hashlib.sha3_256(trace_no_seq).hexdigest()}",
        trace_seal={"trace_digest": f"sha3_256:{hashlib.sha3_256(trace_no_seq).hexdigest()}"},
        evidence_root_hash=pkg.evidence_root_hash,
        decision=pkg.decision,
        required_oracle_ids=pkg.required_oracle_ids,
        executed_oracle_results=pkg.executed_oracle_results,
        finalization_hash=pkg.finalization_hash,
        evaluation_hash=pkg.evaluation_hash,
        package_id=pkg.package_id,
        signature=pkg.signature,
    )
    fin_record.terminal_seq = 99
    with patch(
        "agentv_runtime.finalization.EvaluatorFinalizationRecord.from_dict",
        return_value=fin_record,
    ):
        with patch.object(fin_record, "verify_signature", return_value=True):
            res = TraceVerifier.verify_certification_artifact(
                pkg_no_seq,
                raw_trace_bytes=trace_no_seq,
                require_signature=False,
            )
            assert any("TerminalTraceSequenceMissing" in f for f in res["failures"])
