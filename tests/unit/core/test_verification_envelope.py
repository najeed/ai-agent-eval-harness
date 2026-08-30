"""
tests/unit/core/test_verification_envelope.py

Tests verifying:
1. VerificationPackage canonical payload serialization & SHA3-256 root hashing.
2. Detached signing & pure public-key signature verification (Ed25519).
3. Tamper detection: bitwise payload alteration invalidates signatures.
4. VerificationAuthority end-to-end envelope verification.
5. Strict instantiation and missing field validation.
"""

import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from agentv_runtime.evidence_graph import (
    build_evidence_graph_from_events,
    compute_evidence_graph_root,
)
from agentv_runtime.package import VerificationPackage
from eval_runner.verifier import VerificationAuthority


class MockEd25519Signer:
    def __init__(self, identity: str = "auditor-node-01"):
        self.private_key = ed25519.Ed25519PrivateKey.generate()
        self.public_key = self.private_key.public_key()
        self.identity = identity
        self.algorithm = "ed25519"
        self.public_key_pem = self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

    def sign(self, data: bytes) -> bytes:
        return self.private_key.sign(data)


def test_package_canonical_payload_and_hash():
    pkg = VerificationPackage(
        scenario_id="scen-01",
        scenario_version="1.2.0",
        scenario_hash="sha3_256:scenhash",
        manifest_id="man-01",
        manifest_hash="sha3_256:manhash",
        execution_identity={"worker_id": "w1", "node": "agent-runner"},
        trace_hash="sha3_256:tracehash",
        trace_seal={"event_count": 5, "digest": "sha3_256:tracehash"},
        evidence_root_hash="sha3_256:evroot",
        required_oracle_ids=["oracle_b", "oracle_a"],
        executed_oracle_results=[
            {"metric": "oracle_a", "passed": True},
            {"metric": "oracle_b", "passed": True},
        ],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )
    raw_bytes = pkg.canonical_payload_bytes()
    assert isinstance(raw_bytes, bytes)
    parsed = json.loads(raw_bytes.decode("utf-8"))
    assert parsed["required_oracle_ids"] == ["oracle_a", "oracle_b"]

    h1 = pkg.compute_package_hash()
    assert len(h1) == 64
    d = pkg.to_dict()
    assert d["package_hash"] == h1


def test_package_signing_and_detached_verification():
    signer = MockEd25519Signer()
    pkg = VerificationPackage(
        scenario_id="scen-01",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scenhash",
        manifest_id="man-01",
        manifest_hash="sha3_256:manhash",
        execution_identity={"worker_id": "w1"},
        trace_hash="sha3_256:tracehash",
        trace_seal={"event_count": 2},
        evidence_root_hash="sha3_256:evroot",
        required_oracle_ids=["oracle_1"],
        executed_oracle_results=[{"metric": "oracle_1", "passed": True}],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )

    signed_pkg = pkg.sign(signer)
    assert signed_pkg.signature is not None
    assert signed_pkg.signer_identity == "auditor-node-01"
    assert signed_pkg.public_key_pem == signer.public_key_pem

    # Verify signature with embedded public key
    assert signed_pkg.verify_signature() is True

    # Verify signature with explicitly supplied trust anchor public key
    assert signed_pkg.verify_signature(public_key_pem=signer.public_key_pem) is True

    # Verify signature fails against an unrelated public key
    other_signer = MockEd25519Signer(identity="other")
    assert signed_pkg.verify_signature(public_key_pem=other_signer.public_key_pem) is False


def test_verification_authority_full_verification_pass():
    signer = MockEd25519Signer()
    raw_trace = (
        b'{"_seq": 1, "event": "run_start"}\n'
        b'{"_seq": 2, "event": "metric_evaluated", "metric": "o1", "passed": true}\n'
    )
    actual_trace_hash = hashlib.sha3_256(raw_trace).hexdigest()

    events = [
        {"_seq": 1, "event": "run_start"},
        {"_seq": 2, "event": "metric_evaluated", "metric": "o1", "passed": True},
    ]
    ev_graph = build_evidence_graph_from_events(events)
    ev_root = compute_evidence_graph_root(ev_graph)

    pkg = VerificationPackage(
        scenario_id="scen-01",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        manifest_id="man-01",
        manifest_hash="sha3_256:man",
        execution_identity={"worker_id": "w1"},
        trace_hash=f"sha3_256:{actual_trace_hash}",
        trace_seal={"event_count": 2},
        evidence_root_hash=ev_root,
        required_oracle_ids=["o1"],
        executed_oracle_results=[{"metric": "o1", "passed": True}],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )
    signed_pkg = pkg.sign(signer)

    res = VerificationAuthority.verify_package(
        signed_pkg,
        raw_trace_bytes=raw_trace,
        raw_trace_events=events,
        public_key_pem=signer.public_key_pem,
        require_signature=True,
    )
    assert res["verified"] is True
    assert res["status"] == "CERTIFIED"
    assert len(res["failures"]) == 0


def test_verification_authority_fails_on_tampered_trace():
    signer = MockEd25519Signer()
    tampered_trace = b'{"_seq": 1, "event": "tampered_start"}\n'

    pkg = VerificationPackage(
        scenario_id="scen-01",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:scen",
        manifest_id="man-01",
        manifest_hash="sha3_256:man",
        execution_identity={"worker_id": "w1"},
        trace_hash="sha3_256:12345678",
        trace_seal={"event_count": 1},
        evidence_root_hash="sha3_256:ev",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )
    signed_pkg = pkg.sign(signer)

    res = VerificationAuthority.verify_package(
        signed_pkg,
        raw_trace_bytes=tampered_trace,
        require_signature=True,
    )
    assert res["verified"] is False
    assert res["status"] == "UNVERIFIED"
    assert any("TraceHashMismatch" in f for f in res["failures"])


def test_strict_instantiation_requires_critical_fields():
    with pytest.raises(
        ValueError, match="strict instantiation requires valid scenario_id and trace_hash"
    ):
        VerificationPackage.from_dict({"scenario_id": ""}, strict=True)
