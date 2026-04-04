import pytest
import json
import os
from pathlib import Path
from eval_runner.verifier import TraceVerifier
from eval_runner import config

def test_verifier_end_to_end_signing(tmp_path):
    """
    Harden Test: Verify full cryptographic signing and verification cycle.
    Uses real ED25519 keys and SHA-256 hashing. No mocks.
    """
    # 1. Setup - Create a mock trace file
    trace_content = b"sample trace data for cryptographic verification"
    trace_path = tmp_path / "test_run_123.jsonl"
    trace_path.write_bytes(trace_content)
    
    # 2. Key Generation
    keys_dir = tmp_path / "keys"
    TraceVerifier.generate_key_pair(output_dir=str(keys_dir))
    
    private_key_path = keys_dir / "private_key.pem"
    public_key_path = keys_dir / "public_key.pem"
    
    assert private_key_path.exists()
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
            private_key_path=str(private_key_path),
            fingerprint_id=fingerprint
        )
        
        # 4. Schema Hardening Checks
        assert manifest["harness_version"] == "1.2.3"
        assert manifest["behavioral_fingerprint_id"] == fingerprint
        assert "signature_ed25519" in manifest
        assert manifest["signing_algorithm"] == "ED25519"
        
        # 5. Storage Checks
        sidecar = tmp_path / "test_run_123_manifest.json"
        auth_cert = tmp_path / "reports" / "certificates" / "test_run_123_vc.json"
        
        assert sidecar.exists()
        assert auth_cert.exists()
        
        # 6. Verification
        is_valid = TraceVerifier.verify_trace(
            trace_path=str(trace_path),
            manifest_path=str(sidecar),
            public_key_path=str(public_key_path)
        )
        assert is_valid is True
        
        # 7. Tamper Check
        trace_path.write_bytes(b"tampered data")
        is_valid_tampered = TraceVerifier.verify_trace(
            trace_path=str(trace_path),
            manifest_path=str(sidecar),
            public_key_path=str(public_key_path)
        )
        assert is_valid_tampered is False
        
    finally:
        config.REPORTS_DIR = original_reports

def test_verifier_without_fingerprint(tmp_path):
    """Verify that no placeholder is added if fingerprint is omitted."""
    trace_path = tmp_path / "simple.jsonl"
    trace_path.write_bytes(b"data")
    
    manifest = TraceVerifier.sign_trace(str(trace_path))
    assert "behavioral_fingerprint_id" not in manifest

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
    
    keys_dir = tmp_path / "keys_unverifiable"
    TraceVerifier.generate_key_pair(output_dir=str(keys_dir))
    
    manifest = TraceVerifier.sign_trace(
        str(trace_path),
        private_key_path=str(keys_dir / "private_key.pem")
    )
    
    manifest_path = tmp_path / "unverifiable_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f)
        
    # Verify without public key. Should return True based on integrity check.
    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is True

def test_verifier_exception_handling(tmp_path):
    """Lines 124-125 & 189-190: Verify exception handling in verifier."""
    trace_path = tmp_path / "exception.jsonl"
    trace_path.write_bytes(b"data")
    
    manifest_path = tmp_path / "corrupt_manifest.json"
    manifest_path.write_text("invalid json")
    
    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is False
    
    # Cryptographic verification exception (Now handled by top-level try-except)
    assert TraceVerifier.verify_asymmetric(b"data", "not-hex-signature", "invalid-key-path") is False

def test_verifier_unsigned_manifest(tmp_path):
    """Line 123: Verify that an unsigned manifest correctly returns True (Integrity Only)."""
    trace_path = tmp_path / "unsigned.jsonl"
    trace_path.write_bytes(b"data")
    
    manifest = TraceVerifier.sign_trace(str(trace_path))
    manifest_path = tmp_path / "unsigned_manifest.json"
    
    # Ensure it's unsigned
    assert "signature_ed25519" not in manifest
    with open(manifest_path, "w") as f:
        json.dump(manifest, f)
        
    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is True
