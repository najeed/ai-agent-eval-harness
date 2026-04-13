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


@pytest.fixture(autouse=True)
def vault_context(tmp_path, monkeypatch):
    """Isolate RUN_LOG_DIR to the temporary test path."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("eval_runner.config.RUN_LOG_DIR", runs_dir)
    return runs_dir


def setup_vault(runs_dir, run_id, trace_name="run.jsonl"):
    """
    Industrial Helper: Scaffolds a forensic vault for testing.
    This ensures zero-pollution by keeping the Run ID isolated in a named container.
    """
    vault_dir = runs_dir / run_id
    vault_dir.mkdir(parents=True, exist_ok=True)
    trace_path = vault_dir / trace_name
    return vault_dir, trace_path


def test_v3_manifest_generation(isolated_trust, vault_context):
    """Verify VC v3 manifest compliance and schema using the Vault Standard."""
    run_id = "run-gen-v3"
    vault_dir, trace_path = setup_vault(vault_context, run_id)
    trace_path.write_text("event1\nevent2")

    # Create sidecar artifacts (Inside the vault to satisfy Namespace Affinity)
    (vault_dir / "terminal.log").write_text("terminal output")
    (vault_dir / "db.sqlite").write_text("database bytes")

    manifest = TraceVerifier.sign_trace(
        str(trace_path),
        run_id=run_id,
        identity_id="test_auditor",
        compliance_status="pass",
        compliance_score=0.98,
        policy_ref="SOC2-T1",
    )

    # Check v3 fields and ID integrity
    assert manifest["vc_version"] == "3.0.0"
    assert manifest["run_id"] == run_id  # ENSURE ZERO POLLUTION (No tmp paths in ID)
    assert manifest["compliance"]["status"] == "pass"
    assert manifest["compliance"]["score"] == 0.98

    # Forensic Discovery: Inside a dedicated vault, filenames are sufficient
    assert "terminal.log" in manifest["evidence_ledger"]
    assert "db.sqlite" in manifest["evidence_ledger"]
    assert manifest["trace_file"] == "run.jsonl"

    # Check provenance
    assert len(manifest["provenance_chain"]) == 1
    assert manifest["provenance_chain"][0]["identity"] == "test_auditor"


def test_v3_signature_verification(isolated_trust, vault_context):
    """Verify that v3 signatures are deterministic and verifiable within a vault."""
    run_id = "run-sign-v3"
    vault_dir, trace_path = setup_vault(vault_context, run_id, trace_name="run.jsonl")
    trace_path.write_text("content")

    _manifest = TraceVerifier.sign_trace(str(trace_path), run_id=run_id, identity_id="signer_id")
    manifest_path = vault_dir / "run_manifest.json"

    # Verify
    is_valid = TraceVerifier.verify_trace(str(trace_path), str(manifest_path))
    assert is_valid is True


def test_v3_tamper_detection(isolated_trust, vault_context):
    """Verify that tampering with any part of the forensic vault package fails verification."""
    run_id = "run-secure-v3"
    vault_dir, trace_path = setup_vault(vault_context, run_id)
    trace_path.write_text("baseline")
    (vault_dir / "evidence.txt").write_text("raw evidence")

    _manifest = TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
    manifest_path = vault_dir / "run_manifest.json"

    # 1. Tamper with trace
    trace_path.write_text("modified")
    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is False
    trace_path.write_text("baseline")  # Restore

    # 2. Tamper with evidence (ledger check enabled)
    (vault_dir / "evidence.txt").write_text("modified evidence")
    assert (
        TraceVerifier.verify_trace(str(trace_path), str(manifest_path), verify_ledger=True) is False
    )


def test_v3_governance_ttl(isolated_trust, vault_context):
    """Verify that expired certificates fail verification."""
    run_id = "run-ttl-v3"
    vault_dir, trace_path = setup_vault(vault_context, run_id)
    trace_path.write_text("data")

    # Certify with -1 day TTL (expired)
    _manifest = TraceVerifier.sign_trace(str(trace_path), run_id=run_id, ttl_days=-1)
    manifest_path = vault_dir / "run_manifest.json"

    assert TraceVerifier.verify_trace(str(trace_path), str(manifest_path)) is False


def test_v3_forensic_relevance_bypass(isolated_trust, vault_context, monkeypatch):
    """Verify that mandatory patterns bypass the forensic size quota within a vault."""
    run_id = "run-bypass-v3"
    vault_dir, trace_path = setup_vault(vault_context, run_id)
    trace_path.write_text("trace content")

    # 1. Create a large DB file (6MB) -> Exceeds default 5MB limit
    large_db = vault_dir / "heavy.db"
    with open(large_db, "wb") as f:
        f.write(b"0" * (6 * 1024 * 1024))

    # Standard sign (Should exclude large_db by default)
    manifest_default = TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
    assert "heavy.db" not in manifest_default["evidence_ledger"]

    # 2. Add pattern to mandatory list via monkeypatch
    monkeypatch.setenv("FORENSIC_MANDATORY_PATTERNS", "heavy.*")

    # RELOAD REGISTRY to see new env var
    from eval_runner.config import RegistryManager

    RegistryManager.reload()

    # Sign again with bypass (Should include heavy.db now)
    manifest_bypass = TraceVerifier.sign_trace(str(trace_path), run_id=run_id)
    assert "heavy.db" in manifest_bypass["evidence_ledger"]


def test_v3_forensic_tier1_inclusion(isolated_trust, vault_context):
    """Verify that any file in the forensics/ directory is unconditionally included."""
    run_id = "run-tier1-v3"
    vault_dir, trace_path = setup_vault(vault_context, run_id)
    trace_path.write_text("trace")

    forensics_dir = vault_dir / "forensics"
    forensics_dir.mkdir()

    # 1. Forensic file with unauthorized extension (.exe)
    junk_binary = forensics_dir / "suspect.exe"
    junk_binary.write_text("malicious content")

    # 2. Forensic file that is huge (10MB)
    huge_log = forensics_dir / "massive.log"
    with open(huge_log, "wb") as f:
        f.write(b"L" * (10 * 1024 * 1024))

    manifest = TraceVerifier.sign_trace(str(trace_path), run_id=run_id)

    # Both MUST be included because they are in forensics/ (Tier 1)
    assert "forensics/suspect.exe" in manifest["evidence_ledger"]
    assert "forensics/massive.log" in manifest["evidence_ledger"]


def test_v3_forensic_exclusion_filtering(isolated_trust, vault_context):
    """Verify that EXCLUSION_PATTERNS correctly drop platform junk."""
    run_id = "run-exclude-v3"
    vault_dir, trace_path = setup_vault(vault_context, run_id)
    trace_path.write_text("trace")

    # Allowed extension (.log) but matches exclusion pattern (.*\.node$)
    node_log = vault_dir / "addon.node"
    node_log.write_text("binary data")

    # Allowed extension (.json) but matches exclusion pattern (.*\.cache$)
    cache_file = vault_dir / "meta.cache"
    cache_file.write_text("{}")

    manifest = TraceVerifier.sign_trace(str(trace_path), run_id=run_id)

    # Both MUST be excluded
    assert "addon.node" not in manifest["evidence_ledger"]
    assert "meta.cache" not in manifest["evidence_ledger"]


def test_v3_forensic_extension_filtering(isolated_trust, vault_context):
    """Verify that only allowed enterprise extensions are collected."""
    run_id = "run-ext-v3"
    vault_dir, trace_path = setup_vault(vault_context, run_id)
    trace_path.write_text("trace")

    (vault_dir / "data.parquet").write_text("parquet data")
    (vault_dir / "config.yaml").write_text("yaml content")
    (vault_dir / "legacy.doc").write_text("doc")  # Not in allowed list

    manifest = TraceVerifier.sign_trace(str(trace_path), run_id=run_id)

    assert "data.parquet" in manifest["evidence_ledger"]
    assert "config.yaml" in manifest["evidence_ledger"]
    assert "legacy.doc" not in manifest["evidence_ledger"]


def test_v3_forensic_alias_normalization(isolated_trust, vault_context):
    """Verify that .jpeg matches .jpg, .text matches .txt, etc."""
    run_id = "run-alias-v3"
    vault_dir, trace_path = setup_vault(vault_context, run_id)
    trace_path.write_text("trace")

    # We allow .jpg and .txt by default
    (vault_dir / "image.jpeg").write_text("jpeg data")
    (vault_dir / "notes.text").write_text("text data")
    (vault_dir / "extra.logger").write_text("log data")

    manifest = TraceVerifier.sign_trace(str(trace_path), run_id=run_id)

    assert "image.jpeg" in manifest["evidence_ledger"]
    assert "notes.text" in manifest["evidence_ledger"]
    assert "extra.logger" in manifest["evidence_ledger"]
