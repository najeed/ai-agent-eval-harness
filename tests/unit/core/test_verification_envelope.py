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

    # Zero-Trust Rule: Verify signature without external trust anchor or registry fails closed
    assert signed_pkg.verify_signature() is False

    # Verify signature with explicitly supplied trust anchor public key
    assert signed_pkg.verify_signature(public_key_pem=signer.public_key_pem) is True

    # Verify signature with external key registry
    registry = {signed_pkg.signer_identity: signer.public_key_pem}
    assert signed_pkg.verify_signature(key_registry=registry) is True

    # Verify signature fails against an unrelated public key
    other_signer = MockEd25519Signer(identity="other")
    assert signed_pkg.verify_signature(public_key_pem=other_signer.public_key_pem) is False


def test_verification_authority_full_verification_pass():
    from agentv_runtime.manifest import compute_scenario_hash

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

    scen_data = {
        "scenario_id": "scen-01",
        "version": "1.0.0",
        "description": "test scenario",
    }
    scen_hash = compute_scenario_hash(scen_data)

    trace_hash_str = f"sha3_256:{actual_trace_hash}"
    pkg = VerificationPackage(
        scenario_id="scen-01",
        scenario_version="1.0.0",
        scenario_hash=scen_hash,
        manifest_id="man-01",
        manifest_hash="sha3_256:man",
        execution_identity={"worker_id": "w1"},
        trace_hash=trace_hash_str,
        trace_seal={"event_count": 2, "digest": trace_hash_str},
        evidence_root_hash=ev_root,
        required_oracle_ids=["o1"],
        executed_oracle_results=[
            {
                "oracle_id": "o1",
                "outcome": "PASS",
                "resolver": "deterministic_resolver",
                "version": "1.0.0",
                "evidence_refs": ["ev_1"],
            }
        ],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )
    signed_pkg = pkg.sign(signer)

    res = VerificationAuthority.verify_package(
        signed_pkg,
        raw_trace_bytes=raw_trace,
        raw_trace_events=events,
        scenario_data=scen_data,
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
    with pytest.raises(
        ValueError, match="strict instantiation requires valid scenario_id and trace_hash"
    ):
        VerificationPackage.from_dict({"scenario_id": "scen-1", "trace_hash": ""}, strict=True)


def test_package_verify_signature_without_signature_returns_false():
    pkg = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:s",
        manifest_id="m1",
        manifest_hash="sha3_256:m",
        execution_identity={},
        trace_hash="sha3_256:t",
        trace_seal={},
        evidence_root_hash="sha3_256:e",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={},
        signature=None,
    )
    assert pkg.verify_signature(public_key_pem="fake-pem") is False


def test_package_verify_signature_key_registry_branches():
    signer = MockEd25519Signer(identity="node-x")
    pkg = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:s",
        manifest_id="m1",
        manifest_hash="sha3_256:m",
        execution_identity={},
        trace_hash="sha3_256:t",
        trace_seal={},
        evidence_root_hash="sha3_256:e",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={},
        key_id="custom-key-id",
        signer_identity="node-x",
    )
    signed = pkg.sign(signer)

    # Matched via key_id
    assert signed.verify_signature(key_registry={"custom-key-id": signer.public_key_pem}) is True

    # Matched via signer_identity when key_id is empty
    pkg_no_key_id = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:s",
        manifest_id="m1",
        manifest_hash="sha3_256:m",
        execution_identity={},
        trace_hash="sha3_256:t",
        trace_seal={},
        evidence_root_hash="sha3_256:e",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={},
        key_id=None,
        signer_identity="node-x",
    )
    signed_no_key_id = pkg_no_key_id.sign(signer)
    assert signed_no_key_id.verify_signature(key_registry={"node-x": signer.public_key_pem}) is True
    # Missing from registry fails closed
    assert signed.verify_signature(key_registry={"other-key": signer.public_key_pem}) is False


