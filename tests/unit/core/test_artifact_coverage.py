import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from eval_runner import config
from eval_runner.artifact_plugin import ArtifactPlugin


@pytest.fixture
def plugin():
    return ArtifactPlugin()


def test_get_signing_key_auto_generate(plugin, tmp_path, monkeypatch):
    """Verify that a new key is generated if none exists."""
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    # Path where key will be generated
    key_path = tmp_path / ".aes" / "keys" / "system_id.pem"
    assert not key_path.exists()

    key = plugin._get_signing_key()
    assert isinstance(key, ed25519.Ed25519PrivateKey)
    assert key_path.exists()


def test_bundle_artifacts_missing_file_handling(plugin, tmp_path):
    """Verify that bundling continues if a requested file is missing."""
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()

    # Create one valid file
    (bundle_dir / "valid.txt").write_text("content")

    # Inclusion list with a missing file
    files = ["valid.txt", "missing.txt"]

    res = plugin.bundle_artifacts(str(bundle_dir), files, generate_manifest=True)

    assert res["status"] == "success"

    # Check manifest
    with open(res["manifest_path"]) as f:
        manifest = json.load(f)

    # Only the valid file should be in the manifest
    assert len(manifest["files"]) == 1
    assert manifest["files"][0]["name"] == "valid.txt"


def test_verify_integrity_manifest_not_found(plugin, tmp_path):
    """Verify error behavior when manifest is missing."""
    res = plugin.verify_integrity(str(tmp_path / "non_existent.json"))
    assert res["status"] == "error"
    assert "Manifest not found" in res["message"]


def test_verify_integrity_mismatch_and_missing_files(plugin, tmp_path):
    """Verify integrity failure when files are modified or missing."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    # 1. Create original files and bundle to generate manifest
    (work_dir / "file1.txt").write_text("data1")
    (work_dir / "file2.txt").write_text("data2")

    res = plugin.bundle_artifacts(str(work_dir), ["file1.txt", "file2.txt"])
    manifest_path = res["manifest_path"]

    # 2. Corrupt file1
    (work_dir / "file1.txt").write_text("CORRUPTED")

    # 3. Delete file2
    (work_dir / "file2.txt").unlink()

    # 4. Verify
    verify_res = plugin.verify_integrity(manifest_path)
    assert verify_res["is_valid"] is False

    details = {d["file"]: d["status"] for d in verify_res["details"]}
    assert details["file1.txt"] == "mismatch"
    assert details["file2.txt"] == "missing"


def test_verify_integrity_signature_failure(plugin, tmp_path):
    """Verify that integrity check fails if signature is corrupted."""
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "test.txt").write_text("test")

    res = plugin.bundle_artifacts(str(work_dir), ["test.txt"])
    manifest_path = Path(res["manifest_path"])

    # Corrupt the signature in the manifest
    with open(manifest_path) as f:
        manifest = json.load(f)

    manifest["signature_ed25519"] = ""  # Empty signature

    with open(manifest_path, "w") as f:
        json.dump(manifest, f)

    verify_res = plugin.verify_integrity(str(manifest_path))
    assert verify_res["is_valid"] is False


def test_get_signing_key_invalid_env(plugin, tmp_path, monkeypatch):
    """Verify fallback behavior when env key is malformed."""
    monkeypatch.setenv("AES_PRIVATE_KEY", "NOT_A_PRIVATE_KEY")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    # Should log warning and generate/load file key
    key = plugin._get_signing_key()
    assert isinstance(key, ed25519.Ed25519PrivateKey)
