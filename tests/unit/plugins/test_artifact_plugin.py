import json
import zipfile
from pathlib import Path

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


def test_get_signing_key_auto_generate(tmp_path, monkeypatch):
    """Verify that a new key is generated if none exists."""
    from cryptography.hazmat.primitives.asymmetric import ed25519

    from eval_runner import config

    plugin = ArtifactPlugin()
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    key_path = tmp_path / ".aes" / "keys" / "system_id.pem"
    assert not key_path.exists()

    key = plugin._get_signing_key()
    assert isinstance(key, ed25519.Ed25519PrivateKey)
    assert key_path.exists()


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
    """Verify fallback behavior when env key is malformed."""
    from cryptography.hazmat.primitives.asymmetric import ed25519

    from eval_runner import config

    plugin = ArtifactPlugin()
    monkeypatch.setenv("AES_PRIVATE_KEY", "NOT_A_PRIVATE_KEY")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    key = plugin._get_signing_key()
    assert isinstance(key, ed25519.Ed25519PrivateKey)
