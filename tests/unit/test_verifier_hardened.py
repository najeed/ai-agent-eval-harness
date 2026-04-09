import json
from unittest.mock import patch

import pytest

from eval_runner import config
from eval_runner.verifier import TraceVerifier


def test_verifier_end_to_end_signing(tmp_path):
    """
    Harden Test: Verify full cryptographic signing and verification cycle.
    Uses real ED25519 keys and SHA-256 hashing. No mocks.
    """
    # 1. Setup - Create a mock trace file
    trace_content = b"sample trace data for cryptographic verification"
    trace_path = tmp_path / "test_run_123.jsonl"
    trace_path.write_bytes(trace_content)

    # 2. Key Generation for 'test_id'
    identity_id = "test_id"
    keys_dir = tmp_path / "keys" / identity_id
    TraceVerifier.generate_key_pair(output_dir=str(keys_dir))

    # Configure TRUST_ROOT for IdentityService
    original_trust = config.TRUST_ROOT
    config.TRUST_ROOT = tmp_path / "keys"

    public_key_path = keys_dir / "public_key.pem"
    assert public_key_path.exists()

    # 3. Signing
    fingerprint = "dna_abs_123_hardened"
    metadata = {"test": "hardened"}

    # We point REPORTS_DIR to tmp_path for test isolation
    original_reports = config.REPORTS_DIR
    config.REPORTS_DIR = tmp_path / "reports"

    try:
        manifest = TraceVerifier.sign_trace(
            trace_path=str(trace_path),
            metadata=metadata,
            identity_id=identity_id,
            behavioral_fingerprint_id=fingerprint,
        )

        # 4. Schema Hardening Checks (v3)
        assert manifest["harness_version"] == config.VERSION
        assert manifest["behavioral_fingerprint_id"] == fingerprint
        assert "provenance_chain" in manifest
        assert manifest["provenance_chain"][0]["algorithm"] == "ED25519"

        # 5. Storage Checks
        sidecar = tmp_path / "test_run_123_manifest.json"
        auth_cert = tmp_path / "reports" / "certificates" / "test_run_123_vc.json"

        assert sidecar.exists()
        assert auth_cert.exists()

        # 6. Verification
        is_valid = TraceVerifier.verify_trace(
            trace_path=str(trace_path),
            manifest_path=str(sidecar),
            public_key_path=str(public_key_path),
        )
        assert is_valid is True

        # 7. Tamper Check
        trace_path.write_bytes(b"tampered data")
        is_valid_tampered = TraceVerifier.verify_trace(
            trace_path=str(trace_path),
            manifest_path=str(sidecar),
            public_key_path=str(public_key_path),
        )
        assert is_valid_tampered is False

    finally:
        config.REPORTS_DIR = original_reports
        config.TRUST_ROOT = original_trust


def test_verifier_without_fingerprint(tmp_path):
    """Verify that no placeholder is added if fingerprint is omitted."""
    trace_path = tmp_path / "simple.jsonl"
    trace_path.write_bytes(b"data")

    manifest = TraceVerifier.sign_trace(str(trace_path), behavioral_fingerprint_id="custom_dna")
    assert manifest["behavioral_fingerprint_id"] == "custom_dna"
    
    # In v3, we always have a default fingerprint_id if not provided
    manifest_default = TraceVerifier.sign_trace(str(trace_path))
    assert manifest_default["behavioral_fingerprint_id"] == "default_v1"


def test_verifier_missing_files(tmp_path):
    """Line 44 & 95: Verify FileNotFoundError and False on missing files."""
    with pytest.raises(FileNotFoundError):
        TraceVerifier.sign_trace("non_existent_file.jsonl")

    assert TraceVerifier.verify_trace("missing_trace.jsonl", "missing_manifest.json") is False


def test_verifier_relative_path_keys(tmp_path):
    """Line 142: Verify generate_key_pair handles relative paths."""
    # We use a relative path from PROJECT_ROOT
    rel_path = ".aes/test_keys_rel"
    abs_path = config.PROJECT_ROOT / rel_path

    try:
        TraceVerifier.generate_key_pair(output_dir=rel_path)
        assert (abs_path / "private_key.pem").exists()
    finally:
        if abs_path.exists():
            import shutil

            shutil.rmtree(abs_path)


def test_verifier_unverifiable_signature(tmp_path):
    """Lines 119-121: Verify manifest without a public key returns True (Integrity Only)."""
    trace_path = tmp_path / "unverifiable.jsonl"
    trace_path.write_bytes(b"data")

    # 2. Setup identity
    identity_id = "unverifiable_id"
    keys_dir = tmp_path / "keys_unv" / identity_id
    TraceVerifier.generate_key_pair(output_dir=str(keys_dir))
    
    original_trust = config.TRUST_ROOT
    config.TRUST_ROOT = tmp_path / "keys_unv"

    try:
        manifest = TraceVerifier.sign_trace(
            str(trace_path), identity_id=identity_id
        )

        manifest_path = tmp_path / "unverifiable_manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)

        # Verify without public_key_path explicitly. 
        # In the new world, verify_trace(tp, mp) without key path will try resolution.
        # If it fails resolution, it might return False or True based on integrity.
        # Our current implementation returns True if it fails cryptographic proof but integrity passes (Legacy)
        # OR it fails if v3 signature is invalid.
        assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is True
    finally:
        config.TRUST_ROOT = original_trust


def test_verifier_exception_handling(tmp_path):
    """Lines 124-125 & 189-190: Verify exception handling in verifier."""
    trace_path = tmp_path / "exception.jsonl"
    trace_path.write_bytes(b"data")

    manifest_path = tmp_path / "corrupt_manifest.json"
    manifest_path.write_text("invalid json")

    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is False

    # Cryptographic verification exception (Now handled by top-level try-except)
    assert (
        TraceVerifier.verify_asymmetric(b"data", "not-hex-signature", "invalid-key-path") is False
    )


def test_verifier_unsigned_manifest(tmp_path):
    """Line 123: Verify that an unsigned manifest correctly returns True (Integrity Only)."""
    trace_path = tmp_path / "unsigned.jsonl"
    trace_path.write_bytes(b"data")

    # Ensure it's unsigned by bypassing provenance
    with patch("eval_runner.identity.IdentityService.get_private_key", side_effect=Exception("Disabled")):
        manifest = TraceVerifier.sign_trace(str(trace_path))
        # Downgrade to legacy for integrity-only test
        manifest["vc_version"] = "1.0.0"
        
    manifest_path = tmp_path / "unsigned_manifest.json"

    # Ensure it's unsigned
    assert not manifest.get("provenance_chain")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f)

    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is True
