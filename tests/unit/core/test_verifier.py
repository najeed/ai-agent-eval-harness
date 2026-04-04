"""
test_verifier.py

Unit tests for the TraceVerifier class.
Ensures SHA-256 signing and verification of run traces are accurate.
"""

import pytest
import json
from pathlib import Path
from eval_runner.verifier import TraceVerifier

def test_compute_signature(tmp_path):
    """Verifies that SHA-256 computation is deterministic and correct."""
    test_file = tmp_path / "trace.jsonl"
    content = b'{"event": "test"}\n'
    test_file.write_bytes(content)
    
    sig1 = TraceVerifier.compute_signature(test_file)
    sig2 = TraceVerifier.compute_signature(test_file)
    
    assert sig1 == sig2
    assert len(sig1) == 64  # SHA-256 length

def test_sign_trace_success(tmp_path):
    """Verifies successful generation of a manifest.json file."""
    trace_file = tmp_path / "run_123.jsonl"
    trace_file.write_text('{"event": "start"}', encoding="utf-8")
    
    manifest = TraceVerifier.sign_trace(str(trace_file), metadata={"user": "test_bot"})
    
    # 1. Verify returned dictionary
    assert manifest["trace_file"] == "run_123.jsonl"
    assert manifest["metadata"]["user"] == "test_bot"
    assert "sha256" in manifest

    # 2. Verify file on disk (backward compatibility)
    manifest_path = tmp_path / "run_123_manifest.json"
    assert manifest_path.exists()
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        stored_manifest = json.load(f)
    
    assert stored_manifest["sha256"] == manifest["sha256"]

def test_sign_trace_not_found():
    """Verifies that FileNotFoundError is raised for missing traces."""
    with pytest.raises(FileNotFoundError):
        TraceVerifier.sign_trace("non_existent.jsonl")

def test_verify_trace_success(tmp_path):
    """Verifies that a valid trace and manifest pair return True."""
    trace_file = tmp_path / "valid.jsonl"
    trace_file.write_text("content", encoding="utf-8")
    
    TraceVerifier.sign_trace(str(trace_file))
    manifest_path = tmp_path / "valid_manifest.json"
    
    result = TraceVerifier.verify_trace(str(trace_file), str(manifest_path))
    assert result is True

def test_verify_trace_tampered(tmp_path):
    """Verifies that a tampered trace file fails validation."""
    trace_file = tmp_path / "tamper_me.jsonl"
    trace_file.write_text("original", encoding="utf-8")
    
    TraceVerifier.sign_trace(str(trace_file))
    manifest_path = tmp_path / "tamper_me_manifest.json"
    
    # Tamper with the trace
    trace_file.write_text("manipulated", encoding="utf-8")
    
    result = TraceVerifier.verify_trace(str(trace_file), str(manifest_path))
    assert result is False

def test_verify_trace_missing_files(tmp_path):
    """Verifies that missing files return False."""
    assert TraceVerifier.verify_trace("ghost.jsonl", "ghost_manifest.json") is False

def test_verify_trace_invalid_json(tmp_path):
    """Verifies that malformed manifest returns False."""
    trace_file = tmp_path / "t.jsonl"
    trace_file.write_text("ok")
    
    bad_manifest = tmp_path / "bad_manifest.json"
    bad_manifest.write_text("not json")
    
    assert TraceVerifier.verify_trace(str(trace_file), str(bad_manifest)) is False
