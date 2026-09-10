import json
import zipfile
from pathlib import Path

import pytest

from eval_runner.artifact_plugin import ArtifactPlugin


def test_calculate_hash(tmp_path):
    """Test SHA3-256 calculation for a sample file."""
    f = tmp_path / "test.txt"
    f.write_text("hello world")

    plugin = ArtifactPlugin()
    h = plugin._calculate_hash(f)

    # Expected SHA3-256 for "hello world"
    from eval_runner.utils import crypto

    expected = crypto.file_hash(f)
    assert h == expected


def test_bundle_artifacts(tmp_path):
    """Test bundling multiple files into a ZIP with a manifest."""
    # Setup files
    file1 = tmp_path / "file1.txt"
    file1.write_text("content1")
    file2 = tmp_path / "file2.txt"
    file2.write_text("content2")

    plugin = ArtifactPlugin()
    result = plugin.bundle_artifacts(
        target_dir=str(tmp_path),
        files_to_include=["file1.txt", "file2.txt"],
        output_filename="test_bundle.zip",
        generate_manifest=True,
    )

    assert result["status"] == "success"
    zip_path = Path(result["bundle_path"])
    manifest_path = Path(result["manifest_path"])

    assert zip_path.exists()
    assert manifest_path.exists()

    # Verify ZIP content
    with zipfile.ZipFile(zip_path, "r") as z:
        assert "file1.txt" in z.namelist()
        assert "file2.txt" in z.namelist()

    # Verify manifest content
    with open(manifest_path) as f:
        manifest = json.load(f)
        assert manifest["batch_id"] == tmp_path.name
        assert len(manifest["files"]) == 2
        assert manifest["files"][0]["name"] == "file1.txt"
        assert "file_hash" in manifest["files"][0]


def test_verify_integrity_valid(tmp_path):
    """Test integrity verification for untampered files."""
    f = tmp_path / "valid.txt"
    f.write_text("legit data")

    plugin = ArtifactPlugin()
    bundle_res = plugin.bundle_artifacts(
        target_dir=str(tmp_path), files_to_include=["valid.txt"], generate_manifest=True
    )

    verify_res = plugin.verify_integrity(bundle_res["manifest_path"])
    assert verify_res["is_valid"] is True
    assert verify_res["details"][0]["status"] == "valid"


def test_verify_integrity_tampered(tmp_path):
    """Test integrity verification for tampered files."""
    f = tmp_path / "secret.txt"
    f.write_text("original content")

    plugin = ArtifactPlugin()
    bundle_res = plugin.bundle_artifacts(
        target_dir=str(tmp_path), files_to_include=["secret.txt"], generate_manifest=True
    )

    # Tamper with the file
    f.write_text("HACKED!")

    verify_res = plugin.verify_integrity(bundle_res["manifest_path"])
    assert verify_res["is_valid"] is False
    assert verify_res["details"][0]["status"] == "mismatch"


def test_verify_integrity_missing_file(tmp_path):
    """Test integrity verification when a file is missing."""
    f = tmp_path / "gone.txt"
    f.write_text("temporary")

    plugin = ArtifactPlugin()
    bundle_res = plugin.bundle_artifacts(
        target_dir=str(tmp_path), files_to_include=["gone.txt"], generate_manifest=True
    )

    # Delete the file
    f.unlink()

    verify_res = plugin.verify_integrity(bundle_res["manifest_path"])
    assert verify_res["is_valid"] is False
    assert verify_res["details"][0]["status"] == "missing"


def test_verify_integrity_non_existent_manifest():
    """Test verification when manifest file doesn't exist."""
    plugin = ArtifactPlugin()
    result = plugin.verify_integrity("non_existent_manifest.json")
    assert result["status"] == "error"
    assert "not found" in result["message"]


