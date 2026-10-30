"""Mandatory release proof from real HTTP execution to independent verification.

The agent and state authority run in separate HTTP servers. The authority owns
state; agent response text is never used as the observation oracle. Corruptions
are applied only to copies of the resulting real execution artifacts.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import threading
from urllib.request import Request, urlopen

import pytest
from flask import Flask, jsonify
from werkzeug.serving import make_server

from agentv_runtime.package import VerificationPackage
from eval_runner import config
from eval_runner.console.routes.evidence import build_verification_package
from eval_runner.identity import IdentityService
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.runner import DefaultRunner
from eval_runner.services.certification import execute_industrial_certification
from eval_runner.state_authority import state_authority_registry
from eval_runner.verifier import TraceVerifier, VerificationAuthority, verify_trace_certificate

MATRIX = [
    ("complete_chain", "all", True),
    ("altered_scenario", "scenario", False),
    ("omitted_execution", "execution", False),
    ("omitted_observation", "independent_observation", False),
    ("altered_observation", "independent_observation", False),
    ("omitted_oracle", "oracle_outcomes", False),
    ("failed_oracle", "oracle_outcomes", False),
    ("omitted_finalization", "signed_finalization", False),
    ("unsigned_finalization", "signed_finalization", False),
    ("duplicate_finalizations", "signed_finalization", False),
    ("altered_graph", "evidence_graph", False),
    ("altered_root", "evidence_graph", False),
    ("altered_manifest", "certificate", False),
    ("provisional_certificate", "certificate", False),
    ("legacy_certificate_profile", "certificate", False),
    ("contradictory_execution_mode", "execution", False),
    ("unsigned_package", "certificate", False),
    ("invalid_certificate_signature", "certificate", False),
    ("omitted_trace", "independent_verification", False),
    ("unsealed_run", "independent_verification", False),
    ("false_agent_success", "execution_to_observation", False),
    ("unavailable_observation", "execution_to_observation", False),
]


def _json_bytes(value):
    """Independent encoding for this matrix's ASCII, finite numeric fixtures.

    No Runtime canonicalizer, signer, or verification helper is used here. Integral
    floats are normalized because the published envelope uses JCS numeric values.
    """

    def normalize(item):
        if isinstance(item, float) and item.is_integer():
            return int(item)
        if isinstance(item, dict):
            return {key: normalize(val) for key, val in item.items()}
        if isinstance(item, list):
            return [normalize(val) for val in item]
        return item

    return json.dumps(
        normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def _digest(raw):
    return "sha3_256:" + hashlib.sha3_256(raw).hexdigest()


def _finalizations(events):
    found = []
    for index, event in enumerate(events):
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if event.get("event") == "evaluator_finalization":
            found.append((index, data or event))
        elif event.get("event") in {"run_end", "end"}:
            finalization = event.get("finalization") or data.get("finalization")
            if isinstance(finalization, dict):
                found.append((index, finalization))
    return found


def _independent_signature_review(signature, payload, anchor, identity, purpose):
    """Independent protocol implementation: external key, exact fields, no Core signer APIs."""
    if isinstance(signature, str):
        anchor.verify(bytes.fromhex(signature), payload)
        return
    from cryptography.hazmat.primitives import serialization

    key_der = anchor.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    key_fingerprint = hashlib.sha256(key_der).hexdigest()
    expected = {
        "profile": "agentv.signature.digest-envelope.v1",
        "version": 1,
        "envelope_canonicalization": "RFC8785",
        "purpose": purpose,
        "payload_projection": purpose + ".unsigned.v1",
        "payload_canonicalization": "RFC8785",
        "payload_digest": hashlib.sha256(payload).hexdigest(),
        "payload_digest_algorithm": "sha256",
        "payload_digest_encoding": "hex-lowercase",
        "signing_algorithm": "Ed25519",
        "signing_semantics": "raw-ed25519-over-canonical-envelope-bytes",
        "signer_identity": identity,
        "key_id": "sha256:" + key_fingerprint,
        "public_key_fingerprint": key_fingerprint,
        "fingerprint_algorithm": "sha256",
        "public_key_encoding": "spki-der",
        "signature_encoding": "base64-rfc4648-padded",
        "signature_length": 64,
    }
    assert set(signature) == {"profile", "envelope", "signature"}
    assert signature["profile"] == expected["profile"]
    assert type(signature["envelope"]["version"]) is int
    assert type(signature["envelope"]["signature_length"]) is int
    assert _json_bytes(signature["envelope"]) == _json_bytes(expected)
    encoded = signature["signature"]
    raw_signature = base64.b64decode(encoded, validate=True)
    assert len(raw_signature) == 64
    assert base64.b64encode(raw_signature).decode() == encoded
    anchor.verify(raw_signature, _json_bytes(expected))


def _independent_review(
    cert, raw, graph, scenario, sealed, anchors, strict=False, require_pass=True
):
    """Check external trust anchors and commitments without product verifiers."""
    try:
        assert sealed and raw is not None
        events = [json.loads(line) for line in raw.splitlines() if line.strip()]
        finalizations = _finalizations(events)
        assert len(finalizations) == 1
        fin = finalizations[0][1]
        assert fin["outcome"] in {"pass", "fail"}
        if require_pass:
            assert fin["outcome"] == "pass"
        final_payload = {
            key: val
            for key, val in fin.items()
            if key
            not in {
                "evaluator_signature",
                "finalization_hash",
                "manifest_hash",
            }
        }
        final_payload["required_oracle_ids"] = sorted(final_payload["required_oracle_ids"])
        _independent_signature_review(
            fin["evaluator_signature"],
            _json_bytes(final_payload),
            anchors[fin["evaluator_identity"]],
            fin["evaluator_identity"],
            "agentv.evaluator-finalization",
        )
        assert _digest(_json_bytes(final_payload)) == fin["finalization_hash"]
        package = cert["verification_package"]
        assert cert["vc_version"] == "3.0.0"
        assert package["metadata"]["certificate_profile"] == "agentv.certification.v3.0.0"
        assert package["metadata"]["provisional"] is False and not cert.get("provisional")
        assert package["decision"]["decision"].lower() == fin["outcome"]
        assert package["trace_hash"].split(":")[-1] == hashlib.sha3_256(raw).hexdigest()
        assert cert["trace_hash"].split(":")[-1] == hashlib.sha3_256(raw).hexdigest()
        assert _digest(_json_bytes(scenario)) == package["scenario_hash"]
        execution = cert["execution_manifest"]
        mode = package["execution_identity"]["execution_mode"]
        assert mode in {"live", "hybrid"}
        assert cert["execution_mode"] == execution["runtime_config"]["execution_mode"] == mode
        recorded_modes = []
        for event in events:
            if event.get("event") not in {"run_start", "start"}:
                continue
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            for truth in (event, data, event.get("metadata"), data.get("metadata")):
                if isinstance(truth, dict):
                    assert not truth.get("provisional")
                    if truth.get("execution_mode") is not None:
                        recorded_modes.append(str(truth["execution_mode"]).lower().strip())
        assert recorded_modes and all(recorded == mode for recorded in recorded_modes)
        manifest_payload = {
            key: val
            for key, val in execution.items()
            if key
            not in {
                "content_hash",
                "commitment_graph",
            }
        }
        manifest_payload["parent_artifact_refs"] = sorted(manifest_payload["parent_artifact_refs"])
        assert _digest(_json_bytes(manifest_payload)) == package["manifest_hash"]
        assert package["manifest_hash"] == fin["execution_manifest_hash"]
        package_payload = {
            key: val
            for key, val in package.items()
            if key
            not in {
                "signature",
                "public_key_pem",
                "package_hash",
                "content_hash",
                "commitment_graph",
            }
        }
        for key in (
            "key_id",
            "signer_identity",
            "certificate_hash",
            "evaluation_hash",
            "verification_hash",
            "finalization_hash",
        ):
            package_payload[key] = package_payload.get(key) or ""
        for key in ("required_oracle_ids", "parent_artifact_refs"):
            package_payload[key] = sorted(package_payload[key])
        _independent_signature_review(
            package["signature"],
            _json_bytes(package_payload),
            anchors[package["signer_identity"]],
            package["signer_identity"],
            "agentv.verification-package",
        )
        envelope = {
            key: val
            for key, val in cert.items()
            if key
            not in {
                "provenance_chain",
                "verification_package",
                "package_hash",
                "evaluation_hash",
                "verification_hash",
                "certificate_hash",
                "signing_context",
                "certification_diagnostics",
            }
        }
        envelope["certification"] = {
            key: val for key, val in envelope["certification"].items() if key != "stages"
        }
        assert cert["provenance_chain"]
        for entry in cert["provenance_chain"]:
            _independent_signature_review(
                entry["signature"],
                _json_bytes(envelope),
                anchors[entry["identity"]],
                entry["identity"],
                "agentv.certificate",
            )
        graph_root = _digest(
            _json_bytes(
                {
                    "graph_version": graph["graph_version"],
                    "node_hashes": sorted(node["row_hash"] for node in graph["nodes"]),
                }
            )
        )
        assert graph_root == package["evidence_root_hash"] == fin["evidence_root_hash"]
        raw_digests = {
            json.loads(line)["_seq"]: _digest(line.rstrip(b"\r\n"))
            for line in raw.splitlines()
            if line.strip()
        }
        for node in graph["nodes"]:
            if node.get("source_type") == "trace_event":
                sequence = int(node["source_ref"].split("#seq=")[1])
                assert node["content_hash"] == raw_digests[sequence]
        required = set(fin["required_oracle_ids"])
        assert required and required == set(package["required_oracle_ids"])
        assert required == set(execution["metadata"]["required_oracle_ids"])
        outcomes = package["executed_oracle_results"]
        for oracle in required:
            matches = [row for row in outcomes if row.get("oracle_id") == oracle]
            assert matches
            assert all(row["outcome"] in {"PASS", "FAIL"} for row in matches)
            if require_pass:
                assert all(row["outcome"] == "PASS" for row in matches)
        return True
    except (AssertionError, KeyError, ValueError, TypeError):
        if strict:
            raise
        return False
    except Exception as exc:
        from cryptography.exceptions import InvalidSignature

        if isinstance(exc, InvalidSignature) and not strict:
            return False
        raise


@pytest.fixture
def real_chain(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(config, "TRUST_ROOT", tmp_path / "keys")
    for identity in ("system_id", "eval_kernel"):
        IdentityService._provision_local_identity(identity)
    state = {"balance": 100, "reads": [], "agent_calls": 0, "lie": False, "unavailable": False}
    authority = Flask("release-independent-authority")

    @authority.get("/state")
    def observe():
        state["reads"].append(state["balance"])
        if state["unavailable"]:
            return jsonify({"error": "observation unavailable"}), 503
        return jsonify({"balance": state["balance"]})

    @authority.post("/apply")
    def apply():
        state["balance"] = 75
        return jsonify({"committed": True})

    authority_server = make_server("127.0.0.1", 0, authority)
    authority_origin = f"http://127.0.0.1:{authority_server.server_port}"
    agent = Flask("release-agent")

    @agent.post("/agent")
    def execute():
        state["agent_calls"] += 1
        if not state["lie"]:
            with urlopen(  # nosec B310
                Request(authority_origin + "/apply", data=b"{}", method="POST"), timeout=3
            ):
                pass
        return jsonify(
            {
                "action": "final_answer",
                "summary": "SUCCESS: balance is 75",
                "message": "SUCCESS: balance is 75",
                "success": True,
            }
        )

    agent_server = make_server("127.0.0.1", 0, agent)
    servers = [authority_server, agent_server]
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    monkeypatch.setenv("AGENTV_EXTERNAL_STATE_AUTHORITY_ALLOWLIST", authority_origin)
    state_authority_registry.clear()
    scenario = {
        "aes_version": 1.4,
        "id": "release-evidence-chain",
        "version": "1.0.0",
        "metadata": {
            "name": "Release evidence chain",
            "execution_mode": "live",
            "compliance_level": "Standard",
            "agent": {
                "endpoint": f"http://127.0.0.1:{agent_server.server_port}/agent",
                "protocol": "http",
            },
        },
        "state_authorities": {"ledger": {"url": authority_origin + "/state"}},
        "workflow": {
            "nodes": [
                {
                    "id": "debit",
                    "task_description": "Commit a debit of 25.",
                    "expected_outcome": [
                        {
                            "id": "ledger_balance",
                            "target": "authority:ledger",
                            "property": "balance",
                            "expected": 75,
                            "mode": "exact",
                        }
                    ],
                }
            ],
            "edges": [],
        },
        "evaluation": {},
    }
    try:
        yield scenario, LocalFileRunStore(config.RUN_LOG_DIR), state
    finally:
        state_authority_registry.clear()
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=3)


@pytest.mark.acceptance
@pytest.mark.acceptance_release
@pytest.mark.asyncio
@pytest.mark.parametrize("case,boundary,expected", MATRIX, ids=[row[0] for row in MATRIX])
async def test_release_evidence_chain_matrix(real_chain, case, boundary, expected, record_property):
    scenario, store, state = real_chain
    run_id = "release-" + case
    state["lie"] = case == "false_agent_success"
    state["unavailable"] = case == "unavailable_observation"
    await DefaultRunner(run_store=store).run(
        scenario,
        run_id=run_id,
        metadata={"execution_mode": "live"},
        max_turns=1,
    )
    assert state["reads"] and state["reads"][0] == 100
    record_property("boundary", boundary)
    record_property("expected_certified", expected)
    if case == "unavailable_observation":
        with pytest.raises(ValueError):
            execute_industrial_certification(run_id, run_store=store, scenario_data=scenario)
        assert not (store.get_manifest(run_id) or {}).get("verification_package")
        record_property("issuance_rejected", True)
        record_property("certified", False)
        record_property("run_verdict", "UNVERIFIED")
        return
    assert state["agent_calls"] >= 1 and len(state["reads"]) >= 2

    def observation_rows(value):
        if isinstance(value, dict):
            if value.get("source") == "authority:ledger" and "post_snapshot_hash" in value:
                yield value
            for child in value.values():
                yield from observation_rows(child)
        elif isinstance(value, list):
            for child in value:
                yield from observation_rows(child)

    recorded_events = [
        json.loads(line) for line in store.get_trace_bytes(run_id).splitlines() if line.strip()
    ]
    observations = list(observation_rows(recorded_events))
    assert observations
    assert observations[0]["actual_before"] == 100
    assert observations[0]["actual_after"] == state["balance"]
    assert observations[0]["pre_snapshot_hash"] == _digest(_json_bytes({"balance": 100}))
    assert observations[0]["post_snapshot_hash"] == _digest(
        _json_bytes({"balance": state["balance"]})
    )
    result = execute_industrial_certification(run_id, run_store=store, scenario_data=scenario)
    if case == "false_agent_success":
        assert state["balance"] == 100
        assert result["certified"] is False
        negative = TraceVerifier.verify_run(run_id, run_store=store)
        assert negative["verified"] is False and negative["is_valid"] is True
        assert negative["verification_status"] == "ATTESTED_FAIL"
        anchors = {
            identity: IdentityService.get_public_key(identity, auto_provision=False)
            for identity in ("system_id", "eval_kernel")
        }
        exported_negative = build_verification_package(run_id, run_store=store)
        assert _independent_review(
            result["manifest"],
            store.get_trace_bytes(run_id),
            exported_negative["evidence_graph"],
            scenario,
            True,
            anchors,
            strict=True,
            require_pass=False,
        )
        record_property("independent_verified", True)
        record_property("certified", False)
        record_property("run_verdict", negative["verification_status"])
        return
    assert state["balance"] == 75 and result["certified"] is True
    cert = copy.deepcopy(result["manifest"])
    raw = store.get_trace_bytes(run_id)
    if case in {
        "provisional_certificate",
        "legacy_certificate_profile",
        "contradictory_execution_mode",
    }:
        cert = TraceVerifier.sign_trace_bytes(
            raw,
            run_id=run_id,
            run_store=store,
            scenario_data=scenario,
            execution_manifest=cert["execution_manifest"],
            metadata=cert["metadata"],
            execution_mode="hybrid" if case == "contradictory_execution_mode" else "live",
            provisional=case != "contradictory_execution_mode",
            evidence_root_hash=cert["evidence_root_hash"],
        )
    exported = build_verification_package(run_id, run_store=store)
    graph = copy.deepcopy(exported["evidence_graph"])
    package = cert["verification_package"]
    events = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if case == "altered_scenario":
        scenario["workflow"]["nodes"][0]["task_description"] = "Different operation"
    elif case == "legacy_certificate_profile":
        package["metadata"].pop("certificate_profile")
        package["metadata"]["provisional"] = False
        package["signature"] = (
            IdentityService.get_private_key("system_id", auto_provision=False)
            .sign(VerificationPackage.from_dict(package).canonical_payload_bytes())
            .hex()
        )
        cert["package_hash"] = VerificationPackage.from_dict(package).compute_package_hash()
    elif case == "altered_manifest":
        cert["execution_manifest"]["runtime_config"]["changed"] = True
    elif case == "unsigned_package":
        package["signature"] = None
    elif case == "invalid_certificate_signature":
        cert["provenance_chain"][0]["signature"] = "00" * 64
    elif case == "altered_root":
        package["evidence_root_hash"] = "sha3_256:" + "0" * 64
    elif case == "altered_graph":
        graph["nodes"][0]["row_hash"] = "sha3_256:" + "0" * 64
    elif case == "omitted_oracle":
        package["executed_oracle_results"] = []
    elif case == "failed_oracle":
        package["executed_oracle_results"][0]["outcome"] = "FAIL"
    elif case == "omitted_finalization":
        events.pop(_finalizations(events)[0][0])
    elif case == "unsigned_finalization":
        _finalizations(events)[0][1]["evaluator_signature"] = ""
    elif case == "duplicate_finalizations":
        events.append(copy.deepcopy(events[_finalizations(events)[0][0]]))
    elif case in {"omitted_execution", "omitted_observation", "altered_observation"}:
        needle = "agent" if case == "omitted_execution" else "post_snapshot_hash"
        index = next(i for i, ev in enumerate(events) if needle in json.dumps(ev).lower())
        if case == "altered_observation":

            def corrupt_snapshot(value):
                if isinstance(value, dict):
                    if "post_snapshot_hash" in value:
                        value["post_snapshot_hash"] = "sha3_256:" + "0" * 64
                        return True
                    return any(corrupt_snapshot(child) for child in value.values())
                if isinstance(value, list):
                    return any(corrupt_snapshot(child) for child in value)
                return False

            assert corrupt_snapshot(events[index])
        elif case == "omitted_observation":
            assert events[index].pop("transition_evidence")
        else:
            events.pop(index)
    if case in {
        "omitted_finalization",
        "unsigned_finalization",
        "duplicate_finalizations",
        "omitted_execution",
        "omitted_observation",
        "altered_observation",
    }:
        raw = b"".join(_json_bytes(event) + b"\n" for event in events)
    if case == "omitted_trace":
        raw = None
    # Test issuance independently against a new, unsealed provider containing
    # the duplicated real execution stream, before testing exported verification.
    if case == "duplicate_finalizations":
        duplicate_store = LocalFileRunStore(config.RUN_LOG_DIR.parent / "duplicate-issuance")
        duplicate_store.create_run(run_id, scenario["id"])
        duplicate_store.append_events(run_id, events)
        duplicate_store.save_run_manifest(
            run_id,
            {
                "run_id": run_id,
                "execution_manifest": cert["execution_manifest"],
                "scenario_data": scenario,
            },
        )
        with pytest.raises(ValueError, match="DuplicateEvaluatorFinalization"):
            execute_industrial_certification(
                run_id, run_store=duplicate_store, scenario_data=scenario
            )
        assert not (duplicate_store.get_manifest(run_id) or {}).get("verification_package")
        assert duplicate_store.get_run(run_id)["lifecycle"] != "SEALED"
        record_property("issuance_rejected", True)

    # Re-sign a duplicated stream so a hash/signature failure cannot conceal a
    # verifier which silently accepts multiple authoritative finalizations.
    if case == "duplicate_finalizations":
        package["trace_hash"] = _digest(raw)
        package["trace_seal"]["trace_digest"] = _digest(raw)
        parsed = VerificationPackage.from_dict(package)
        package["signature"] = (
            IdentityService.get_private_key("system_id")
            .sign(parsed.canonical_payload_bytes())
            .hex()
        )
    sealed = case != "unsealed_run"
    anchors = {
        identity: IdentityService.get_public_key(identity, auto_provision=False)
        for identity in ("system_id", "eval_kernel")
    }
    product = VerificationAuthority.verify_certification_artifact(
        package,
        raw_trace_bytes=raw,
        canonical_manifest=cert["execution_manifest"],
        scenario_data=scenario,
    )
    semantic_failures = {
        "provisional_certificate": "ProvisionalExecutionCertificationProhibited",
        "legacy_certificate_profile": "UnsupportedCertificateProfile",
        "contradictory_execution_mode": "ExecutionModeMismatch",
    }
    if case in semantic_failures:
        assert any(semantic_failures[case] in failure for failure in product["failures"])
        assert not any(
            "SignatureVerificationFailed" in failure or "TraceHashMismatch" in failure
            for failure in product["failures"]
        )
        integrity = verify_trace_certificate(
            run_id, raw, cert_data=cert, scenario_data=scenario, trace_only=False
        )
        assert integrity["verified"], integrity["errors"]
        record_property("cryptographic_integrity", True)
    if case == "duplicate_finalizations":
        assert any("DuplicateEvaluatorFinalization" in failure for failure in product["failures"])
        assert not any(
            "SignatureVerificationFailed" in failure or "TraceHashMismatch" in failure
            for failure in product["failures"]
        )

    class ArtifactView:
        # A corrupted reader view, never a mutation of the sealed provider.
        def get_run(self, requested_id, context=None):
            record = store.get_run(requested_id, context=context)
            return {**record, "lifecycle": "SEALED" if sealed else "OPEN"}

        def get_manifest(self, requested_id, context=None):
            return cert

        def get_trace_bytes(self, requested_id, context=None):
            return raw

    run_verdict = TraceVerifier.verify_run(run_id, run_store=ArtifactView(), scenario_data=scenario)
    independent = _independent_review(cert, raw, graph, scenario, sealed, anchors, strict=expected)
    record_property("product_failures", json.dumps(product.get("failures", [])))
    record_property("artifact_certified", bool(product.get("certified")))
    record_property("run_verified", bool(run_verdict.get("verified")))
    record_property("independent_verified", independent)
    record_property("run_verdict", run_verdict.get("verification_status"))
    record_property(
        "certified",
        bool(product.get("certified") and run_verdict.get("verified") and independent and sealed),
    )
    assert (
        bool(product.get("certified") and run_verdict.get("verified") and independent and sealed)
        is expected
    ), product
    # Check every consumer's own boundary, so a rejection by one consumer
    # cannot conceal another consumer accepting evidence it should reject.
    assert independent is expected
    assert bool(run_verdict.get("verified")) is (expected or case == "altered_graph")
    assert bool(product.get("certified")) is (
        expected or case in {"altered_graph", "invalid_certificate_signature", "unsealed_run"}
    ), product
    if expected:
        assert TraceVerifier.verify_run(run_id, run_store=store)["verified"] is True
