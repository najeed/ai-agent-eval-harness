import json
import zipfile
from pathlib import Path
from eval_runner.artifact_plugin import ArtifactPlugin


def test_calculate_sha256(tmp_path):
    """Test SHA-256 calculation for a sample file."""
    f = tmp_path / "test.txt"
    f.write_text("hello world")

    plugin = ArtifactPlugin()
    h = plugin._calculate_sha256(f)

    # Expected SHA-256 for "hello world"
    import hashlib

    expected = hashlib.sha256(b"hello world").hexdigest()
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
    with open(manifest_path, "r") as f:
        manifest = json.load(f)
        assert manifest["batch_id"] == tmp_path.name
        assert len(manifest["files"]) == 2
        assert manifest["files"][0]["name"] == "file1.txt"
        assert "sha256" in manifest["files"][0]


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
