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
from agentv_runtime.finalization import EvaluatorFinalizationRecord
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
    from agentv_runtime.signatures import (
        DigestEnvelopeSigningBackend,
        SignaturePolicy,
        fingerprint,
    )
    from eval_runner.reference.signing import LocalEd25519SigningBackend

    signer = CoreTraceSigner()
    real_key = IdentityService.get_private_key("system_id", auto_provision=False)
    pub_key = real_key.public_key()
    policy = SignaturePolicy("system_id", "sha256:" + fingerprint(pub_key), pub_key)
    envelope_backend = DigestEnvelopeSigningBackend(LocalEd25519SigningBackend(), policy)

    manifest = {
        "signing_context": {
            "signing_backend": envelope_backend,
            "identity_id": "system_id",
        }
    }

    with patch.object(IdentityService, "get_private_key", return_value=real_key):
        res = signer.sign(manifest, next_signer=lambda m: m)

    assert res["provenance_chain"][0]["signature_profile"] == "agentv.signature.digest-envelope.v1"
    assert isinstance(res["provenance_chain"][0]["signature"], dict)


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
    with pytest.raises(
        CertificationFailedError,
        match="Invalid or unauthorized structured signing response",
    ):
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


def test_verify_trace_bytes_ledger_requires_provider_contract():
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
            assert result is False


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


def test_verify_trace_requires_provider_owned_bytes(tmp_path):
    assert not TraceVerifier.verify_trace(b"trace", 12345)
    trace_bytes = b'{"event":"run_end"}\n'
    manifest_dict = {
        "run_id": "run-path-ok",
        "trace_hash": f"sha3_256:{hashlib.sha3_256(trace_bytes).hexdigest()}",
    }

    with patch.object(TraceVerifier, "verify_trace_bytes", return_value=True):
        mock_store = MagicMock()
        assert TraceVerifier.verify_trace(trace_bytes, manifest_dict, run_store=mock_store) is True
    assert not TraceVerifier.verify_trace(trace_bytes, manifest_dict, run_store=None)


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
    mock_store.get_trace_bytes.return_value = None
    res = TraceVerifier.verify_run("target-run-id", run_store=mock_store)
    assert res["verification_status"] == "FAILED_VERIFICATION"
    assert "Trace bytes not returned by storage provider" in res["failure_reason"]

    mock_store.get_manifest.return_value = {"run_id": "target-run-id", "vc_version": "3.0.0"}
    mock_store.get_trace_bytes.return_value = b'{"event":"run_end"}\n'
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
    from agentv_runtime.signatures import CERTIFICATE, sign_digest_envelope

    sig_hex = sign_digest_envelope(manifest_bytes, key, identity="system_id", purpose=CERTIFICATE)

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

        # evidence_root_hash mismatch must be detected
        bad_cert = dict(cert_data)
        bad_cert["evidence_root_hash"] = "sha3_256:corrupt_root_value_12345"
        res_bad = verify_trace_certificate(
            "run-filter-rec",
            raw_trace_bytes,
            cert_data=bad_cert,
            trace_only=False,
        )
        assert res_bad.get("verified") is False
        assert any("Evidence root hash mismatch" in err for err in res_bad.get("errors", []))


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


def test_verify_package_artifacts_multiple_candidates_without_hash_does_not_diverge():
    """Disambiguation without hash must require len(candidates) == 1."""
    events = [
        {
            "event": "oracle_result",
            "oracle_id": "oracle_disambig",
            "outcome": "FAIL",
            "passed": False,
            "_seq": 1,
        },
        {
            "event": "oracle_result",
            "oracle_id": "oracle_disambig",
            "outcome": "PASS",
            "passed": True,
            "_seq": 2,
        },
    ]
    lines = [json.dumps(e) for e in events]
    raw_bytes = "\n".join(lines).encode("utf-8") + b"\n"
    trace_hash = f"sha3_256:{hashlib.sha3_256(raw_bytes).hexdigest()}"

    pkg = VerificationPackage(
        package_id="pkg_disambig",
        scenario_id="scen",
        scenario_version="1.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="man",
        manifest_hash="sha3_256:dummy",
        execution_identity={"system_id": "test"},
        trace_hash=trace_hash,
        trace_seal={"trace_digest": trace_hash},
        evidence_root_hash="sha3_256:dummy",
        required_oracle_ids=[],
        executed_oracle_results=[
            {"oracle_id": "oracle_disambig", "outcome": "PASS", "passed": True}
        ],
        decision={"decision": "PASS"},
        signature="dummy",
    )
    res = TraceVerifier.verify_package_artifacts(
        pkg, raw_trace_bytes=raw_bytes, require_signature=False
    )
    assert any("UngroundedPackagedOracle" in f for f in res["failures"])
    assert not any("PackagedEvidenceDivergence" in f for f in res["failures"])


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
    assert not any("InvalidOracleResolver" in f for f in failures)
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


def test_verify_package_certificate_hash_binds_evidence_root_hash():
    """verify_package must verify certificate_hash binds evidence_root_hash."""
    manifest = {
        "vc_version": "3.0.0",
        "run_id": "run-cert-test",
        "timestamp": "2026-11-02T04:00:00Z",
        "execution_mode": "live",
        "trace_hash": "sha3_256:thash",
        "compliance": {"status": "PASS", "score": 1.0},
        "evidence_root_hash": "sha3_256:eroot",
    }
    cert_payload = {
        "compliance": manifest["compliance"],
        "evidence_root_hash": manifest["evidence_root_hash"],
        "execution_mode": manifest["execution_mode"],
        "run_id": manifest["run_id"],
        "timestamp": manifest["timestamp"],
        "trace_hash": manifest["trace_hash"],
        "vc_version": manifest["vc_version"],
    }
    cert_hash = f"sha3_256:{hashlib.sha3_256(canonical_json_encode(cert_payload)).hexdigest()}"

    pkg = VerificationPackage(
        package_id="pkg_cert",
        scenario_id="scen",
        scenario_version="1.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="man",
        manifest_hash="sha3_256:dummy",
        execution_identity={"system_id": "test"},
        trace_hash="sha3_256:thash",
        trace_seal={"trace_digest": "sha3_256:thash"},
        evidence_root_hash="sha3_256:eroot",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
        certificate_hash=cert_hash,
        signature="dummy",
    )
    res = TraceVerifier.verify_package(pkg, canonical_manifest=manifest, require_signature=False)
    assert not any("CertificateHashMismatch" in f for f in res["failures"])


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
        with patch.object(EvaluatorFinalizationRecord, "verify_signature", return_value=True):
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
        with patch.object(EvaluatorFinalizationRecord, "verify_signature", return_value=True):
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
        with patch.object(EvaluatorFinalizationRecord, "verify_signature", return_value=True):
            res = TraceVerifier.verify_certification_artifact(
                pkg_no_seq,
                raw_trace_bytes=trace_no_seq,
                require_signature=False,
            )
            assert any("TerminalTraceSequenceMissing" in f for f in res["failures"])


def test_verify_package_artifacts_candidate_manifest_without_compliance_ignored():
    """candidate_manifest whose to_dict() lacks 'compliance' must not be used."""
    from agentv_runtime.package import VerificationPackage
    from eval_runner.verifier import TraceVerifier

    class ManifestWithoutCompliance:
        def to_dict(self):
            return {"run_id": "test_run", "other_field": "val"}

    pkg = VerificationPackage(
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="test_run",
        manifest_hash="sha3_256:dummy",
        execution_identity={"system_id": "test"},
        trace_hash="sha3_256:dummy",
        trace_seal={"trace_digest": "sha3_256:dummy"},
        evidence_root_hash="sha3_256:dummy",
        decision={"decision": "PASS"},
        required_oracle_ids=[],
        executed_oracle_results=[],
        package_id="pkg_1",
        signature="dummy",
        certificate_hash="sha3_256:expected_hash",
    )

    res = TraceVerifier.verify_package_artifacts(
        pkg,
        raw_trace_bytes=b'{"event":"test"}\n',
        canonical_manifest=ManifestWithoutCompliance(),
    )
    # When unmutated, m_dict is None, so CertificateHashMismatch is NOT triggered
    assert not any("CertificateHashMismatch" in f for f in res.get("failures", []))


