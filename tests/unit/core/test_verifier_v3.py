import hashlib
import json

import pytest

from eval_runner import config
from eval_runner.verifier import TraceVerifier


@pytest.fixture
def isolated_trust(tmp_path, monkeypatch):
    """Fixture to isolate trust root for tests and allow provisioning."""
    original_root = config.TRUST_ROOT
    config.TRUST_ROOT = tmp_path / "trust"

    # Enable provisioning for tests to allow automatic identity creation
    monkeypatch.setattr("eval_runner.config.ALLOW_SYSTEM_IDENTITY_PROVISIONING", True)

    from eval_runner.config import RegistryManager

    RegistryManager.reload()

    yield config.TRUST_ROOT
    config.TRUST_ROOT = original_root
    RegistryManager.reload()


def test_v3_manifest_generation(isolated_trust, tmp_path):
    """Verify VC v3 manifest compliance and schema."""
    trace_path = tmp_path / "test.jsonl"
    trace_path.write_text("event1\nevent2")

    # Create sidecar artifacts (Prefix with 'test' to satisfy Namespace Affinity)
    (tmp_path / "test_terminal.log").write_text("terminal output")
    (tmp_path / "test_db.sqlite").write_text("database bytes")

    manifest = TraceVerifier.sign_trace(
        str(trace_path),
        identity_id="test_auditor",
        compliance_status="pass",
        compliance_score=0.98,
        policy_ref="SOC2-T1",
    )

    # Check v3 fields
    assert manifest["vc_version"] == "3.0.0"
    assert manifest["compliance"]["status"] == "pass"
    assert manifest["compliance"]["score"] == 0.98
    assert manifest["compliance"]["policy_ref"] == "SOC2-T1"

    # Forensic Discovery: We expect artifacts to be prefix-matched or in forensics/
    # If the directory matches run_id, prefix isn't required but helps consistency
    assert "test_terminal.log" in manifest["evidence_ledger"]
    assert "test_db.sqlite" in manifest["evidence_ledger"]
    assert manifest["trace_file"] == "test.jsonl"  # Standard stem-based run_id

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
    (tmp_path / "secure_evidence.txt").write_text("raw evidence")  # Prefixed for Affinity

    manifest = TraceVerifier.sign_trace(str(trace_path))
    manifest_path = tmp_path / "secure_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f)

    # 1. Tamper with trace
    trace_path.write_text("modified")
    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is False
    trace_path.write_text("baseline")  # Restore

    # 2. Tamper with evidence (ledger check enabled)
    (tmp_path / "secure_evidence.txt").write_text("modified evidence")
    assert (
        TraceVerifier.verify_trace(str(trace_path), str(manifest_path), verify_ledger=True) is False
    )


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


def test_v3_forensic_relevance_bypass(isolated_trust, tmp_path, monkeypatch):
    """Verify that mandatory patterns bypass the forensic size quota."""
    trace_path = tmp_path / "bypass_test.jsonl"
    trace_path.write_text("trace content")

    # 1. Create a large DB file (6MB) -> Exceeds default 5MB limit
    large_db = tmp_path / "bypass_test_heavy.db"  # Prefixed for Affinity
    with open(large_db, "wb") as f:
        f.write(b"0" * (6 * 1024 * 1024))

    # Standard sign (Should exclude large_db by default)
    manifest_default = TraceVerifier.sign_trace(str(trace_path))
    assert "bypass_test_heavy.db" not in manifest_default["evidence_ledger"]

    # 2. Add pattern to mandatory list via monkeypatch
    # We now use setenv because config is refactored to check env/registry dynamically
    monkeypatch.setenv("FORENSIC_MANDATORY_PATTERNS", "bypass_test_heavy.*")

    # RELOAD REGISTRY to see new env var
    from eval_runner.config import RegistryManager

    RegistryManager.reload()

    # Sign again with bypass (Should include large_db now)
    manifest_bypass = TraceVerifier.sign_trace(str(trace_path))
    assert "bypass_test_heavy.db" in manifest_bypass["evidence_ledger"]

    # Verify the hash is computed correctly for the 6MB file
    expected_hash = hashlib.sha256(b"0" * (6 * 1024 * 1024)).hexdigest()
    assert manifest_bypass["evidence_ledger"]["bypass_test_heavy.db"] == expected_hash


def test_v3_forensic_tier1_inclusion(isolated_trust, tmp_path):
    """Verify that any file in the forensics/ directory is unconditionally included."""
    trace_path = tmp_path / "tier1_test.jsonl"
    trace_path.write_text("trace")

    forensics_dir = tmp_path / "forensics"
    forensics_dir.mkdir()

    # 1. Forensic file with unauthorized extension (.exe)
    junk_binary = forensics_dir / "suspect.exe"
    junk_binary.write_text("malicious content")

    # 2. Forensic file that is huge (10MB)
    huge_log = forensics_dir / "massive.log"
    with open(huge_log, "wb") as f:
        f.write(b"L" * (10 * 1024 * 1024))

    manifest = TraceVerifier.sign_trace(str(trace_path))

    # Both MUST be included because they are in forensics/ (Tier 1)
    assert "forensics/suspect.exe" in manifest["evidence_ledger"]
    assert "forensics/massive.log" in manifest["evidence_ledger"]


def test_v3_forensic_exclusion_filtering(isolated_trust, tmp_path):
    """Verify that EXCLUSION_PATTERNS correctly drop platform junk."""
    trace_path = tmp_path / "exclude_test.jsonl"
    trace_path.write_text("trace")

    # Allowed extension (.log) but matches exclusion pattern (.*\.node$)
    node_log = tmp_path / "addon.node"
    node_log.write_text("binary data")

    # Allowed extension (.json) but matches exclusion pattern (.*\.cache$)
    cache_file = tmp_path / "meta.cache"
    cache_file.write_text("{}")

    manifest = TraceVerifier.sign_trace(str(trace_path))

    # Both MUST be excluded
    assert "addon.node" not in manifest["evidence_ledger"]
    assert "meta.cache" not in manifest["evidence_ledger"]


def test_v3_forensic_extension_filtering(isolated_trust, tmp_path):
    """Verify that only allowed enterprise extensions are collected."""
    trace_path = tmp_path / "ext_test.jsonl"
    trace_path.write_text("trace")

    (tmp_path / "ext_test_data.parquet").write_text("parquet data")
    (tmp_path / "ext_test_config.yaml").write_text("yaml content")
    (tmp_path / "ext_test_legacy.doc").write_text("doc")  # Not in allowed list

    manifest = TraceVerifier.sign_trace(str(trace_path))

    # Check for run_id prefixed files
    assert "ext_test_data.parquet" in manifest["evidence_ledger"]
    assert "ext_test_config.yaml" in manifest["evidence_ledger"]
    assert "ext_test_legacy.doc" not in manifest["evidence_ledger"]


def test_v3_forensic_alias_normalization(isolated_trust, tmp_path):
    """Verify that .jpeg matches .jpg, .text matches .txt, etc."""
    trace_path = tmp_path / "alias_test.jsonl"
    trace_path.write_text("trace")

    # We allow .jpg and .txt by default
    (tmp_path / "alias_test_image.jpeg").write_text("jpeg data")
    (tmp_path / "alias_test_notes.text").write_text("text data")
    (tmp_path / "alias_test_extra.logger").write_text("log data")

    manifest = TraceVerifier.sign_trace(str(trace_path))

    assert "alias_test_image.jpeg" in manifest["evidence_ledger"]
    assert "alias_test_notes.text" in manifest["evidence_ledger"]
    assert "alias_test_extra.logger" in manifest["evidence_ledger"]
