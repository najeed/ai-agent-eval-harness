import json
import pytest
from pathlib import Path
from eval_runner import config
from eval_runner.verifier import TraceVerifier
from eval_runner.identity import IdentityService

@pytest.fixture
def isolated_trust(tmp_path):
    """Fixture to isolate trust root for tests."""
    original_root = config.TRUST_ROOT
    config.TRUST_ROOT = tmp_path / "trust"
    yield config.TRUST_ROOT
    config.TRUST_ROOT = original_root

def test_v3_manifest_generation(isolated_trust, tmp_path):
    """Verify VC v3 manifest compliance and schema."""
    trace_path = tmp_path / "test.jsonl"
    trace_path.write_text("event1\nevent2")
    
    # Create sidecar artifacts
    (tmp_path / "terminal.log").write_text("terminal output")
    (tmp_path / "db.sqlite").write_text("database bytes")
    
    manifest = TraceVerifier.sign_trace(
        str(trace_path),
        identity_id="test_auditor",
        compliance_status="pass",
        compliance_score=0.98,
        policy_ref="SOC2-T1"
    )
    
    # Check v3 fields
    assert manifest["vc_version"] == "3.0.0"
    assert manifest["compliance"]["status"] == "pass"
    assert manifest["compliance"]["score"] == 0.98
    assert manifest["compliance"]["policy_ref"] == "SOC2-T1"
    
    # Check forensic ledger
    assert "terminal.log" in manifest["evidence_ledger"]
    assert "db.sqlite" in manifest["evidence_ledger"]
    assert manifest["trace_file"] not in manifest["evidence_ledger"]
    
    # Check provenance
    assert len(manifest["provenance_chain"]) == 1
    assert manifest["provenance_chain"][0]["identity"] == "test_auditor"

def test_v3_signature_verification(isolated_trust, tmp_path):
    """Verify that v3 signatures are deterministic and verifiable."""
    trace_path = tmp_path / "sign_test.jsonl"
    trace_path.write_text("content")
    
    manifest = TraceVerifier.sign_trace(str(trace_path), identity_id="signer_id")
    manifest_path = tmp_path / "sign_test_manifest.json"
    
    with open(manifest_path, "w") as f:
        json.dump(manifest, f)
        
    # Verify
    is_valid = TraceVerifier.verify_trace(str(trace_path), str(manifest_path))
    assert is_valid is True

def test_v3_tamper_detection(isolated_trust, tmp_path):
    """Verify that tampering with any part of the forensic package fails verification."""
    trace_path = tmp_path / "secure.jsonl"
    trace_path.write_text("baseline")
    (tmp_path / "evidence.txt").write_text("raw evidence")
    
    manifest = TraceVerifier.sign_trace(str(trace_path))
    manifest_path = tmp_path / "secure_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f)
        
    # 1. Tamper with trace
    trace_path.write_text("modified")
    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is False
    trace_path.write_text("baseline") # Restore
    
    # 2. Tamper with evidence (ledger check enabled)
    (tmp_path / "evidence.txt").write_text("modified evidence")
    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path), verify_ledger=True) is False

def test_v3_governance_ttl(isolated_trust, tmp_path):
    """Verify that expired certificates fail verification."""
    trace_path = tmp_path / "ttl_test.jsonl"
    trace_path.write_text("data")
    
    # Certify with -1 day TTL (expired)
    manifest = TraceVerifier.sign_trace(str(trace_path), ttl_days=-1)
    manifest_path = tmp_path / "ttl_test_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f)
        
    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is False
