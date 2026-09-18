import base64
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from agentv_runtime.canonical import canonical_json_encode
from eval_runner import config
from eval_runner.artifact_plugin import ArtifactPlugin
from eval_runner.identity import IdentityService


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
    """Verify that private key can be loaded from CORE_ARTIFACT_SIGNING_PEM environment variable."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    private_key = ed25519.Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    monkeypatch.setenv("CORE_ARTIFACT_SIGNING_PEM", pem)
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
    monkeypatch.delenv("CORE_ARTIFACT_SIGNING_PEM", raising=False)

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
    monkeypatch.setenv("CORE_ARTIFACT_SIGNING_PEM", "NOT_A_PRIVATE_KEY")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    with pytest.raises(
        RuntimeError, match="Failed to load signing key from CORE_ARTIFACT_SIGNING_PEM"
    ):
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


def test_artifact_plugin_on_discover_services():
    """Verify registration of bundle_artifacts and verify_integrity in service registry."""

    class DummyRegistry:
        def __init__(self):
            self.services = {}

        def register_service(self, name, fn):
            self.services[name] = fn

    plugin = ArtifactPlugin()
    registry = DummyRegistry()
    plugin.on_discover_services(registry)
    assert "bundle_artifacts" in registry.services
    assert "verify_integrity" in registry.services


def test_get_signing_key_priority3_persistent_file_fallback(tmp_path, monkeypatch):
    """Verify Priority 3 persistent key loading when IdentityService has no key."""
    monkeypatch.delenv("CORE_ARTIFACT_SIGNING_PEM", raising=False)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(IdentityService, "get_private_key", lambda *args, **kwargs: None)

    key_dir = tmp_path / ".aes" / "keys"
    key_dir.mkdir(parents=True)
    key_path = key_dir / "system_id.pem"

    priv = ed25519.Ed25519PrivateKey.generate()
    pem_bytes = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path.write_bytes(pem_bytes)

    plugin = ArtifactPlugin()
    loaded_key = plugin._get_signing_key()
    assert isinstance(loaded_key, ed25519.Ed25519PrivateKey)
    assert loaded_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ) == priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def test_verify_integrity_zip_bundle_missing_audit_manifest(tmp_path):
    """Verify error returned when zip bundle does not contain audit_manifest.json."""
    zip_path = tmp_path / "corrupt_bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("some_file.txt", "content")

    plugin = ArtifactPlugin()
    res = plugin.verify_integrity(str(zip_path))
    assert res["status"] == "error"
    assert res["message"] == "No audit_manifest.json in bundle"
    assert res["is_valid"] is False


def test_verify_integrity_zip_bundle_unsafe_path_and_missing_file(tmp_path):
    """Verify zip archive path traversal entries and missing files are flagged."""
    priv = ed25519.Ed25519PrivateKey.generate()
    manifest_data = {
        "files": [
            {"name": "../traversal.txt", "file_hash": "dummy"},
            {"name": "non_existent.txt", "file_hash": "dummy"},
        ],
        "signer_identity": "test_signer",
    }
    canonical_bytes = canonical_json_encode(manifest_data)
    manifest_data["signature_ed25519"] = base64.b64encode(priv.sign(canonical_bytes)).decode(
        "ascii"
    )

    zip_path = tmp_path / "unsafe_bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("audit_manifest.json", json.dumps(manifest_data))

    plugin = ArtifactPlugin()
    res = plugin.verify_integrity(str(zip_path), trusted_public_key=priv.public_key())
    assert res["is_valid"] is False
    assert res["status"] == "INVALID"
    status_map = {d["file"]: d["status"] for d in res["details"]}
    assert status_map["../traversal.txt"] == "unsafe_path"
    assert status_map["non_existent.txt"] == "missing"


def test_verify_integrity_missing_cryptographic_signature(tmp_path):
    """Verify UNVERIFIED status when manifest completely lacks signature_ed25519."""
    manifest_path = tmp_path / "unsigned_manifest.json"
    manifest_path.write_text(
        json.dumps({"files": [], "signer_identity": "tester"}), encoding="utf-8"
    )

    plugin = ArtifactPlugin()
    res = plugin.verify_integrity(str(manifest_path))
    assert res["is_valid"] is False
    assert res["status"] == "UNVERIFIED"
    assert res["message"] == "Manifest has no cryptographic signature"


def _create_signed_manifest_bundle(priv, signer_id="test_signer"):
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    manifest = {
        "files": [],
        "signer_identity": signer_id,
    }
    canonical = canonical_json_encode(manifest)
    manifest["signature_ed25519"] = base64.b64encode(priv.sign(canonical)).decode("ascii")
    manifest["public_key"] = base64.b64encode(pub_raw).decode("ascii")
    return manifest


def test_verify_integrity_trusted_public_key_formats(tmp_path):
    """Verify trusted_public_key accepts Ed25519PublicKey, str PEM, and bytes PEM."""
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_pem_bytes = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub_pem_str = pub_pem_bytes.decode("utf-8")

    manifest = _create_signed_manifest_bundle(priv)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    plugin = ArtifactPlugin()

    # Case 1: Ed25519PublicKey
    res1 = plugin.verify_integrity(str(manifest_path), trusted_public_key=pub)
    assert res1["is_valid"] is True
    assert res1["status"] == "VALID"

    # Case 2: str PEM
    res2 = plugin.verify_integrity(str(manifest_path), trusted_public_key=pub_pem_str)
    assert res2["is_valid"] is True
    assert res2["status"] == "VALID"

    # Case 3: bytes PEM
    res3 = plugin.verify_integrity(str(manifest_path), trusted_public_key=pub_pem_bytes)
    assert res3["is_valid"] is True
    assert res3["status"] == "VALID"


def test_verify_integrity_public_key_pem_formats(tmp_path):
    """Verify public_key_pem parameter accepts bytes and str."""
    priv = ed25519.Ed25519PrivateKey.generate()
    pub_pem_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    manifest = _create_signed_manifest_bundle(priv)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    plugin = ArtifactPlugin()
    res_bytes = plugin.verify_integrity(str(manifest_path), public_key_pem=pub_pem_bytes)
    assert res_bytes["is_valid"] is True

    res_str = plugin.verify_integrity(
        str(manifest_path), public_key_pem=pub_pem_bytes.decode("utf-8")
    )
    assert res_str["is_valid"] is True


def test_verify_integrity_key_registry_branches(tmp_path):
    """Verify key_registry resolution for signer_id, key_id, system_id, and unresolvable."""
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_pem_str = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    plugin = ArtifactPlugin()

    # Sub-case A: key_registry matches signer_id as Ed25519PublicKey
    m1 = _create_signed_manifest_bundle(priv, signer_id="signer_a")
    p1 = tmp_path / "m1.json"
    p1.write_text(json.dumps(m1), encoding="utf-8")
    res1 = plugin.verify_integrity(str(p1), key_registry={"signer_a": pub})
    assert res1["is_valid"] is True

    # Sub-case B: key_registry matches key_id as str PEM
    m2 = _create_signed_manifest_bundle(priv, signer_id="")
    m2["key_id"] = "kid_123"
    verify_part = {k: v for k, v in m2.items() if k not in ["signature_ed25519", "public_key"]}
    m2["signature_ed25519"] = base64.b64encode(
        priv.sign(canonical_json_encode(verify_part))
    ).decode("ascii")
    p2 = tmp_path / "m2.json"
    p2.write_text(json.dumps(m2), encoding="utf-8")
    res2 = plugin.verify_integrity(str(p2), key_registry={"kid_123": pub_pem_str})
    assert res2["is_valid"] is True

    # Sub-case C: key_registry matches system_id fallback
    m3 = _create_signed_manifest_bundle(priv, signer_id="")
    verify_part3 = {k: v for k, v in m3.items() if k not in ["signature_ed25519", "public_key"]}
    m3["signature_ed25519"] = base64.b64encode(
        priv.sign(canonical_json_encode(verify_part3))
    ).decode("ascii")
    p3 = tmp_path / "m3.json"
    p3.write_text(json.dumps(m3), encoding="utf-8")
    res3 = plugin.verify_integrity(str(p3), key_registry={"system_id": pub})
    assert res3["is_valid"] is True

    # Sub-case D: key_registry misses all -> UNVERIFIED
    res4 = plugin.verify_integrity(str(p1), key_registry={"other_signer": pub})
    assert res4["is_valid"] is False
    assert res4["status"] == "UNVERIFIED"


def test_verify_integrity_trust_root_branches(tmp_path):
    """Verify trust_root resolution via object method and directory paths."""
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_pem_bytes = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    manifest = _create_signed_manifest_bundle(priv, signer_id="trust_signer")
    m_path = tmp_path / "manifest.json"
    m_path.write_text(json.dumps(manifest), encoding="utf-8")

    plugin = ArtifactPlugin()

    # Sub-case A: trust_root object with get_public_key returning Ed25519PublicKey
    class TrustRootObjKey:
        def get_public_key(self, sid):
            return pub if sid == "trust_signer" else None

    res1 = plugin.verify_integrity(str(m_path), trust_root=TrustRootObjKey())
    assert res1["is_valid"] is True

    # Sub-case B: trust_root object returning PEM bytes
    class TrustRootObjBytes:
        def get_public_key(self, sid):
            return pub_pem_bytes if sid == "trust_signer" else None

    res2 = plugin.verify_integrity(str(m_path), trust_root=TrustRootObjBytes())
    assert res2["is_valid"] is True

    # Sub-case C: trust_root directory path with signer_id/public_key.pem
    trust_dir1 = tmp_path / "trust_root1"
    sub_dir = trust_dir1 / "trust_signer"
    sub_dir.mkdir(parents=True)
    (sub_dir / "public_key.pem").write_bytes(pub_pem_bytes)

    res3 = plugin.verify_integrity(str(m_path), trust_root=trust_dir1)
    assert res3["is_valid"] is True

    # Sub-case D: trust_root directory path with {signer_id}_public.pem
    trust_dir2 = tmp_path / "trust_root2"
    trust_dir2.mkdir(parents=True)
    (trust_dir2 / "trust_signer_public.pem").write_bytes(pub_pem_bytes)

    res4 = plugin.verify_integrity(str(m_path), trust_root=trust_dir2)
    assert res4["is_valid"] is True


def test_verify_integrity_candidate_trust_root_discovery(tmp_path, monkeypatch):
    """Verify fallback discovery in candidate paths when IdentityService raises error."""
    priv = ed25519.Ed25519PrivateKey.generate()
    pub_pem_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    manifest = _create_signed_manifest_bundle(priv, signer_id="candidate_signer")
    m_path = tmp_path / "manifest.json"
    m_path.write_text(json.dumps(manifest), encoding="utf-8")

    def _raise_error(*args, **kwargs):
        raise OSError("Identity backend unavailable")

    monkeypatch.setattr(IdentityService, "get_public_key", _raise_error)

    # Place candidate in config.TRUST_ROOT
    trust_root_dir = tmp_path / "trust_root"
    trust_root_dir.mkdir()
    (trust_root_dir / "candidate_signer_public.pem").write_bytes(pub_pem_bytes)
    monkeypatch.setattr(config, "TRUST_ROOT", trust_root_dir)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path / "empty_project")

    plugin = ArtifactPlugin()
    res = plugin.verify_integrity(str(m_path))
    assert res["is_valid"] is True
    assert res["status"] == "VALID"

    # Test corrupted candidate key handling with recovery from PROJECT_ROOT/.aes/keys/
    corrupt_trust_dir = tmp_path / "corrupt_trust"
    corrupt_trust_dir.mkdir()
    (corrupt_trust_dir / "candidate_signer_public.pem").write_text(
        "NOT_VALID_PEM", encoding="utf-8"
    )
    monkeypatch.setattr(config, "TRUST_ROOT", corrupt_trust_dir)

    keys_dir = tmp_path / "proj" / ".aes" / "keys"
    keys_dir.mkdir(parents=True)
    (keys_dir / "candidate_signer_public.pem").write_bytes(pub_pem_bytes)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path / "proj")

    res_recovered = plugin.verify_integrity(str(m_path))
    assert res_recovered["is_valid"] is True
    assert res_recovered["status"] == "VALID"


def test_verify_integrity_embedded_public_key_mismatch_and_malformed(tmp_path):
    """Verify detection of embedded public key mismatch or malformed base64."""
    priv = ed25519.Ed25519PrivateKey.generate()
    other_priv = ed25519.Ed25519PrivateKey.generate()
    other_pub_raw = other_priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    manifest_mismatch = _create_signed_manifest_bundle(priv, signer_id="mismatch_signer")
    manifest_mismatch["public_key"] = base64.b64encode(other_pub_raw).decode("ascii")
    p1 = tmp_path / "mismatch.json"
    p1.write_text(json.dumps(manifest_mismatch), encoding="utf-8")

    plugin = ArtifactPlugin()
    res1 = plugin.verify_integrity(str(p1), trusted_public_key=priv.public_key())
    assert res1["is_valid"] is False
    assert res1["status"] == "UNVERIFIED"
    assert (
        "Embedded public key does not match authoritative external trust anchor" in res1["message"]
    )

    manifest_malformed = _create_signed_manifest_bundle(priv, signer_id="malformed_signer")
    manifest_malformed["public_key"] = 12345
    p2 = tmp_path / "malformed.json"
    p2.write_text(json.dumps(manifest_malformed), encoding="utf-8")

    res2 = plugin.verify_integrity(str(p2), trusted_public_key=priv.public_key())
    assert res2["is_valid"] is False
    assert res2["status"] == "UNVERIFIED"
    assert "Malformed embedded public key" in res2["message"]