def test_verify_trace_certificate_unsupported_algorithm_without_profile_rejected():
    """Entry with unsupported algorithm must report error."""
    from eval_runner.verifier import verify_trace_certificate

    cert_data = {
        "run_id": "run_test_unsupported",
        "vc_version": "3.0.0",
        "trace_hash": "a" * 64,
        "provenance_chain": [
            {
                "identity": "unsupported_signer",
                "algorithm": "UNSUPPORTED_ALGO",
                "signature": "12345678",
                "signature_profile": None,
            }
        ],
    }
    res = verify_trace_certificate(
        "run_test_unsupported", b'{"event":"test"}\n', cert_data=cert_data, trace_only=False
    )
    assert any("UnsupportedSignatureProfile: 'unsupported_signer'" in e for e in res["errors"])


def test_verify_certification_artifact_missing_evaluator_finalization_reported():
    """Trace missing finalization must report error."""
    raw_trace = b'{"event": "step", "_seq": 1}\n'
    h = f"sha3_256:{hashlib.sha3_256(raw_trace).hexdigest()}"
    pkg = VerificationPackage(
        scenario_id="scen_test",
        scenario_version="1.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="man_test",
        manifest_hash="sha3_256:dummy",
        execution_identity={"system_id": "test"},
        trace_hash=h,
        trace_seal={"trace_digest": h},
        evidence_root_hash="sha3_256:dummy",
        decision={"decision": "PASS"},
        required_oracle_ids=[],
        executed_oracle_results=[],
        finalization_hash="sha3_256:dummy",
        evaluation_hash="sha3_256:dummy",
        package_id="pkg_test",
        signature={"sig": "dummy"},
    )
    res = TraceVerifier.verify_certification_artifact(
        pkg,
        raw_trace_bytes=raw_trace,
        require_signature=False,
    )
    assert any("MissingEvaluatorFinalization" in f for f in res["failures"])


def test_sign_trace_bytes_filtered_finalization_evidence_root_adopted(tmp_path):
    """
    Sign_trace_bytes must adopt evidence root from filtered events
    when finalization record present.
    """
    from agentv_runtime.evidence_graph import build_evidence_graph_from_events
    from eval_runner.reference.local_run_store import LocalFileRunStore

    run_id = "run-m116-test"
    store = LocalFileRunStore(str(tmp_path / "runs"))
    store.create_run(run_id, scenario_id="scenario")
    ev1 = {"event": "metric_evaluated", "metric": "safety", "passed": True, "_seq": 1}
    ev2 = {
        "event": "run_end",
        "finalization": {"evaluator": "test"},
        "assertions": [{"oracle_id": "extra_oracle", "passed": True}],
        "_seq": 2,
    }
    store.append_events(run_id, [ev1, ev2])
    trace_bytes = store.get_trace_bytes(run_id)

    # Compute expected filtered evidence root (ev1 only) from exact stored trace line
    ev1_line = trace_bytes.splitlines()[0].decode("utf-8")
    filtered_graph = build_evidence_graph_from_events([(ev1, ev1_line)])
    filtered_root = filtered_graph["evidence_root_hash"]

    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        run_id=run_id,
        run_store=store,
        identity_id="test_signer",
        evidence_root_hash=filtered_root,
    )
    assert manifest["evidence_root_hash"] == filtered_root


def test_sign_trace_bytes_filtered_run_end_finalization_evidence_root_adopted(tmp_path):
    """sign_trace_bytes must filter run_end with finalization."""
    from agentv_runtime.evidence_graph import build_evidence_graph_from_events
    from eval_runner.reference.local_run_store import LocalFileRunStore

    run_id = "run-m113-test"
    store = LocalFileRunStore(str(tmp_path / "runs"))
    store.create_run(run_id, scenario_id="scenario")
    ev1 = {"event": "metric_evaluated", "metric": "safety", "passed": True, "_seq": 1}
    ev2 = {"event": "run_end", "finalization": {"evaluator": "test"}, "_seq": 2}
    store.append_events(run_id, [ev1, ev2])
    trace_bytes = store.get_trace_bytes(run_id)

    ev1_line = trace_bytes.splitlines()[0].decode("utf-8")
    filtered_graph = build_evidence_graph_from_events([(ev1, ev1_line)])
    filtered_root = filtered_graph["evidence_root_hash"]

    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        run_id=run_id,
        run_store=store,
        identity_id="test_signer",
        evidence_root_hash=filtered_root,
    )
    assert manifest["evidence_root_hash"] == filtered_root


def test_verify_run_provisional_live_must_fail_authoritative(tmp_path):
    """verify_run must reject provisional runs even if mode is live."""
    from eval_runner.reference.local_run_store import LocalFileRunStore

    run_id = "run-m243-test"
    store = LocalFileRunStore(str(tmp_path / "runs"))
    store.create_run(run_id, scenario_id="scenario")
    store.append_events(run_id, [{"event": "step", "_seq": 1}])
    manifest = {
        "vc_version": "3.0.0",
        "harness_version": "2.0.0",
        "timestamp": "2026-11-02T03:00:00Z",
        "run_id": run_id,
        "execution_mode": "live",
        "provisional": True,
        "trace_hash": "dummy_hash",
        "algorithm": "ed25519",
        "evidence_root_hash": "sha3_256:dummy",
    }
    store.save_run_manifest(run_id, manifest)
    with patch(
        "eval_runner.verifier.verify_trace_certificate",
        return_value={"verified": True, "errors": []},
    ):
        with patch.object(TraceVerifier, "verify_trace_bytes", return_value=True):
            res = TraceVerifier.verify_run(run_id, manifest=manifest, run_store=store)
            assert res["is_valid"] is False
            assert (
                "Authoritative verification requires a non-provisional live run"
                in res["failure_reason"]
            )


def test_sign_trace_bytes_extracts_finalization_hash_from_run_end(tmp_path):
    """sign_trace_bytes must extract finalization_hash from run_end event."""
    from eval_runner.reference.local_run_store import LocalFileRunStore

    run_id = "run-m141-test"
    store = LocalFileRunStore(str(tmp_path / "runs"))
    store.create_run(run_id, scenario_id="scenario")
    ev1 = {"event": "step", "_seq": 1}
    ev2 = {
        "event": "run_end",
        "_seq": 2,
        "finalization": {"finalization_hash": "sha3_256:fin_m141_expected"},
    }
    store.append_events(run_id, [ev1, ev2])
    trace_bytes = store.get_trace_bytes(run_id)

    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        run_id=run_id,
        run_store=store,
        identity_id="test_signer",
    )
    pkg = manifest.get("verification_package") or {}
    assert pkg.get("finalization_hash") == "sha3_256:fin_m141_expected"


def test_sign_trace_bytes_certificate_hash_binds_evidence_root_hash(tmp_path):
    """certificate_hash must bind evidence_root_hash into its payload."""
    from agentv_runtime.canonical import canonical_json_encode
    from eval_runner.reference.local_run_store import LocalFileRunStore

    run_id = "run-m147-test"
    store = LocalFileRunStore(str(tmp_path / "runs"))
    store.create_run(run_id, scenario_id="scenario")
    ev = {"event": "step", "_seq": 1}
    store.append_events(run_id, [ev])
    trace_bytes = store.get_trace_bytes(run_id)

    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        run_id=run_id,
        run_store=store,
        identity_id="test_signer",
    )
    ev_root = manifest.get("evidence_root_hash")
    assert ev_root is not None

    expected_cert_payload = {
        "compliance": manifest["compliance"],
        "evidence_root_hash": ev_root,
        "execution_mode": manifest.get("execution_mode", "unknown"),
        "run_id": run_id,
        "timestamp": manifest["timestamp"],
        "trace_hash": manifest.get("trace_hash"),
        "vc_version": manifest["vc_version"],
    }
    expected_cert_hash = (
        f"sha3_256:{hashlib.sha3_256(canonical_json_encode(expected_cert_payload)).hexdigest()}"
    )
    pkg = manifest.get("verification_package") or {}
    assert pkg.get("certificate_hash") == expected_cert_hash


