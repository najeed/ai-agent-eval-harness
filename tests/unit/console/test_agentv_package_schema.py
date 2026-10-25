"""
[Spec] agentv-package.json contract: the built package must validate against
spec/agentv-package/agentv-package.schema.json, including the REQUIRED
five-field chain header.
"""

import json
from pathlib import Path

import jsonschema
import pytest

from eval_runner.console.routes.evidence import build_verification_package
from eval_runner.reference.local_run_store import LocalFileRunStore

SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "spec" / "agentv-package" / "agentv-package.schema.json"
)


@pytest.fixture
def package_vault(tmp_path):
    run_id = "pkg-contract-run"
    store = LocalFileRunStore(tmp_path / "runs")
    scenario = {"id": "sample", "aes_version": 1.4}
    store.create_run(run_id, "sample", metadata={"scenario_data": scenario})
    store.append_events(
        run_id,
        [
            {
                "event": "run_start",
                "run_id": run_id,
                "scenario": "sample",
                "identifier": "target-abc",
                "execution_mode": "live",
                "execution_mode_declared": True,
                "reproducibility_fingerprint": "sha3_256:" + "a" * 64,
            },
            {
                "event": "run_end",
                "run_id": run_id,
                "data": {"passed": False, "status": "EXECUTION_FAILED"},
            },
        ],
    )
    store.save_run_manifest(
        run_id,
        {
            "scenario_data": scenario,
            "execution_manifest": {
                "scope": {
                    "org_id": "northstar-health",
                    "tenant_id": "northstar-health",
                    "workspace_id": "utilization-management",
                    "active_environment": "Staging",
                }
            },
        },
    )
    return run_id, store


def test_package_validates_against_spec_schema(package_vault):
    run_id, store = package_vault
    pkg = build_verification_package(run_id, run_store=store)
    assert pkg is not None

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=pkg, schema=schema)


def test_chain_header_binds_five_fields(package_vault):
    from agentv_runtime.manifest import compute_scenario_hash

    run_id, store = package_vault
    pkg = build_verification_package(run_id, run_store=store)
    chain = pkg["chain"]

    assert chain["run_id"] == run_id
    assert chain["scenario_hash"] == compute_scenario_hash({"id": "sample", "aes_version": 1.4})
    assert chain["resolved_config_hash"] == "sha3_256:" + "a" * 64
    assert chain["agent_target_id"] == "target-abc"
    assert chain["execution_mode"] == "live"
    assert chain["execution_mode_declared"] is True


def test_package_signed_execution_scope_not_default_envelope(package_vault):
    """A Northstar run must never export fabricated ``default-*`` scope values."""
    run_id, store = package_vault
    pkg = build_verification_package(run_id, run_store=store)

    assert pkg["org_id"] == "northstar-health"
    assert pkg["tenant_id"] == "northstar-health"
    assert pkg["workspace_id"] == "utilization-management"
    assert pkg["active_environment"] == "Staging"


def test_undeclared_mode_stamps_unknown_provisional(tmp_path):
    """A trace with no declared mode yields truthful unknown + provisional."""
    store = LocalFileRunStore(tmp_path / "runs")
    store.create_run("legacy-run", "legacy")
    store.append_events("legacy-run", [{"event": "run_end", "data": {"passed": False}}])
    store.save_run_manifest("legacy-run", {"status": "OPEN"})

    pkg = build_verification_package("legacy-run", run_store=store)
    assert pkg["chain"]["execution_mode"] == "unknown"
    assert pkg["chain"]["execution_mode_declared"] is False


def test_verification_package_verify_signature_missing_trust_root_branches(tmp_path):
    from agentv_runtime.package import VerificationPackage

    pkg = VerificationPackage(
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash="scen_hash_1",
        manifest_id="man_1",
        manifest_hash="man_hash_1",
        execution_identity={},
        trace_hash="trace_hash_1",
        trace_seal={},
        evidence_root_hash="ev_root_1",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={},
        package_id="pkg_test_branches",
        signer_identity="",
        key_id="",
        signature="abc",
    )

    class MockTrustRootNoKey:
        def get_public_key(self, target_id):
            return None

    # Branch 235->269: trust_root has get_public_key but returns None
    assert pkg.verify_signature(trust_root=MockTrustRootNoKey()) is False

    # Branch 244->269: trust_root is neither object with get_public_key nor str/Path
    assert pkg.verify_signature(trust_root=12345) is False

    # Branch: trust_root is Path, but key_id and signer_identity are empty
    assert pkg.verify_signature(trust_root=tmp_path) is False


