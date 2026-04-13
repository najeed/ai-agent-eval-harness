import json

from eval_runner import config
from eval_runner.verifier import TraceVerifier


def test_verifier_end_to_end_v3_cycle(tmp_path, monkeypatch):
    """
    Harden Test: Verify full VC v3.0.0 cryptographic signing and verification cycle.
    Uses Run ID vault architecture and IdentityService.
    """
    # 1. Setup - Create a mock trace in a run vault
    run_id = "test-666"
    run_vault = tmp_path / "runs" / run_id
    run_vault.mkdir(parents=True)
    trace_path = run_vault / "run.jsonl"
    trace_content = b"sample trace data for VC v3 verification"
    trace_path.write_bytes(trace_content)

    # 2. Setup Identity
    identity_id = "validator"
    keys_dir = tmp_path / "keys" / identity_id
    TraceVerifier.generate_key_pair(output_dir=str(keys_dir))

    # Configure Environment
    monkeypatch.setattr(config, "TRUST_ROOT", tmp_path / "keys")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")

    # 3. Signing
    fingerprint = "dna_v3_hardened"
    manifest = TraceVerifier.sign_trace(
        str(trace_path),
        identity_id=identity_id,
        behavioral_fingerprint_id=fingerprint,
        run_id=run_id,
    )

    # 4. Schema Checks
    assert manifest["vc_version"] == "3.0.0"
    assert manifest["run_id"] == run_id
    assert manifest["behavioral_fingerprint_id"] == fingerprint
    assert "provenance_chain" in manifest
    assert len(manifest["provenance_chain"]) == 1

    # 5. Storage Checks (Vault storage)
    sidecar_path = run_vault / "run_manifest.json"
    auth_cert_path = tmp_path / "reports" / "certificates" / f"{run_id}_vc.json"

    assert sidecar_path.exists()
    assert auth_cert_path.exists()

    # 6. Verification
    assert TraceVerifier.verify_trace(str(trace_path), str(sidecar_path)) is True

    # 7. Tamper Check
    trace_path.write_bytes(b"TAMPERED")
    assert TraceVerifier.verify_trace(str(trace_path), str(sidecar_path)) is False


def test_verifier_missing_files():
    """Verify robust failure on missing artifacts."""
    assert (
        TraceVerifier.verify_trace("non_existent_trace.jsonl", "non_existent_manifest.json")
        is False
    )


def test_verifier_legacy_rejection(tmp_path, monkeypatch):
    """Verify that VC version < 3.0.0 is explicitly rejected."""
    run_dir = tmp_path / "legacy_run"
    run_dir.mkdir()
    trace_path = run_dir / "trace.jsonl"
    trace_path.write_text("{}")

    legacy_manifest = {
        "vc_version": "1.0.0",
        "sha256": TraceVerifier.compute_signature(trace_path),
        "run_id": "legacy",
    }
    manifest_path = run_dir / "run_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(legacy_manifest, f)

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is False


def test_verifier_security_jail_violation(tmp_path, monkeypatch):
    """Verify traversal protection in verifier."""
    outside_file = tmp_path / "outside.jsonl"
    outside_file.write_text("{}")

    # Set PROJECT_ROOT to a subdirectory
    jail_root = tmp_path / "jail"
    jail_root.mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", jail_root)

    assert TraceVerifier.verify_trace(str(outside_file), str(jail_root / "manifest.json")) is False


def test_verifier_expired_ttl(tmp_path, monkeypatch):
    """Verify governance TTL enforcement (v3)."""
    run_dir = tmp_path / "expired_run"
    run_dir.mkdir()
    trace_path = run_dir / "run.jsonl"
    trace_path.write_bytes(b"data")

    # Create a manifest with an old timestamp
    old_ts = "2020-01-01T12:00:00.000+0000"
    manifest = {
        "vc_version": "3.0.0",
        "timestamp": old_ts,
        "run_id": "expired",
        "sha256": TraceVerifier.compute_signature(trace_path),
        "governance_ttl": 30,  # 30 days
        "provenance_chain": [
            {"identity": "sys", "signature": "fake"}
        ],  # Triggered if we don't mock get_public_key
    }

    manifest_path = run_dir / "run_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f)

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    # Verification should fail due to TTL
    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is False