def test_verify_trace_bytes_package_and_manifest_present_returns_true():
    """verify_trace_bytes returns True when package and manifest valid."""
    from eval_runner.run_lifecycle import RunLifecycleState
    from eval_runner.verifier import VerificationAuthority

    trace = b'{"event":"step"}\n'
    thash = f"sha3_256:{hashlib.sha3_256(trace).hexdigest()}"
    manifest = {
        "run_id": "run-m202-ok",
        "trace_hash": thash,
        "verification_package": {"package_id": "pkg1"},
        "execution_manifest": {"manifest_id": "man1"},
    }
    mock_store = MagicMock()
    mock_store.get_trace_bytes.return_value = trace
    with patch(
        "eval_runner.run_lifecycle.get_run_lifecycle_state",
        return_value=RunLifecycleState.SEALED,
    ):
        with patch(
            "eval_runner.verifier.verify_trace_certificate",
            return_value={"verified": True, "errors": []},
        ):
            with patch.object(
                VerificationAuthority,
                "verify_certification_artifact",
                return_value={"verified": True, "failures": []},
            ):
                assert (
                    TraceVerifier.verify_trace_bytes(trace, manifest=manifest, run_store=mock_store)
                    is True
                )


def test_sign_trace_bytes_metadata_execution_manifest_hash_binds_to_package(tmp_path):
    """sign_trace_bytes must extract execution_manifest_hash from metadata."""
    from eval_runner.reference.local_run_store import LocalFileRunStore

    run_id = "run-m126-test"
    store = LocalFileRunStore(str(tmp_path / "runs"))
    store.create_run(run_id, scenario_id="scenario")
    store.append_events(run_id, [{"event": "step", "_seq": 1}])
    trace_bytes = store.get_trace_bytes(run_id)

    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        run_id=run_id,
        run_store=store,
        identity_id="test_signer",
        metadata={"execution_manifest_hash": "sha3_256:explicit_m_hash"},
    )
    pkg = manifest.get("verification_package") or {}
    assert pkg.get("manifest_hash") == "sha3_256:explicit_m_hash"


def test_verify_certification_artifact_invalid_evaluator_suppresses_missing_finalization():
    """Invalid evaluator record must suppress MissingEvaluatorFinalization."""
    tb = b'{"event": "evaluator_finalization", "finalization": "not_a_dict"}\n'
    th = f"sha3_256:{hashlib.sha3_256(tb).hexdigest()}"
    pkg = VerificationPackage(
        package_id="pkg724",
        scenario_id="scen",
        scenario_version="1.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="man",
        manifest_hash="sha3_256:dummy",
        execution_identity={"system_id": "test"},
        trace_hash=th,
        trace_seal={"trace_digest": th},
        evidence_root_hash="sha3_256:dummy",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
        signature="dummy",
    )
    res = TraceVerifier.verify_certification_artifact(
        pkg, raw_trace_bytes=tb, canonical_manifest=None, require_signature=False
    )
    failures = res["failures"]
    assert any("AuthoritativeEvaluatorRecordInvalid" in f for f in failures)
    assert not any("MissingEvaluatorFinalization" in f for f in failures)


def test_sign_trace_bytes_non_dict_event_raises_malformed(tmp_path):
    """sign_trace_bytes must fail when an event line parses as non-dict."""
    from eval_runner.reference.local_run_store import LocalFileRunStore

    run_id = "run-m61-test"
    store = LocalFileRunStore(str(tmp_path / "runs"))
    store.create_run(run_id, scenario_id="scenario")
    trace_bytes = b'{"event":"step"}\n12345\n'
    (tmp_path / "runs" / run_id / "run.jsonl").write_bytes(trace_bytes)
    with pytest.raises(CertificationFailedError, match="MalformedProviderTraceBytes"):
        TraceVerifier.sign_trace_bytes(
            trace_bytes, run_id=run_id, run_store=store, identity_id="signer"
        )


def test_verify_run_manifest_run_id_mismatch_fails():
    """verify_run must fail when manifest run_id differs from expected run_id."""
    mock_store = MagicMock()
    mock_store.get_run.return_value = {"run_id": "run-correct"}
    mock_store.get_manifest.return_value = {"run_id": "run-WRONG"}
    mock_store.get_trace_bytes.return_value = b'{"event":"step"}\n'
    res = TraceVerifier.verify_run("run-correct", run_store=mock_store)
    assert res["is_valid"] is False
    assert res["failure_reason"] == "Provider scope returned artifacts for a different run."


def test_sign_trace_bytes_binds_execution_mode_to_package_execution_identity(tmp_path):
    """sign_trace_bytes must bind execution_mode into verification_package."""
    from eval_runner.reference.local_run_store import LocalFileRunStore

    run_id = "run-m157-test"
    store = LocalFileRunStore(str(tmp_path / "runs"))
    store.create_run(run_id, scenario_id="scenario")
    store.append_events(run_id, [{"event": "step", "_seq": 1}])
    trace_bytes = store.get_trace_bytes(run_id)

    manifest = TraceVerifier.sign_trace_bytes(
        trace_bytes,
        run_id=run_id,
        run_store=store,
        identity_id="test_signer",
        execution_mode="live",
    )
    pkg = manifest.get("verification_package") or {}
    exec_id = pkg.get("execution_identity") or {}
    assert exec_id.get("execution_mode") == "live"


def test_verify_certification_artifact_run_end_carrier_alone_succeeds():
    """Must recognize run_end as a valid finalization carrier."""
    from agentv_runtime.finalization import EvaluatorFinalizationRecord

    fin_record = EvaluatorFinalizationRecord(
        finalization_id="fin_1",
        run_id="run_1",
        execution_manifest_hash="sha3_256:man_hash",
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen_hash",
        evaluator_identity="eval_kernel",
        evaluator_config_hash="sha3_256:cfg_hash",
        required_oracle_ids=[],
        evidence_root_hash="sha3_256:ev_root",
        outcome="pass",
        score=1.0,
        terminal_seq=1,
    )
    fin_record_dict = fin_record.to_dict()
    fin_hash = fin_record.compute_finalization_hash()
    fin_record_dict["finalization_hash"] = fin_hash

    tb = (
        json.dumps(
            {
                "_seq": 1,
                "event": "evaluator_finalization",
                "data": fin_record_dict,
            }
        )
        + "\n"
        + json.dumps(
            {
                "_seq": 2,
                "event": "run_end",
                "finalization": fin_record_dict,
            }
        )
        + "\n"
    ).encode("utf-8")
    th = f"sha3_256:{hashlib.sha3_256(tb).hexdigest()}"

    pkg = VerificationPackage(
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen_hash",
        manifest_id="man",
        manifest_hash="sha3_256:man_hash",
        execution_identity={"system_id": "test", "execution_mode": "live"},
        trace_hash=th,
        trace_seal={"trace_digest": th},
        evidence_root_hash="sha3_256:ev_root",
        required_oracle_ids=[],
        executed_oracle_results=[],
        finalization_hash=fin_hash,
        decision={"decision": "PASS"},
        signature="dummy",
    )

    with patch(
        "agentv_runtime.finalization.EvaluatorFinalizationRecord.from_dict",
        return_value=fin_record,
    ):
        with patch.object(EvaluatorFinalizationRecord, "verify_signature", return_value=True):
            res = TraceVerifier.verify_certification_artifact(
                pkg, raw_trace_bytes=tb, canonical_manifest=None, require_signature=False
            )
            assert any("DuplicateEvaluatorFinalization" in f for f in res["failures"])


def test_sign_trace_bytes_scenario_hash_and_manifest_hash_edge_cases():
    backend = MagicMock()
    backend.requires_private_key_material = False
    backend.sign_payload.return_value = {
        "format": "agentv.signature.digest-envelope.v1",
        "profile": "agentv.signature.digest-envelope.v1",
        "signature": "sig",
        "key_id": "key_1",
        "algorithm": "ed25519",
    }
    raw_tb = b'{"_seq": 1, "event": "start"}\n'
    store = MagicMock()
    store.get_trace_bytes.return_value = raw_tb
    store.get_events.return_value = [{"_seq": 1, "event": "start"}]

    with patch.object(IdentityService, "get_public_key", return_value=None):
        with patch(
            "agentv_runtime.signatures.validate_signing_response",
            side_effect=lambda payload, sig, **kw: sig,
        ):
            manifest = TraceVerifier.sign_trace_bytes(
                raw_tb,
                run_id="run_scen_meta",
                run_store=store,
                signing_backend=backend,
                identity_id="test_signer",
                metadata={"scenario_hash": "sha3_256:custom_scen_hash_from_meta"},
                scenario_data=None,
                execution_manifest=None,
            )

    pkg = manifest["verification_package"]
    # scenario_hash from metadata must not be omitted
    assert pkg["scenario_hash"] == "sha3_256:custom_scen_hash_from_meta"
    # manifest hash empty when execution_manifest is None
    # and metadata has no hash
    assert pkg["manifest_hash"] == ""