def test_get_signing_key_from_env(monkeypatch):
    """Verify that private key can be loaded from AES_PRIVATE_KEY environment variable."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    private_key = ed25519.Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    monkeypatch.setenv("AES_PRIVATE_KEY", pem)
    plugin = ArtifactPlugin()
    key = plugin._get_signing_key()
    assert isinstance(key, ed25519.Ed25519PrivateKey)


def test_get_signing_key_from_file(tmp_path, monkeypatch):
    """Verify that private key can be loaded from persistent file."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    from eval_runner import config

    # Mock project root to point to tmp_path
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    key_dir = tmp_path / ".aes" / "keys"
    key_dir.mkdir(parents=True)
    key_path = key_dir / "system_id.pem"

    private_key = ed25519.Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path.write_bytes(pem)

    plugin = ArtifactPlugin()
    key = plugin._get_signing_key()
    assert isinstance(key, ed25519.Ed25519PrivateKey)


def test_verify_integrity_signature_failure(tmp_path):
    """Verify that tampering with the signature results in invalid integrity."""
    f = tmp_path / "data.txt"
    f.write_text("secure data")

    plugin = ArtifactPlugin()
    res = plugin.bundle_artifacts(str(tmp_path), ["data.txt"], generate_manifest=True)

    manifest_path = Path(res["manifest_path"])
    with open(manifest_path) as mf:
        manifest = json.load(mf)

    # Tamper with signature
    manifest["signature_ed25519"] = ""
    with open(manifest_path, "w") as mf:
        json.dump(manifest, mf)

    verify_res = plugin.verify_integrity(str(manifest_path))
    assert verify_res["is_valid"] is False


def test_get_signing_key_no_auto_generation(tmp_path, monkeypatch):
    """Verify that auto-generation is prohibited when no key exists."""
    from eval_runner import config

    plugin = ArtifactPlugin()
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "TRUST_ROOT", tmp_path / "nonexistent_trust")
    monkeypatch.delenv("AES_PRIVATE_KEY", raising=False)

    key_path = tmp_path / ".aes" / "keys" / "system_id.pem"
    assert not key_path.exists()

    with pytest.raises(RuntimeError, match="Self-generated unanchored signing keys are prohibited"):
        plugin._get_signing_key()

    assert not key_path.exists()


def test_bundle_artifacts_missing_file_handling(tmp_path):
    """Verify that bundling continues if a requested file is missing."""
    plugin = ArtifactPlugin()
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()

    (bundle_dir / "valid.txt").write_text("content")

    files = ["valid.txt", "missing.txt"]
    res = plugin.bundle_artifacts(str(bundle_dir), files, generate_manifest=True)
    assert res["status"] == "success"

    with open(res["manifest_path"]) as f:
        manifest = json.load(f)

    assert len(manifest["files"]) == 1
    assert manifest["files"][0]["name"] == "valid.txt"


def test_verify_integrity_manifest_not_found(tmp_path):
    """Verify error behavior when manifest is missing."""
    plugin = ArtifactPlugin()
    res = plugin.verify_integrity(str(tmp_path / "non_existent.json"))
    assert res["status"] == "error"
    assert "Manifest not found" in res["message"]


def test_verify_integrity_mismatch_and_missing_files(tmp_path):
    """Verify integrity failure when files are modified or missing."""
    plugin = ArtifactPlugin()
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    (work_dir / "file1.txt").write_text("data1")
    (work_dir / "file2.txt").write_text("data2")

    res = plugin.bundle_artifacts(str(work_dir), ["file1.txt", "file2.txt"])
    manifest_path = res["manifest_path"]

    (work_dir / "file1.txt").write_text("CORRUPTED")
    (work_dir / "file2.txt").unlink()

    verify_res = plugin.verify_integrity(manifest_path)
    assert verify_res["is_valid"] is False

    details = {d["file"]: d["status"] for d in verify_res["details"]}
    assert details["file1.txt"] == "mismatch"
    assert details["file2.txt"] == "missing"


def test_get_signing_key_invalid_env(tmp_path, monkeypatch):
    """Verify fail-closed error behavior when env key is malformed (no auto-generation fallback)."""
    from eval_runner import config

    plugin = ArtifactPlugin()
    monkeypatch.setenv("AES_PRIVATE_KEY", "NOT_A_PRIVATE_KEY")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    with pytest.raises(RuntimeError, match="Failed to load signing key from AES_PRIVATE_KEY"):
        plugin._get_signing_key()


