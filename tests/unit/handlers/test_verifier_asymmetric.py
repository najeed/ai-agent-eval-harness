import json

from eval_runner import config
from eval_runner.verifier import TraceVerifier


def test_key_generation(tmp_path):
    """Test generating ED25519 key pair via TraceVerifier utility."""
    key_dir = tmp_path / "keys"
    TraceVerifier.generate_key_pair(str(key_dir))

    assert (key_dir / "private_key.pem").exists()
    assert (key_dir / "public_key.pem").exists()

    # Check if they are PEM formatted
    priv_content = (key_dir / "private_key.pem").read_text()
    pub_content = (key_dir / "public_key.pem").read_text()

    assert "-----BEGIN PRIVATE KEY-----" in priv_content
    assert "-----BEGIN PUBLIC KEY-----" in pub_content


def test_trace_verification_cycle(tmp_path, monkeypatch):
    """
    Test the full VC v3.0.0 cycle: compute hash, sign, and verify.
    This replaces the legacy test_asymmetric_sign_verify.
    """
    # 1. Setup - Create a mock trace in a run directory
    run_id = "test-run-v3"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    trace_path = run_dir / "run.jsonl"
    trace_content = b'{"event":"test"}'
    trace_path.write_bytes(trace_content)

    # 2. Setup Identities
    identity_id = "tester_id"
    keys_dir = tmp_path / "keys" / identity_id
    TraceVerifier.generate_key_pair(str(keys_dir))

    # Configure TRUST_ROOT and PROJECT_ROOT for testing
    monkeypatch.setattr(config, "TRUST_ROOT", tmp_path / "keys")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")

    # 3. Sign Trace
    manifest = TraceVerifier.sign_trace(str(trace_path), identity_id=identity_id, run_id=run_id)

    assert manifest["vc_version"] == "3.0.0"
    assert manifest["run_id"] == run_id
    assert manifest["trace_hash"] == TraceVerifier.compute_signature(trace_path)
    assert len(manifest["provenance_chain"]) == 1
    assert manifest["provenance_chain"][0]["identity"] == identity_id

    # 4. Success Verification
    manifest_path = run_dir / "run_manifest.json"
    assert manifest_path.exists()

    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is True

    # 5. Tamper Verification (Data mismatch)
    trace_path.write_bytes(b"TAMPERED")
    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is False

    # 6. Corruption Verification (Manifest mismatch)
    trace_path.write_bytes(trace_content)  # Restore
    with open(manifest_path) as f:
        bad_manifest = json.load(f)
    bad_manifest["sha256"] = "wrong-hash"
    bad_manifest_path = run_dir / "bad_manifest.json"
    with open(bad_manifest_path, "w") as f:
        json.dump(bad_manifest, f)

    assert TraceVerifier.verify_trace(str(trace_path), str(bad_manifest_path)) is False