def test_sign_trace_bytes_finalization_hash_from_top_level_and_cert_payload_execution_mode():
    backend = MagicMock()
    backend.requires_private_key_material = False
    backend.sign_payload.return_value = {
        "format": "agentv.signature.digest-envelope.v1",
        "profile": "agentv.signature.digest-envelope.v1",
        "signature": "sig",
        "key_id": "key_1",
        "algorithm": "ed25519",
    }

    raw_tb = (
        b'{"_seq": 1, "event": "evaluator_finalization", '
        b'"finalization_hash": "sha3_256:top_level_fin_hash"}\n'
    )
    store = MagicMock()
    store.get_trace_bytes.return_value = raw_tb
    store.get_events.return_value = [
        {
            "_seq": 1,
            "event": "evaluator_finalization",
            "finalization_hash": "sha3_256:top_level_fin_hash",
        }
    ]

    with patch.object(IdentityService, "get_public_key", return_value=None):
        with patch(
            "agentv_runtime.signatures.validate_signing_response",
            side_effect=lambda payload, sig, **kw: sig,
        ):
            manifest_sim = TraceVerifier.sign_trace_bytes(
                raw_tb,
                run_id="run_fin_top",
                run_store=store,
                signing_backend=backend,
                identity_id="test_signer",
                execution_mode="simulated",
            )

    pkg_sim = manifest_sim["verification_package"]
    # top-level finalization_hash must be extracted
    assert pkg_sim["finalization_hash"] == "sha3_256:top_level_fin_hash"
    # execution_mode in execution_identity
    assert pkg_sim["execution_identity"]["execution_mode"] == "simulated"

    # certificate_hash binds execution_mode
    expected_cert_payload = {
        "compliance": manifest_sim["compliance"],
        "evidence_root_hash": manifest_sim["evidence_root_hash"],
        "execution_mode": "simulated",
        "run_id": "run_fin_top",
        "timestamp": manifest_sim["timestamp"],
        "trace_hash": manifest_sim["trace_hash"],
        "vc_version": manifest_sim["vc_version"],
    }
    expected_cert_hash = (
        f"sha3_256:{hashlib.sha3_256(canonical_json_encode(expected_cert_payload)).hexdigest()}"
    )
    assert manifest_sim["certificate_hash"] == expected_cert_hash


def test_sign_trace_bytes_private_key_without_private_bytes_raises():
    backend = MagicMock()
    backend.requires_private_key_material = True
    raw_tb = b'{"_seq": 1, "event": "start"}\n'
    store = MagicMock()
    store.get_trace_bytes.return_value = raw_tb
    store.get_events.return_value = [{"_seq": 1, "event": "start"}]

    # private_key lacking private_bytes must raise CertificationFailedError
    with patch.object(IdentityService, "get_private_key", return_value=object()):
        with pytest.raises(
            CertificationFailedError, match="Pre-existing trusted private key not found"
        ):
            TraceVerifier.sign_trace_bytes(
                raw_tb,
                run_id="run_bad_key",
                run_store=store,
                signing_backend=backend,
                identity_id="test_signer",
            )


def test_verify_trace_bytes_mutant_branches():
    run_store = MagicMock()
    tb = b'{"_seq": 1, "event": "start"}\n'
    th = f"sha3_256:{hashlib.sha3_256(tb).hexdigest()}"
    manifest = {
        "run_id": "run_vtb",
        "trace_hash": th,
        "verification_package": {"pkg": 1},
        "execution_manifest": {"man": 1},
    }

    # owned_trace is None returns False immediately without TypeError
    run_store.get_trace_bytes.return_value = None
    assert TraceVerifier.verify_trace_bytes(tb, manifest, run_store=run_store) is False

    # verify_ledger=True returns False immediately
    run_store.get_trace_bytes.return_value = tb
    with patch("eval_runner.verifier.verify_trace_certificate", return_value={"verified": True}):
        assert (
            TraceVerifier.verify_trace_bytes(
                tb, manifest, run_store=run_store, verify_ledger=True, trace_only=True
            )
            is False
        )
        assert (
            TraceVerifier.verify_trace_bytes(
                tb, manifest, run_store=run_store, trace_only=True, **{"verify_ledger": True}
            )
            is False
        )

    # missing package or missing execution_manifest when trace_only=False
    manifest_no_exec = dict(manifest, execution_manifest=None)
    with patch("eval_runner.verifier.verify_trace_certificate", return_value={"verified": True}):
        with patch("eval_runner.run_lifecycle.get_run_lifecycle_state") as mock_state:
            from eval_runner.run_lifecycle import RunLifecycleState

            mock_state.return_value = RunLifecycleState.SEALED
            assert (
                TraceVerifier.verify_trace_bytes(
                    tb, manifest_no_exec, run_store=run_store, trace_only=False
                )
                is False
            )

            manifest_no_pkg = dict(manifest, verification_package=None)
            assert (
                TraceVerifier.verify_trace_bytes(
                    tb, manifest_no_pkg, run_store=run_store, trace_only=False
                )
                is False
            )

    # trace_only=True skips sealed lifecycle check
    with patch("eval_runner.verifier.verify_trace_certificate", return_value={"verified": True}):
        with patch("eval_runner.run_lifecycle.get_run_lifecycle_state") as mock_state:
            mock_state.return_value = RunLifecycleState.OPEN  # Not sealed!
            assert (
                TraceVerifier.verify_trace_bytes(tb, manifest, run_store=run_store, trace_only=True)
                is True
            )


def test_verify_run_uncertified_and_verified_matrix_booster():
    run_store = MagicMock()
    tb = b'{"_seq": 1, "event": "start"}\n'

    # Uncertified run with execution_mode="simulated"
    manifest_uncert = {
        "run_id": "run_uncert_1",
        "execution_mode": "simulated",
        "compliance_status": "pass",
    }
    run_store.get_run.return_value = {"run_id": "run_uncert_1"}
    run_store.get_manifest.return_value = manifest_uncert
    run_store.get_trace_bytes.return_value = tb

    res = TraceVerifier.verify_run("run_uncert_1", run_store=run_store)
    assert res["verification_status"] == "UNVERIFIED"
    assert res["execution_mode"] == "simulated"
    assert res["provisional"] is True
    assert res["has_signature"] is False

    # uncertified run with execution_mode="live" and provisional=True
    manifest_uncert_live = {
        "run_id": "run_uncert_live_prov",
        "execution_mode": "live",
        "provisional": True,
        "compliance_status": "pass",
    }
    run_store.get_run.return_value = {"run_id": "run_uncert_live_prov"}
    run_store.get_manifest.return_value = manifest_uncert_live
    res_prov = TraceVerifier.verify_run("run_uncert_live_prov", run_store=run_store)
    assert res_prov["provisional"] is True

    # Uncertified run with trace_bytes=None and signature present
    run_store.get_run.return_value = {"run_id": "run_sig_no_tb"}
    run_store.get_trace_bytes.return_value = None
    manifest_sig_no_tb = {
        "run_id": "run_sig_no_tb",
        "signature": {"format": "envelope"},
    }
    run_store.get_manifest.return_value = manifest_sig_no_tb
    res_no_tb = TraceVerifier.verify_run("run_sig_no_tb", run_store=run_store)
    # has_signature must be True
    assert res_no_tb["has_signature"] is True
    assert res_no_tb["has_certificate"] is True

    # Manifest with only "signature" key makes has_certificate True
    manifest_sig_only = {
        "run_id": "run_sig_only",
        "signature": {"format": "envelope"},
        "execution_mode": "live",
    }
    run_store.get_run.return_value = {"run_id": "run_sig_only"}
    run_store.get_manifest.return_value = manifest_sig_only
    run_store.get_trace_bytes.return_value = tb
    with patch.object(TraceVerifier, "verify_trace_bytes", return_value=True):
        res_sig = TraceVerifier.verify_run("run_sig_only", run_store=run_store)
        assert res_sig["has_certificate"] is True
        assert res_sig["has_signature"] is True
        assert res_sig["execution_mode"] == "live"