def test_verification_package_sign_verify_strict_and_key_registry_branches(tmp_path):
    """Test package signing, key registry, embedded key mismatch, strict mode, and error paths."""
    from unittest.mock import patch

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

    from agentv_runtime.package import VerificationPackage

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    pub_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    class MockSigner:
        identity = "test-signer"
        algorithm = "ed25519"
        key_id = "test-key-id"
        public_key_pem = pub_pem

        def sign(self, payload: bytes) -> bytes:
            return private_key.sign(payload)

    pkg = VerificationPackage(
        scenario_id="scen_1",
        scenario_version="1.0.0",
        scenario_hash="scen_hash_1",
        manifest_id="man_1",
        manifest_hash="man_hash_1",
        execution_identity={},
        trace_hash="trace_hash_1",
        trace_seal={},
        evidence_root_hash="ev_root_1",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={},
        package_id="pkg_test_full",
    )

    signed_pkg = pkg.sign(MockSigner())
    assert signed_pkg.signature is not None

    # Verification with explicit public_key_pem
    assert signed_pkg.verify_signature(public_key_pem=pub_pem) is True

    # Verification with key_registry by key_id and by signer_identity
    assert signed_pkg.verify_signature(key_registry={"test-key-id": pub_pem}) is True

    class MockSignerNoKeyId:
        identity = "test-signer"
        algorithm = "ed25519"
        key_id = ""
        public_key_pem = pub_pem

        def sign(self, payload: bytes) -> bytes:
            return private_key.sign(payload)

    pkg_by_signer = pkg.sign(MockSignerNoKeyId())
    assert pkg_by_signer.verify_signature(key_registry={"test-signer": pub_pem}) is True

    # Verification with trust_root object providing get_public_key
    class MockTrustRootWithKey:
        def get_public_key(self, target_id):
            return public_key

    assert signed_pkg.verify_signature(trust_root=MockTrustRootWithKey()) is True

    # Verification with trust_root raising exception in get_public_key
    class MockTrustRootErr:
        def get_public_key(self, target_id):
            raise RuntimeError("Trust root lookup failure")

    assert signed_pkg.verify_signature(trust_root=MockTrustRootErr()) is False

    # Signature missing branch
    unsigned = VerificationPackage.from_dict({**signed_pkg.to_dict(), "signature": ""})
    assert unsigned.verify_signature() is False

    # Embedded key mismatch branch
    other_key = ed25519.Ed25519PrivateKey.generate().public_key()
    other_pem = other_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    assert signed_pkg.verify_signature(public_key_pem=other_pem) is False

    # Corrupted embedded key branch
    corrupt_embed = VerificationPackage.from_dict(
        {**signed_pkg.to_dict(), "public_key_pem": "NOT_A_VALID_PEM"}
    )
    assert corrupt_embed.verify_signature(public_key_pem=pub_pem) is False

    # Non-Ed25519 public key branch
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    rsa_pem = rsa_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    assert signed_pkg.verify_signature(public_key_pem=rsa_pem) is False

    # Default IdentityService exception fallback branch
    with patch(
        "eval_runner.identity.IdentityService.get_public_key",
        side_effect=RuntimeError("Unavailable"),
    ):
        assert signed_pkg.verify_signature() is False

    # Default IdentityService successful retrieval branch
    with patch(
        "eval_runner.identity.IdentityService.get_public_key",
        return_value=public_key,
    ):
        assert signed_pkg.verify_signature() is True

    # Default IdentityService returning None branch
    with patch(
        "eval_runner.identity.IdentityService.get_public_key",
        return_value=None,
    ):
        assert signed_pkg.verify_signature() is False

    # Matching non-Ed25519 key (e.g. RSA) fails closed without exception
    rsa_pkg = VerificationPackage.from_dict({**signed_pkg.to_dict(), "public_key_pem": rsa_pem})
    assert rsa_pkg.verify_signature(public_key_pem=rsa_pem) is False

    # Key registry lookup miss
    assert signed_pkg.verify_signature(key_registry={"unrelated_key_id": pub_pem}) is False

    # Trust root directory candidate miss
    assert signed_pkg.verify_signature(trust_root=tmp_path / "nonexistent_dir") is False

    # Verification when package carries no embedded public_key_pem
    no_pub_pkg = VerificationPackage.from_dict({**signed_pkg.to_dict(), "public_key_pem": ""})
    assert no_pub_pkg.verify_signature(public_key_pem=pub_pem) is True

    # Verification failure on invalid signature bytes
    corrupt_sig_pkg = VerificationPackage.from_dict(
        {**signed_pkg.to_dict(), "signature": "00" * 64}
    )
    assert corrupt_sig_pkg.verify_signature(public_key_pem=pub_pem) is False

    # Dict signature form in from_dict
    dict_sig_pkg = VerificationPackage.from_dict(
        {
            **signed_pkg.to_dict(),
            "signature": {
                "signature": signed_pkg.signature,
                "identity": "dict-signer",
                "public_key_pem": pub_pem,
                "algorithm": "ed25519",
                "key_id": "dict-key-id",
            },
        }
    )
    assert dict_sig_pkg.signer_identity == "dict-signer"
    assert dict_sig_pkg.key_id == "dict-key-id"

    # Strict mode validation on missing scenario_id or trace_hash
    with pytest.raises(ValueError, match="strict instantiation requires valid"):
        VerificationPackage.from_dict({"scenario_id": ""}, strict=True)