def test_package_verify_signature_trust_root_branches(tmp_path):
    signer = MockEd25519Signer(identity="node-y")
    pkg = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:s",
        manifest_id="m1",
        manifest_hash="sha3_256:m",
        execution_identity={},
        trace_hash="sha3_256:t",
        trace_seal={},
        evidence_root_hash="sha3_256:e",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={},
        key_id="k-1",
        signer_identity="node-y",
    )
    signed = pkg.sign(signer)

    # 1. Trust root with get_public_key returning an Ed25519 key
    class MockTrustRootObj:
        def get_public_key(self, target_id):
            assert target_id == "k-1"
            return signer.public_key

    assert signed.verify_signature(trust_root=MockTrustRootObj()) is True

    # 2. Trust root raising an exception
    class BrokenTrustRootObj:
        def get_public_key(self, target_id):
            raise RuntimeError("PKI lookup timeout")

    assert signed.verify_signature(trust_root=BrokenTrustRootObj()) is False

    # 3. Trust root as directory path
    trust_dir = tmp_path / "trust_anchors"
    key_dir = trust_dir / "k-1"
    key_dir.mkdir(parents=True)
    (key_dir / "public_key.pem").write_text(signer.public_key_pem, encoding="utf-8")

    assert signed.verify_signature(trust_root=trust_dir) is True
    assert signed.verify_signature(trust_root=str(trust_dir)) is True

    # 4. Trust root directory missing key file
    empty_dir = tmp_path / "empty_trust"
    empty_dir.mkdir()
    assert signed.verify_signature(trust_root=empty_dir) is False


def test_package_verify_signature_identity_service_fallback(monkeypatch):
    signer = MockEd25519Signer(identity="service-node")
    pkg = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:s",
        manifest_id="m1",
        manifest_hash="sha3_256:m",
        execution_identity={},
        trace_hash="sha3_256:t",
        trace_seal={},
        evidence_root_hash="sha3_256:e",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={},
        key_id="node-sys",
        signer_identity="service-node",
    )
    signed = pkg.sign(signer)

    # Mock IdentityService returning public key
    from unittest.mock import MagicMock

    mock_id_svc = MagicMock()
    mock_id_svc.get_public_key.return_value = signer.public_key
    monkeypatch.setattr("eval_runner.identity.IdentityService", mock_id_svc)

    assert signed.verify_signature() is True

    # Mock IdentityService throwing exception
    mock_id_svc.get_public_key.side_effect = RuntimeError("DB down")
    assert signed.verify_signature() is False


def test_package_verify_signature_embedded_key_mismatch_and_invalid():
    import dataclasses

    signer = MockEd25519Signer()
    other_signer = MockEd25519Signer()
    pkg = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:s",
        manifest_id="m1",
        manifest_hash="sha3_256:m",
        execution_identity={},
        trace_hash="sha3_256:t",
        trace_seal={},
        evidence_root_hash="sha3_256:e",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={},
    )
    signed = pkg.sign(signer)
    # Tamper with embedded public_key_pem to mismatch external trust anchor
    tampered_key = dataclasses.replace(signed, public_key_pem=other_signer.public_key_pem)
    assert tampered_key.verify_signature(public_key_pem=signer.public_key_pem) is False

    # Corrupt embedded public_key_pem (triggers exception)
    corrupt_key = dataclasses.replace(signed, public_key_pem="NOT-A-VALID-PEM")
    assert corrupt_key.verify_signature(public_key_pem=signer.public_key_pem) is False


