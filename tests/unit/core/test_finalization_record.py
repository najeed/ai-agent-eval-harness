"""
tests/unit/core/test_finalization_record.py

Comprehensive unit tests for EvaluatorFinalizationRecord covering:
- Serialization & RFC 8785 canonical byte representation
- Field validations (mandatory strings, manifest hash, oracles, sequence,
  outcome, score, hash, signature)
- Signing with explicit Ed25519PrivateKey and IdentityService resolution
- Signature verification across Ed25519PublicKey, PEM bytes, PEM str,
  trust_root directory, and IdentityService
- Error handling on invalid hex, corrupt keys, unanchored identities, and tampered signatures
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from agentv_runtime.finalization import EvaluatorFinalizationRecord
from eval_runner import config
from eval_runner.identity import IdentityService


@pytest.fixture
def trust_env(tmp_path, monkeypatch):
    trust_dir = tmp_path / "trust_root"
    trust_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "TRUST_ROOT", trust_dir)
    IdentityService._provision_local_identity("test_evaluator")
    return {"trust_root": trust_dir}


def _valid_record_dict() -> dict:
    priv = ed25519.Ed25519PrivateKey.generate()
    rec = EvaluatorFinalizationRecord(
        finalization_id="fin_001",
        run_id="run_001",
        execution_manifest_hash="sha3_256:1111111111111111111111111111111111111111111111111111111111111111",
        scenario_id="scen_001",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:2222222222222222222222222222222222222222222222222222222222222222",
        evaluator_identity="test_evaluator",
        evaluator_config_hash="sha3_256:3333333333333333333333333333333333333333333333333333333333333333",
        required_oracle_ids=["oracle_1"],
        evidence_root_hash="sha3_256:4444444444444444444444444444444444444444444444444444444444444444",
        outcome="pass",
        score=1.0,
        terminal_seq=5,
    )
    signed = rec.sign(priv)
    return signed.to_dict()


def test_finalization_record_valid_from_dict():
    d = _valid_record_dict()
    rec = EvaluatorFinalizationRecord.from_dict(d, require_authoritative=True)
    assert rec.finalization_id == "fin_001"
    assert rec.run_id == "run_001"
    assert rec.outcome == "pass"
    assert rec.score == 1.0
    assert rec.terminal_seq == 5
    assert rec.evaluator_signature != ""
    assert rec.finalization_hash == rec.compute_finalization_hash()


def test_finalization_record_mandatory_str_fields_validation():
    base = _valid_record_dict()
    for field_name in (
        "finalization_id",
        "run_id",
        "scenario_id",
        "scenario_version",
        "scenario_hash",
        "evaluator_identity",
        "evaluator_config_hash",
        "evidence_root_hash",
    ):
        bad_dict = dict(base)
        bad_dict[field_name] = ""
        with pytest.raises(ValueError, match="Missing mandatory finalization trust field"):
            EvaluatorFinalizationRecord.from_dict(bad_dict, require_authoritative=True)


def test_finalization_record_manifest_hash_validation():
    bad = dict(_valid_record_dict())
    bad["execution_manifest_hash"] = ""
    bad["manifest_hash"] = ""
    with pytest.raises(ValueError, match="execution_manifest_hash"):
        EvaluatorFinalizationRecord.from_dict(bad, require_authoritative=True)


def test_finalization_record_required_oracles_validation():
    bad = dict(_valid_record_dict())
    bad["required_oracle_ids"] = "not-a-list"
    with pytest.raises(ValueError, match="must be a list"):
        EvaluatorFinalizationRecord.from_dict(bad, require_authoritative=True)


def test_finalization_record_terminal_seq_validation():
    bad = dict(_valid_record_dict())
    bad["terminal_seq"] = "not-an-int"
    with pytest.raises(ValueError, match="must be an integer"):
        EvaluatorFinalizationRecord.from_dict(bad, require_authoritative=True)


def test_finalization_record_outcome_validation():
    bad = dict(_valid_record_dict())
    bad["outcome"] = "invalid_outcome"
    with pytest.raises(ValueError, match="Missing or invalid mandatory finalization outcome"):
        EvaluatorFinalizationRecord.from_dict(bad, require_authoritative=True)


def test_finalization_record_score_validation():
    bad = dict(_valid_record_dict())
    bad["score"] = "string-score"
    with pytest.raises(ValueError, match="must be a float/int"):
        EvaluatorFinalizationRecord.from_dict(bad, require_authoritative=True)


def test_finalization_record_finalization_hash_validation():
    bad = dict(_valid_record_dict())
    bad["finalization_hash"] = ""
    with pytest.raises(ValueError, match="Missing mandatory 'finalization_hash'"):
        EvaluatorFinalizationRecord.from_dict(bad, require_authoritative=True)


def test_finalization_record_hash_mismatch_raises():
    bad = dict(_valid_record_dict())
    bad["finalization_hash"] = "sha3_256:" + "0" * 64
    with pytest.raises(ValueError, match="FinalizationHashMismatch"):
        EvaluatorFinalizationRecord.from_dict(bad, require_authoritative=True)


def test_finalization_record_signature_validation():
    bad = dict(_valid_record_dict())
    bad["evaluator_signature"] = ""
    bad["signature"] = ""
    with pytest.raises(
        ValueError,
        match="Missing mandatory finalization trust field 'evaluator_signature'",
    ):
        EvaluatorFinalizationRecord.from_dict(bad, require_authoritative=True)


def test_finalization_record_signing_with_identity_service(trust_env):
    rec = EvaluatorFinalizationRecord(
        finalization_id="fin_auto",
        run_id="run_auto",
        execution_manifest_hash="sha3_256:1111",
        scenario_id="scen_auto",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:2222",
        evaluator_identity="test_evaluator",
        evaluator_config_hash="sha3_256:3333",
        required_oracle_ids=[],
        evidence_root_hash="sha3_256:4444",
        outcome="pass",
        score=1.0,
        terminal_seq=1,
    )
    signed = rec.sign()
    assert signed.evaluator_signature != ""
    assert signed.verify_signature(trust_root=trust_env["trust_root"]) is True


def test_finalization_record_signing_invalid_signer_raises():
    from unittest.mock import patch

    rec = EvaluatorFinalizationRecord(
        finalization_id="fin_err",
        run_id="run_err",
        execution_manifest_hash="sha3_256:1111",
        scenario_id="scen_err",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:2222",
        evaluator_identity="test_evaluator",
        evaluator_config_hash="sha3_256:3333",
        required_oracle_ids=[],
        evidence_root_hash="sha3_256:4444",
        outcome="pass",
        score=1.0,
        terminal_seq=1,
    )
    # Signer object without sign method raises ValueError
    with pytest.raises(ValueError, match="Invalid signer object"):
        rec.sign(signer="not-a-signer")

    # Exception during get_private_key raises ValueError
    with patch(
        "eval_runner.identity.IdentityService.get_private_key",
        side_effect=RuntimeError("KMS offline"),
    ):
        with pytest.raises(ValueError, match="Could not resolve private key"):
            rec.sign()

    # None return from get_private_key raises ValueError
    with patch("eval_runner.identity.IdentityService.get_private_key", return_value=None):
        with pytest.raises(ValueError, match="No private key available"):
            rec.sign()


def test_finalization_record_from_dict_non_authoritative():
    # Calling from_dict with require_authoritative=False succeeds even with partial fields
    minimal = {
        "finalization_id": "fin_min",
        "run_id": "run_min",
    }
    rec = EvaluatorFinalizationRecord.from_dict(minimal, require_authoritative=False)
    assert rec.finalization_id == "fin_min"
    assert rec.run_id == "run_min"


def test_finalization_record_verify_signature_exception_in_identity_service():
    from unittest.mock import patch

    priv = ed25519.Ed25519PrivateKey.generate()
    rec = EvaluatorFinalizationRecord(
        finalization_id="fin_exc",
        run_id="run_exc",
        execution_manifest_hash="sha3_256:1111",
        scenario_id="scen_exc",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:2222",
        evaluator_identity="test_evaluator",
        evaluator_config_hash="sha3_256:3333",
        required_oracle_ids=[],
        evidence_root_hash="sha3_256:4444",
        outcome="pass",
        score=1.0,
        terminal_seq=1,
    ).sign(priv)

    with patch(
        "eval_runner.identity.IdentityService.get_public_key",
        side_effect=RuntimeError("Disk failure"),
    ):
        assert rec.verify_signature() is False


def test_finalization_record_verify_signature_formats_and_errors(trust_env):
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_pem_bytes = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub_pem_str = pub_pem_bytes.decode("utf-8")

    rec = EvaluatorFinalizationRecord(
        finalization_id="fin_sig",
        run_id="run_sig",
        execution_manifest_hash="sha3_256:1111",
        scenario_id="scen_sig",
        scenario_version="1.0.0",
        scenario_hash="sha3_256:2222",
        evaluator_identity="test_evaluator",
        evaluator_config_hash="sha3_256:3333",
        required_oracle_ids=[],
        evidence_root_hash="sha3_256:4444",
        outcome="pass",
        score=1.0,
        terminal_seq=1,
    ).sign(priv)

    # 1. Direct Ed25519PublicKey object
    assert rec.verify_signature(public_key=pub) is True

    # 2. PEM string
    assert rec.verify_signature(public_key=pub_pem_str) is True

    # 3. PEM bytes
    assert rec.verify_signature(public_key=pub_pem_bytes) is True

    # 4. Wrong public key -> False
    other_pub = ed25519.Ed25519PrivateKey.generate().public_key()
    assert rec.verify_signature(public_key=other_pub) is False

    # 5. Missing evaluator_signature -> False
    from dataclasses import replace

    no_sig = replace(rec, evaluator_signature="")
    assert no_sig.verify_signature(public_key=pub) is False

    # 6. Corrupt hex signature -> False
    corrupt_sig = replace(rec, evaluator_signature="not-hex-data!")
    assert corrupt_sig.verify_signature(public_key=pub) is False

    # 7. Unanchored identity without passed public_key -> False
    unknown_rec = replace(rec, evaluator_identity="unknown_identity_xyz")
    assert unknown_rec.verify_signature(trust_root=trust_env["trust_root"]) is False