def test_verify_trace_certificate_mutant_branches(tmp_path):
    # PQC verify_digest returns False
    with patch("eval_runner.identity.IdentityService.get_pqc_client") as mock_pqc:
        pqc_inst = MagicMock()
        pqc_inst.verify_digest.return_value = False
        mock_pqc.return_value = pqc_inst
        cert_pqc = {
            "signatures": [
                {
                    "algorithm": "ML-DSA-65",
                    "identity_id": "pqc_id",
                    "signature": "abcd",
                }
            ]
        }
        res_pqc = verify_trace_certificate("run_pqc", b"trace", cert_data=cert_pqc)
        assert res_pqc["verified"] is False
        assert any("ML-DSA-65 signature verification failed" in e for e in res_pqc["errors"])

    # trust_root flat directory with {identity_id}.pem
    key = ed25519.Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization

    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    tr_dir = tmp_path / "trust_root"
    tr_dir.mkdir()
    (tr_dir / "user_flat.pem").write_bytes(pub_pem)

    tb = b"trace"
    th = f"sha3_256:{hashlib.sha3_256(tb).hexdigest()}"
    cert_flat = {
        "trace_hash": th,
        "signatures": [
            {
                "algorithm": "ed25519",
                "signer_identity": "user_flat",
                "signature": {
                    "format": "agentv.signature.digest-envelope.v1",
                    "signature": "dummy",
                },
            }
        ],
    }
    with patch("agentv_runtime.signatures.verify_artifact_signature", return_value=True):
        res_flat = verify_trace_certificate(
            "run_flat", tb, cert_data=cert_flat, trust_root=str(tr_dir)
        )
        assert res_flat["verified"] is True

    # trust_root sub-directory cand is_file
    dir_key_dir = tr_dir / "user_dir"
    dir_key_dir.mkdir()
    (dir_key_dir / "public_key.pem").write_bytes(pub_pem)
    cert_dir = {
        "trace_hash": th,
        "signatures": [
            {
                "algorithm": "ed25519",
                "signer_identity": "user_dir",
                "signature": {
                    "format": "agentv.signature.digest-envelope.v1",
                    "signature": "dummy",
                },
            }
        ],
    }
    with patch("agentv_runtime.signatures.verify_artifact_signature", return_value=True):
        with patch("eval_runner.identity.IdentityService.get_public_key", return_value=None):
            res_dir = verify_trace_certificate(
                "run_dir", tb, cert_data=cert_dir, trust_root=str(tr_dir)
            )
            assert res_dir["verified"] is True

    # profile mismatch in envelope
    cert_prof = {
        "trace_hash": th,
        "signatures": [
            {
                "algorithm": "ed25519",
                "signer_identity": "user_flat",
                "signature_profile": "profile_A",
                "signature": {
                    "format": "agentv.signature.digest-envelope.v1",
                    "profile": "profile_B",
                },
            }
        ],
    }
    with patch("agentv_runtime.signatures.verify_artifact_signature", return_value=True):
        res_prof = verify_trace_certificate(
            "run_prof", tb, cert_data=cert_prof, trust_root=str(tr_dir)
        )
    assert res_prof["verified"] is False
    assert any("EnvelopeSignatureVerificationFailed" in e for e in res_prof["errors"])

    # legacy raw Ed25519 disabled by policy
    cert_raw = {
        "trace_hash": th,
        "signatures": [
            {
                "algorithm": "ed25519",
                "signer_identity": "user_flat",
                "signature": "abcd1234deadbeef",
            }
        ],
    }
    mock_pol = MagicMock()
    mock_pol.allow_legacy_raw = False
    with patch("agentv_runtime.signatures.resolve_policy", return_value=mock_pol):
        res_raw = verify_trace_certificate(
            "run_raw", tb, cert_data=cert_raw, trust_root=str(tr_dir)
        )
    assert res_raw["verified"] is False
    assert any("Legacy raw Ed25519 is disabled" in e for e in res_raw["errors"])

    # malformed line suppresses evidence graph computation
    tb_bad_line = b'{"_seq": 1, "event": "start"}\n{invalid_json}\n'
    cert_ev_root = {
        "evidence_root_hash": "sha3_256:some_root",
        "trace_only": False,
    }
    res_bad_line = verify_trace_certificate(
        "run_bad", tb_bad_line, cert_data=cert_ev_root, trace_only=False
    )
    assert any("Malformed trace record at line 2" in e for e in res_bad_line["errors"])
    # Graph calculation should have been skipped, not computed mismatch
    assert not any("Evidence root hash mismatch" in e for e in res_bad_line["errors"])

    # run_end without finalization is NOT filtered out during evidence recovery
    events_re = [
        {"_seq": 1, "event": "oracle_result", "oracle_id": "o1", "passed": True, "outcome": "PASS"},
        {
            "_seq": 2,
            "event": "run_end",
            "data": {
                "assertions": [{"oracle_id": "carrier_oracle", "passed": True, "outcome": "PASS"}]
            },
        },
        {
            "_seq": 3,
            "event": "session_decision",
            "finalization": {"finalization_hash": "abc"},
            "data": {
                "assertions": [{"oracle_id": "session_oracle", "passed": True, "outcome": "PASS"}]
            },
        },
    ]
    lines_re = [json.dumps(e) for e in events_re]
    tb_re = ("\n".join(lines_re) + "\n").encode("utf-8")
    th_re = f"sha3_256:{hashlib.sha3_256(tb_re).hexdigest()}"
    ev_graph_re = build_evidence_graph_from_events(
        list(zip(events_re[:2], lines_re[:2], strict=False))
    )
    cert_re = {
        "trace_hash": th_re,
        "evidence_root_hash": ev_graph_re["evidence_root_hash"],
        "signatures": [],
    }
    res_re = verify_trace_certificate("run_re", tb_re, cert_data=cert_re)
    assert not any("Evidence root hash mismatch" in e for e in res_re.get("errors", []))

    # top-level scenario_hash binding mismatch
    cert_scen = {
        "trace_hash": th,
        "scenario_hash": "sha3_256:declared_scen_hash",
        "signatures": [],
    }
    res_scen = verify_trace_certificate(
        "run_scen", tb, cert_data=cert_scen, scenario_data={"step": 1}
    )
    assert res_scen["verified"] is False
    assert "Scenario hash mismatch against certificate binding." in res_scen["errors"]

    # scenario_hash only in metadata binds scenario hash
    cert_meta_scen = {
        "metadata": {
            "scenario_hash": "sha3_256:expected_scen_hash",
        }
    }
    bad_scen = {"metadata": {"name": "diff"}}
    res_meta_scen = verify_trace_certificate(
        "run_scen", tb, cert_data=cert_meta_scen, scenario_data=bad_scen
    )
    assert any("Scenario hash mismatch" in e for e in res_meta_scen["errors"])