def test_package_verify_signature_corrupt_signature_and_rsa_key():
    import dataclasses

    signer = MockEd25519Signer()
    pkg = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:s",
        manifest_id="m1",
        manifest_hash="sha3_256:m",
        execution_identity={},
        trace_hash="sha3_256:t",
        trace_seal={},
        evidence_root_hash="sha3_256:e",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={},
    )
    signed = pkg.sign(signer)
    # Bad signature hex (triggers verify exception)
    bad_sig = dataclasses.replace(signed, signature="deadbeef")
    assert bad_sig.verify_signature(public_key_pem=signer.public_key_pem) is False

    # RSA key instead of Ed25519
    from cryptography.hazmat.primitives.asymmetric import rsa

    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)  # nosec B505
    rsa_pem = (
        rsa_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    no_embedded = dataclasses.replace(signed, public_key_pem=None)
    assert no_embedded.verify_signature(public_key_pem=rsa_pem) is False


def test_package_from_dict_defaults_and_dict_signature():
    raw = {
        "scenario_id": "s1",
        "trace_hash": "sha3_256:xyz",
        "signature": {
            "signature": "abcdef123456",
            "identity": "auditor-01",
            "public_key_pem": "pem-content",
            "algorithm": "ed25519",
            "key_id": "k-01",
        },
    }
    pkg = VerificationPackage.from_dict(raw)
    assert pkg.scenario_id == "s1"
    assert pkg.trace_hash == "sha3_256:xyz"
    assert pkg.signature == "abcdef123456"
    assert pkg.signer_identity == "auditor-01"
    assert pkg.public_key_pem == "pem-content"
    assert pkg.algorithm == "ed25519"
    assert pkg.key_id == "k-01"
    assert pkg.required_oracle_ids == []
    assert pkg.executed_oracle_results == []


def test_canonical_jcs_dumps_and_encode():
    from agentv_runtime.canonical import canonical_json_dumps, canonical_json_encode

    data = {
        "z": 100,
        "a": "hello world",
        "m": {"nested_b": 2, "nested_a": 1},
        "unicode": "téñ§",
    }
    dumped = canonical_json_dumps(data)
    # RFC 8785: sorted keys, no whitespace around separators, UTF-8 unicode preserved
    assert dumped == '{"a":"hello world","m":{"nested_a":1,"nested_b":2},"unicode":"téñ§","z":100}'

    encoded = canonical_json_encode(data)
    assert isinstance(encoded, bytes)
    assert encoded == dumped.encode("utf-8")


def test_rfc8785_utf16_code_unit_property_ordering():
    """RFC 8785 Section 3.2.3 requires sorting by UTF-16 code units."""
    from agentv_runtime.canonical import canonical_json_dumps

    obj = {
        "\uffff": "high BMP",
        "\U0001f600": "supplementary plane emoji",
        "a": "ascii a",
        "\u00e9": "latin e acute",
    }
    dumped = canonical_json_dumps(obj)
    expected = (
        '{"a":"ascii a","\u00e9":"latin e acute",'
        '"\U0001f600":"supplementary plane emoji","\uffff":"high BMP"}'
    )
    assert dumped == expected


def test_rfc8785_number_serialization():
    """RFC 8785 Section 3.2.2.3 requires ECMAScript 2020 Number.prototype.toString formatting."""
    from agentv_runtime.canonical import canonical_json_dumps

    cases = [
        (0, "0"),
        (-0.0, "0"),
        (0.0, "0"),
        (1.0, "1"),
        (-1.0, "-1"),
        (100.0, "100"),
        (-100.0, "-100"),
        (12.34, "12.34"),
        (0.00123, "0.00123"),
        (1e-6, "0.000001"),
        (-1e-6, "-0.000001"),
        (1e-7, "1e-7"),
        (-1e-7, "-1e-7"),
        (1e20, "100000000000000000000"),
        (1e21, "1e+21"),
        (1.5e23, "1.5e+23"),
        (-1.5e-7, "-1.5e-7"),
    ]
    for num, exp in cases:
        assert canonical_json_dumps(num) == exp, f"Failed for {num}"


def test_rfc8785_non_finite_numbers_fail():
    """RFC 8785 and I-JSON strictly forbid NaN and Infinity."""
    from agentv_runtime.canonical import canonical_json_dumps

    for bad_num in [float("nan"), float("inf"), float("-inf")]:
        with pytest.raises(ValueError, match="non-finite number violation"):
            canonical_json_dumps(bad_num)


def test_rfc8785_string_escaping():
    """RFC 8785 Section 3.2.2.2: only quote, reverse solidus, and 0x00..0x1F escaped."""
    from agentv_runtime.canonical import canonical_json_dumps

    assert canonical_json_dumps("hello/world") == '"hello/world"'
    assert canonical_json_dumps('quote: " and backslash: \\') == r'"quote: \" and backslash: \\"'
    assert canonical_json_dumps("line1\nline2\ttab\r\b\f") == r'"line1\nline2\ttab\r\b\f"'
    assert canonical_json_dumps("\x00\x1f") == r'"\u0000\u001f"'
    assert canonical_json_dumps("Hello, 世界! 🚀") == '"Hello, 世界! 🚀"'


def test_rfc8785_lone_surrogate_fails():
    """RFC 8785 forbids lone surrogates."""
    from agentv_runtime.canonical import canonical_json_dumps

    with pytest.raises(ValueError, match="lone surrogate"):
        canonical_json_dumps("\ud800")


def test_rfc8785_non_string_keys_fail():
    """Object keys must be strings."""
    from agentv_runtime.canonical import canonical_json_dumps

    with pytest.raises(TypeError, match="object keys must be strings"):
        canonical_json_dumps({123: "val"})


def test_rfc8785_structures():
    """Test nested arrays, objects, booleans, and null."""
    from agentv_runtime.canonical import canonical_json_encode

    data = {
        "z": [1, 2.0, False, True, None],
        "a": {"c": 3, "b": "nested"},
        "empty_list": [],
        "empty_dict": {},
    }
    encoded = canonical_json_encode(data)
    expected = (
        b'{"a":{"b":"nested","c":3},"empty_dict":{},"empty_list":[],"z":[1,2,false,true,null]}'
    )
    assert encoded == expected


def test_rfc8785_unsupported_type_fails():
    """Unsupported non-JSON types raise TypeError."""
    from agentv_runtime.canonical import canonical_json_dumps

    with pytest.raises(TypeError, match="RFC 8785 unsupported type"):
        canonical_json_dumps(object())