def test_verify_integrity_requires_external_trust_anchor(tmp_path, monkeypatch):
    """Defect 3: Missing external trust anchor must result in UNVERIFIED, never valid."""
    from eval_runner import config

    plugin = ArtifactPlugin()
    f = tmp_path / "data.txt"
    f.write_text("certified payload")

    res = plugin.bundle_artifacts(str(tmp_path), ["data.txt"])

    # Isolate trust root so no system_id key is found
    empty_trust = tmp_path / "empty_trust"
    empty_trust.mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path / "empty_root")
    monkeypatch.setattr(config, "TRUST_ROOT", empty_trust)
    monkeypatch.delenv("AES_PUBLIC_KEY_SYSTEM_ID", raising=False)
    monkeypatch.delenv("AES_PUBLIC_KEY", raising=False)

    verify_res = plugin.verify_integrity(res["manifest_path"])
    assert verify_res["is_valid"] is False
    assert verify_res["status"] == "UNVERIFIED"
    assert "No external trust anchor found" in verify_res["message"]


def test_verify_integrity_zip_bundle_internal_bytes(tmp_path):
    """Defect 4: ZIP verification must hash archive entries directly, ignoring adjacent files."""
    plugin = ArtifactPlugin()
    f = tmp_path / "file.txt"
    f.write_text("zip payload")

    res = plugin.bundle_artifacts(str(tmp_path), ["file.txt"])
    zip_path = res["bundle_path"]

    # Delete adjacent filesystem file: ZIP verification must still succeed
    f.unlink()
    assert not f.exists()

    verify_res = plugin.verify_integrity(zip_path)
    assert verify_res["is_valid"] is True
    assert verify_res["status"] == "VALID"
    assert verify_res["details"][0]["status"] == "valid"


def test_verify_integrity_rejects_unsafe_paths(tmp_path):
    """Defect 4: Reject path traversal entries (.. or absolute paths)."""
    manifest_path = tmp_path / "audit_manifest.json"
    manifest = {
        "version": "1.0",
        "timestamp": "2026-09-07T00:00:00",
        "batch_id": "test",
        "files": [
            {"name": "../etc/passwd", "file_hash": "abc"},
            {"name": "/absolute/path", "file_hash": "def"},
        ],
    }
    manifest_path.write_text(json.dumps(manifest))

    plugin = ArtifactPlugin()
    verify_res = plugin.verify_integrity(str(manifest_path))
    assert verify_res["is_valid"] is False
    assert verify_res["status"] == "INVALID"
    for detail in verify_res["details"]:
        assert detail["status"] == "unsafe_path"


def test_verify_integrity_zip_tampered_internal_bytes_detected(tmp_path):
    """Corrupting bytes inside a ZIP archive is detected directly from archive streams."""
    import io
    import zipfile

    plugin = ArtifactPlugin()
    f1 = tmp_path / "item.txt"
    f1.write_text("safe content", encoding="utf-8")

    bundle_res = plugin.bundle_artifacts(str(tmp_path), ["item.txt"])
    zip_path = Path(bundle_res["bundle_path"])

    buf = io.BytesIO()
    with zipfile.ZipFile(zip_path, "r") as zf_in:
        with zipfile.ZipFile(buf, "w") as zf_out:
            for item in zf_in.infolist():
                if item.filename == "item.txt":
                    zf_out.writestr(item, "corrupted content")
                else:
                    zf_out.writestr(item, zf_in.read(item.filename))

    tampered_zip = tmp_path / "tampered.zip"
    tampered_zip.write_bytes(buf.getvalue())

    res_tampered = plugin.verify_integrity(str(tampered_zip))
    assert res_tampered["is_valid"] is False
    assert res_tampered["status"] == "INVALID"
    assert any(d["status"] == "mismatch" for d in res_tampered["details"])