def test_verify_package_artifacts_coverage_booster():
    tb = b'{"_seq": 1, "event": "start"}\n'
    th = f"sha3_256:{hashlib.sha3_256(tb).hexdigest()}"

    # corrupt seal digest (int)
    pkg_bad_seal = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="m1",
        manifest_hash="sha3_256:dummy",
        execution_identity={},
        trace_hash=th,
        trace_seal={"trace_digest": 12345},  # not a string
        evidence_root_hash="sha3_256:dummy",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
    )
    res_seal = TraceVerifier.verify_package_artifacts(pkg_bad_seal, raw_trace_bytes=tb)
    assert any("TraceSealCorrupt" in f for f in res_seal["failures"])

    # scenario_hash mismatch and missing version
    pkg_bad_scen = VerificationPackage(
        scenario_id="s1",
        scenario_version="",  # missing version
        scenario_hash="sha3_256:wrong_scen_hash",
        manifest_id="m1",
        manifest_hash="sha3_256:dummy",
        execution_identity={},
        trace_hash=th,
        trace_seal={"trace_digest": th},
        evidence_root_hash="sha3_256:dummy",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
    )
    res_scen = TraceVerifier.verify_package_artifacts(
        pkg_bad_scen, raw_trace_bytes=tb, scenario_data={"id": "s1"}
    )
    assert any("ScenarioHashMismatch" in f for f in res_scen["failures"])
    assert any("ScenarioBindingIncomplete" in f for f in res_scen["failures"])

    # oracle passed vs outcome divergence
    pkg_div_a = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="m1",
        manifest_hash="sha3_256:dummy",
        execution_identity={},
        trace_hash=th,
        trace_seal={"trace_digest": th},
        evidence_root_hash="sha3_256:dummy",
        required_oracle_ids=["o1"],
        executed_oracle_results=[{"oracle_id": "o1", "outcome": "PASS", "resolver": "code"}],
        decision={"decision": "PASS"},
    )
    raw_div_a = [
        {"_seq": 1, "event": "start"},
        {"_seq": 2, "event": "assertion", "oracle_id": "o1", "outcome": "PASS", "passed": False},
    ]
    with patch("agentv_runtime.evidence_graph.build_evidence_graph_from_events") as mock_g:
        mock_g.return_value = {
            "evidence_root_hash": "sha3_256:dummy",
            "nodes": [
                {
                    "oracle_id": "o1",
                    "outcome": "PASS",
                    "passed": False,
                    "sequence": 2,
                    "content_hash": "h2",
                }
            ],
            "total_nodes": 1,
            "assertion_nodes": 1,
        }
        res_div_a = TraceVerifier.verify_package_artifacts(
            pkg_div_a, raw_trace_bytes=tb, raw_trace_events=raw_div_a
        )
        assert any("PackagedEvidenceDivergence" in f for f in res_div_a["failures"])

    # pkg_passed is False with outcome PASS vs raw_passed
    # derived from outcome PASS
    pkg_div_b = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="m1",
        manifest_hash="sha3_256:dummy",
        execution_identity={},
        trace_hash=th,
        trace_seal={"trace_digest": th},
        evidence_root_hash="sha3_256:dummy",
        required_oracle_ids=["o1"],
        executed_oracle_results=[
            {"oracle_id": "o1", "outcome": "PASS", "passed": False, "resolver": "code"}
        ],
        decision={"decision": "PASS"},
    )
    raw_div_b = [
        {"_seq": 1, "event": "start"},
        {"_seq": 2, "event": "assertion", "oracle_id": "o1", "outcome": "PASS"},
    ]
    with patch("agentv_runtime.evidence_graph.build_evidence_graph_from_events") as mock_g:
        mock_g.return_value = {
            "evidence_root_hash": "sha3_256:dummy",
            "nodes": [
                {
                    "oracle_id": "o1",
                    "outcome": "PASS",
                    "sequence": 2,
                    "content_hash": "h2",
                }
            ],
            "total_nodes": 1,
            "assertion_nodes": 1,
        }
        res_div_b = TraceVerifier.verify_package_artifacts(
            pkg_div_b, raw_trace_bytes=tb, raw_trace_events=raw_div_b
        )
        assert any("PackagedEvidenceDivergence" in f for f in res_div_b["failures"])

    # invalid resolver specification (int)
    pkg_bad_res = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="m1",
        manifest_hash="sha3_256:dummy",
        execution_identity={},
        trace_hash=th,
        trace_seal={"trace_digest": th},
        evidence_root_hash="sha3_256:dummy",
        required_oracle_ids=["o1"],
        executed_oracle_results=[{"oracle_id": "o1", "outcome": "PASS", "resolver": 9999}],
        decision={"decision": "PASS"},
    )
    res_bad_res = TraceVerifier.verify_package_artifacts(pkg_bad_res, raw_trace_bytes=tb)
    assert any("InvalidOracleResolver" in f for f in res_bad_res["failures"])

    # evaluation_hash is empty -> should not fail with EvaluationHashMismatch
    pkg_empty_eval_h = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="m1",
        manifest_hash="sha3_256:dummy",
        execution_identity={},
        trace_hash=th,
        trace_seal={"trace_digest": th},
        evidence_root_hash="sha3_256:dummy",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
        evaluation_hash="",
    )
    events_with_fin = [
        {"_seq": 1, "event": "start"},
        {"_seq": 2, "event": "evaluator_finalization", "finalization_hash": "sha3_256:fin1"},
    ]
    tb_fin = (json.dumps(events_with_fin[0]) + "\n" + json.dumps(events_with_fin[1]) + "\n").encode(
        "utf-8"
    )
    res_empty_eval = TraceVerifier.verify_package_artifacts(
        pkg_empty_eval_h, raw_trace_bytes=tb_fin, raw_trace_events=events_with_fin
    )
    assert not any("EvaluationHashMismatch" in f for f in res_empty_eval["failures"])

    # finalization_hash nested in data
    events_with_nested_fin = [
        {"_seq": 1, "event": "start"},
        {
            "_seq": 2,
            "event": "evaluator_finalization",
            "data": {"finalization_hash": "sha3_256:actual_eval_hash"},
        },
    ]
    tb_nested = (
        json.dumps(events_with_nested_fin[0]) + "\n" + json.dumps(events_with_nested_fin[1]) + "\n"
    ).encode("utf-8")
    th_nested = f"sha3_256:{hashlib.sha3_256(tb_nested).hexdigest()}"
    pkg_nested_eval = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="m1",
        manifest_hash="sha3_256:dummy",
        execution_identity={},
        trace_hash=th_nested,
        trace_seal={"trace_digest": th_nested},
        evidence_root_hash="sha3_256:dummy",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
        evaluation_hash="sha3_256:wrong_eval_hash",
    )
    res_nested_eval = TraceVerifier.verify_package_artifacts(
        pkg_nested_eval, raw_trace_bytes=tb_nested, raw_trace_events=events_with_nested_fin
    )
    assert any("EvaluationHashMismatch" in f for f in res_nested_eval["failures"])


def test_verify_package_coverage_booster():
    tb = b'{"_seq": 1, "event": "start"}\n'
    th = f"sha3_256:{hashlib.sha3_256(tb).hexdigest()}"

    # pkg.manifest_hash present but pkg.manifest_id empty
    # without canonical_manifest
    pkg_missing_man_id = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="",  # missing id
        manifest_hash="sha3_256:valid_hash",
        execution_identity={},
        trace_hash=th,
        trace_seal={"trace_digest": th},
        evidence_root_hash="sha3_256:dummy",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
    )
    res_man = TraceVerifier.verify_package(
        pkg_missing_man_id, raw_trace_bytes=tb, canonical_manifest=None, require_signature=False
    )
    assert any(
        "ManifestMissing: package does not bind a valid manifest hash" in f
        for f in res_man["failures"]
    )

    # direct provenance violation handling
    pkg_complete = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="m1",
        manifest_hash="sha3_256:dummy",
        execution_identity={},
        trace_hash=th,
        trace_seal={"trace_digest": th},
        evidence_root_hash="sha3_256:dummy",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
    )
    with patch("agentv_runtime.evidence_graph.build_evidence_graph_from_events") as mock_g:
        # is_complete_provenance: True
        mock_g.return_value = {
            "evidence_root_hash": "sha3_256:dummy",
            "nodes": [],
            "is_complete_provenance": True,
        }
        res_comp_true = TraceVerifier.verify_package(
            pkg_complete,
            raw_trace_events=[{"_seq": 1}],
            canonical_manifest={"manifest_id": "m1", "scenario_hash": "sha3_256:dummy"},
            require_signature=False,
        )
        assert not any("DirectProvenanceViolation" in f for f in res_comp_true["failures"])

        # is_complete_provenance omitted defaults to True
        mock_g.return_value = {
            "evidence_root_hash": "sha3_256:dummy",
            "nodes": [],
        }
        res_comp_def = TraceVerifier.verify_package(
            pkg_complete,
            raw_trace_events=[{"_seq": 1}],
            canonical_manifest={"manifest_id": "m1", "scenario_hash": "sha3_256:dummy"},
            require_signature=False,
        )
        assert not any("DirectProvenanceViolation" in f for f in res_comp_def["failures"])

        # Provenance False correctly appends DirectProvenanceViolation
        mock_g.return_value = {
            "evidence_root_hash": "sha3_256:dummy",
            "nodes": [],
            "is_complete_provenance": False,
        }
        res_comp_false = TraceVerifier.verify_package(
            pkg_complete,
            raw_trace_events=[{"_seq": 1}],
            canonical_manifest={"manifest_id": "m1", "scenario_hash": "sha3_256:dummy"},
            require_signature=False,
        )
        assert any("DirectProvenanceViolation" in f for f in res_comp_false["failures"])

    # valid string seal_digest does not corrupt, non-string does
    res_seal_valid = TraceVerifier.verify_package(
        pkg_complete,
        raw_trace_bytes=tb,
        canonical_manifest={"manifest_id": "m1", "scenario_hash": "sha3_256:dummy"},
        require_signature=False,
    )
    assert not any("TraceSealCorrupt" in f for f in res_seal_valid["failures"])

    # empty signature string does not enter seal signature verification
    pkg_empty_seal_sig = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="m1",
        manifest_hash="sha3_256:dummy",
        execution_identity={},
        trace_hash=th,
        trace_seal={"trace_digest": th, "signature": ""},
        evidence_root_hash="sha3_256:dummy",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
    )
    res_empty_sig = TraceVerifier.verify_package(
        pkg_empty_seal_sig,
        raw_trace_bytes=tb,
        canonical_manifest={"manifest_id": "m1", "scenario_hash": "sha3_256:dummy"},
        require_signature=False,
    )
    assert not any("TraceSealMissingIdentity" in f for f in res_empty_sig["failures"])

    pkg_bad_seal = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="m1",
        manifest_hash="sha3_256:dummy",
        execution_identity={},
        trace_hash=th,
        trace_seal={"trace_digest": 12345},  # non-string
        evidence_root_hash="sha3_256:dummy",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
    )
    res_bad_s = TraceVerifier.verify_package(
        pkg_bad_seal,
        raw_trace_bytes=tb,
        canonical_manifest={"manifest_id": "m1", "scenario_hash": "sha3_256:dummy"},
        require_signature=False,
    )
    assert any("TraceSealCorrupt" in f for f in res_bad_s["failures"])

    # trace seal signature present with key_id
    key = ed25519.Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization

    pub_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )

    pkg_seal_key_id = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="m1",
        manifest_hash="sha3_256:dummy",
        execution_identity={},
        trace_hash=th,
        trace_seal={
            "trace_digest": th,
            "signature": "dummy_seal_sig",
            "key_id": "seal_key_1",
        },
        evidence_root_hash="sha3_256:dummy",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
    )
    res_seal_k = TraceVerifier.verify_package(
        pkg_seal_key_id,
        raw_trace_bytes=tb,
        canonical_manifest={"manifest_id": "m1", "scenario_hash": "sha3_256:dummy"},
        key_registry={"seal_key_1": pub_pem},
        require_signature=False,
    )
    assert not any("TraceSealMissingIdentity" in f for f in res_seal_k["failures"])

    # signer_identity unmapped but key_id mapped in key_registry
    pkg_seal_fallback_key = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="m1",
        manifest_hash="sha3_256:dummy",
        execution_identity={},
        trace_hash=th,
        trace_seal={
            "trace_digest": th,
            "signature": "dummy_seal_sig",
            "signer_identity": "unknown_signer",
            "key_id": "seal_key_1",
        },
        evidence_root_hash="sha3_256:dummy",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
    )
    res_seal_fb = TraceVerifier.verify_package(
        pkg_seal_fallback_key,
        raw_trace_bytes=tb,
        canonical_manifest={"manifest_id": "m1", "scenario_hash": "sha3_256:dummy"},
        key_registry={"seal_key_1": pub_pem},
        require_signature=False,
    )
    assert not any("TraceSealUntrustedSigner" in f for f in res_seal_fb["failures"])

    # trust_root is not None provides public key lookup
    mock_tr = MagicMock()
    mock_tr.get_public_key.return_value = key.public_key()
    res_tr = TraceVerifier.verify_package(
        pkg_seal_key_id,
        raw_trace_bytes=tb,
        canonical_manifest={"manifest_id": "m1", "scenario_hash": "sha3_256:dummy"},
        trust_root=mock_tr,
        require_signature=False,
    )
    assert not any("TraceSealUntrustedSigner" in f for f in res_tr["failures"])

    # oracle resolver is valid string vs non-string
    pkg_valid_resolver = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="m1",
        manifest_hash="sha3_256:dummy",
        execution_identity={},
        trace_hash=th,
        trace_seal={"trace_digest": th},
        evidence_root_hash="sha3_256:dummy",
        required_oracle_ids=["req_o1"],
        executed_oracle_results=[
            {"oracle_id": "req_o1", "resolver": "code", "outcome": "PASS", "passed": True}
        ],
        decision={"decision": "PASS"},
    )
    res_val_res = TraceVerifier.verify_package(
        pkg_valid_resolver,
        raw_trace_bytes=tb,
        canonical_manifest={"manifest_id": "m1", "scenario_hash": "sha3_256:dummy"},
        require_signature=False,
    )
    assert not any("InvalidOracleResolver" in f for f in res_val_res["failures"])

    pkg_bad_resolver = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="m1",
        manifest_hash="sha3_256:dummy",
        execution_identity={},
        trace_hash=th,
        trace_seal={"trace_digest": th},
        evidence_root_hash="sha3_256:dummy",
        required_oracle_ids=["req_o1"],
        executed_oracle_results=[{"oracle_id": "req_o1", "resolver": 12345}],
        decision={"decision": "PASS"},
    )
    res_bad_res = TraceVerifier.verify_package(
        pkg_bad_resolver,
        raw_trace_bytes=tb,
        canonical_manifest={"manifest_id": "m1", "scenario_hash": "sha3_256:dummy"},
        require_signature=False,
    )
    assert any("InvalidOracleResolver" in f for f in res_bad_res["failures"])

    # matching evaluation_hash does not trigger mismatch
    fin_events_match = [
        {"_seq": 1, "event": "start"},
        {
            "_seq": 2,
            "event": "evaluator_finalization",
            "data": {"finalization_hash": "sha3_256:nested_fin"},
        },
    ]
    tb_match = ("\n".join(json.dumps(e) for e in fin_events_match) + "\n").encode("utf-8")
    th_match = f"sha3_256:{hashlib.sha3_256(tb_match).hexdigest()}"
    pkg_match_fin = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="m1",
        manifest_hash="sha3_256:dummy",
        execution_identity={},
        trace_hash=th_match,
        trace_seal={"trace_digest": th_match},
        evidence_root_hash="sha3_256:dummy",
        evaluation_hash="sha3_256:nested_fin",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
    )
    res_match = TraceVerifier.verify_package(
        pkg_match_fin,
        raw_trace_bytes=tb_match,
        canonical_manifest={"manifest_id": "m1", "scenario_hash": "sha3_256:dummy"},
        require_signature=False,
    )
    assert not any("EvaluationHashMismatch" in f for f in res_match["failures"])

    # nested data.finalization_hash detected upon mismatch
    pkg_mismatch_fin = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="m1",
        manifest_hash="sha3_256:dummy",
        execution_identity={},
        trace_hash=th_match,
        trace_seal={"trace_digest": th_match},
        evidence_root_hash="sha3_256:dummy",
        evaluation_hash="sha3_256:different_fin",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
    )
    res_mismatch = TraceVerifier.verify_package(
        pkg_mismatch_fin,
        raw_trace_bytes=tb_match,
        canonical_manifest={"manifest_id": "m1", "scenario_hash": "sha3_256:dummy"},
        require_signature=False,
    )
    assert any("EvaluationHashMismatch" in f for f in res_mismatch["failures"])

    # certificate_hash binds m_dict["evidence_root_hash"] and execution_mode
    cert_payload_man_root = {
        "compliance": {"status": "pass"},
        "evidence_root_hash": "sha3_256:man_ev_root",
        "execution_mode": "live",
        "run_id": "r1",
        "timestamp": "2026-11-03T00:00:00Z",
        "trace_hash": th,
        "vc_version": "3.0.0",
    }
    cert_hash_man = (
        f"sha3_256:{hashlib.sha3_256(canonical_json_encode(cert_payload_man_root)).hexdigest()}"
    )
    pkg_cert_man_root = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:dummy",
        manifest_id="m1",
        manifest_hash="sha3_256:dummy",
        execution_identity={},
        trace_hash=th,
        trace_seal={"trace_digest": th},
        evidence_root_hash="sha3_256:pkg_ev_root",
        certificate_hash=cert_hash_man,
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS"},
    )
    man_with_ev_root = {
        "manifest_id": "m1",
        "scenario_hash": "sha3_256:dummy",
        "compliance": {"status": "pass"},
        "evidence_root_hash": "sha3_256:man_ev_root",
        "execution_mode": "live",
        "run_id": "r1",
        "timestamp": "2026-11-03T00:00:00Z",
        "trace_hash": th,
        "vc_version": "3.0.0",
    }
    res_ch_man = TraceVerifier.verify_package(
        pkg_cert_man_root,
        raw_trace_bytes=tb,
        canonical_manifest=man_with_ev_root,
        require_signature=False,
    )
    assert not any("CertificateHashMismatch" in f for f in res_ch_man["failures"])


def test_verify_certification_artifact_coverage_booster():
    fin_record = EvaluatorFinalizationRecord(
        finalization_id="fin_1",
        run_id="run_1",
        execution_manifest_hash="sha3_256:man_hash",
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen_hash",
        evaluator_identity="eval_kernel",
        evaluator_config_hash="sha3_256:cfg_hash",
        required_oracle_ids=["o1"],
        evidence_root_hash="sha3_256:ev_root",
        outcome="pass",
        score=1.0,
        terminal_seq=1,
    )
    fin_dict = fin_record.to_dict()
    fin_hash = fin_record.compute_finalization_hash()
    fin_dict["finalization_hash"] = fin_hash

    events = [
        {"_seq": 1, "event": "run_start", "execution_mode": "live"},
        {"_seq": 2, "event": "evaluator_finalization", "data": fin_dict},
        {"_seq": 3, "event": "run_end"},
    ]
    tb = (
        json.dumps(events[0]) + "\n" + json.dumps(events[1]) + "\n" + json.dumps(events[2]) + "\n"
    ).encode("utf-8")
    th = f"sha3_256:{hashlib.sha3_256(tb).hexdigest()}"

    # pkg.manifest_id present but pkg.manifest_hash empty
    pkg_no_man_h = VerificationPackage(
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen_hash",
        manifest_id="man_1",
        manifest_hash="",  # missing hash
        execution_identity={"system_id": "test", "execution_mode": "live", "run_id": "run_1"},
        trace_hash=th,
        trace_seal={"trace_digest": th},
        evidence_root_hash="sha3_256:ev_root",
        required_oracle_ids=["o1"],
        executed_oracle_results=[],
        finalization_hash=fin_hash,
        evaluation_hash=fin_hash,
        decision={"decision": "PASS", "score": 1.0},
        signature="dummy",
    )
    res_m711 = TraceVerifier.verify_certification_artifact(
        pkg_no_man_h,
        raw_trace_bytes=tb,
        canonical_manifest={"manifest_id": "man_1"},
        scenario_data={"id": "scen_1"},
    )
    assert any("ExecutionManifestBindingMissing" in f for f in res_m711["failures"])

    # raw_trace_events provided alongside valid raw_trace_bytes
    pkg_valid = VerificationPackage(
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen_hash",
        manifest_id="man_1",
        manifest_hash="sha3_256:man_hash",
        execution_identity={
            "system_id": "test",
            "run_id": "run_1",
        },  # execution_mode omitted to test fallback!
        trace_hash=th,
        trace_seal={"trace_digest": th},
        evidence_root_hash="sha3_256:ev_root",
        required_oracle_ids=["o1"],
        executed_oracle_results=[],
        finalization_hash=fin_hash,
        evaluation_hash=fin_hash,
        decision={"decision": "PASS", "score": 1.0},
        signature="dummy",
    )
    man_canonical = {
        "manifest_id": "man_1",
        "run_id": "run_1",
        "execution_mode": "live",  # fallback execution_mode from canonical_manifest
        "provisional": False,
        "metadata": {"required_oracle_ids": ["o1"]},
        "scenario_hash": "sha3_256:scen_hash",
        "agent_config": {},
        "runtime_config": {},
        "environment": {},
    }
    with patch(
        "agentv_runtime.finalization.EvaluatorFinalizationRecord.from_dict",
        return_value=fin_record,
    ):
        with patch.object(EvaluatorFinalizationRecord, "verify_authoritative", return_value=True):
            # return_value=None ensures key_registry lookup is strictly required
            with patch.object(IdentityService, "get_public_key", return_value=None):
                # caller provides raw_trace_events
                # matching byte event count
                res_split = TraceVerifier.verify_certification_artifact(
                    pkg_valid,
                    raw_trace_bytes=tb,
                    raw_trace_events=events,
                    canonical_manifest=man_canonical,
                    scenario_data={"id": "scen_1", "required_oracle_ids": ["o1"]},
                    require_signature=False,
                    key_registry={"eval_kernel": "dummy_pem"},
                )
                assert not any("DuplicateEvaluatorFinalization" in f for f in res_split["failures"])
                assert not any("EvaluatorKeyMissing" in f for f in res_split["failures"])
                assert not any("TraceStreamSplitChainViolation" in f for f in res_split["failures"])
                # canonical_manifest execution_mode accepted
                assert not any("UncertifiedExecutionMode" in f for f in res_split["failures"])

    # pkg_reqs != fin_reqs when manifest_reqs == fin_reqs
    pkg_diff_reqs = VerificationPackage(
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen_hash",
        manifest_id="man_1",
        manifest_hash="sha3_256:man_hash",
        execution_identity={"system_id": "test", "execution_mode": "live", "run_id": "run_1"},
        trace_hash=th,
        trace_seal={"trace_digest": th},
        evidence_root_hash="sha3_256:ev_root",
        required_oracle_ids=["o2"],  # differs from fin_record ["o1"]!
        executed_oracle_results=[],
        finalization_hash=fin_hash,
        evaluation_hash=fin_hash,
        decision={"decision": "PASS", "score": 1.0},
        signature="dummy",
    )
    with patch(
        "agentv_runtime.finalization.EvaluatorFinalizationRecord.from_dict",
        return_value=fin_record,
    ):
        with patch.object(EvaluatorFinalizationRecord, "verify_authoritative", return_value=True):
            with patch.object(IdentityService, "get_public_key", return_value=object()):
                res_reqs = TraceVerifier.verify_certification_artifact(
                    pkg_diff_reqs,
                    raw_trace_bytes=tb,
                    canonical_manifest=man_canonical,
                    scenario_data={"id": "scen_1", "required_oracle_ids": ["o1"]},
                    require_signature=False,
                )
                assert any("RequiredOracleInventoryMismatch" in f for f in res_reqs["failures"])

    # score mismatch (pkg=0.5, fin_record=1.0)
    pkg_diff_score = VerificationPackage(
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen_hash",
        manifest_id="man_1",
        manifest_hash="sha3_256:man_hash",
        execution_identity={"system_id": "test", "execution_mode": "live", "run_id": "run_1"},
        trace_hash=th,
        trace_seal={"trace_digest": th},
        evidence_root_hash="sha3_256:ev_root",
        required_oracle_ids=["o1"],
        executed_oracle_results=[],
        finalization_hash=fin_hash,
        evaluation_hash=fin_hash,
        decision={"decision": "PASS", "score": 0.5},  # differs from 1.0!
        signature="dummy",
    )
    with patch(
        "agentv_runtime.finalization.EvaluatorFinalizationRecord.from_dict",
        return_value=fin_record,
    ):
        with patch.object(EvaluatorFinalizationRecord, "verify_authoritative", return_value=True):
            with patch.object(IdentityService, "get_public_key", return_value=object()):
                res_score = TraceVerifier.verify_certification_artifact(
                    pkg_diff_score,
                    raw_trace_bytes=tb,
                    canonical_manifest=man_canonical,
                    scenario_data={"id": "scen_1", "required_oracle_ids": ["o1"]},
                    require_signature=False,
                )
                assert any("ScoreMismatch" in f for f in res_score["failures"])

    # canonical_manifest provisional=True is prohibited
    man_provisional = dict(man_canonical, provisional=True)
    with patch(
        "agentv_runtime.finalization.EvaluatorFinalizationRecord.from_dict",
        return_value=fin_record,
    ):
        with patch.object(EvaluatorFinalizationRecord, "verify_authoritative", return_value=True):
            with patch.object(IdentityService, "get_public_key", return_value=object()):
                res_prov = TraceVerifier.verify_certification_artifact(
                    pkg_valid,
                    raw_trace_bytes=tb,
                    canonical_manifest=man_provisional,
                    scenario_data={"id": "scen_1", "required_oracle_ids": ["o1"]},
                    require_signature=False,
                )
                assert any(
                    "ProvisionalExecutionCertificationProhibited" in f for f in res_prov["failures"]
                )

    # auto_provision=False must be enforced when resolving evaluator key
    with patch(
        "agentv_runtime.finalization.EvaluatorFinalizationRecord.from_dict",
        return_value=fin_record,
    ):
        with patch.object(EvaluatorFinalizationRecord, "verify_authoritative", return_value=True):
            with patch.object(
                IdentityService,
                "get_public_key",
                side_effect=lambda id, auto_provision=False: (
                    object() if auto_provision is False else None
                ),
            ):
                res_m729 = TraceVerifier.verify_certification_artifact(
                    pkg_valid,
                    raw_trace_bytes=tb,
                    canonical_manifest=man_canonical,
                    scenario_data={"id": "scen_1", "required_oracle_ids": ["o1"]},
                    require_signature=False,
                )
                assert not any("EvaluatorKeyMissing" in f for f in res_m729["failures"])
