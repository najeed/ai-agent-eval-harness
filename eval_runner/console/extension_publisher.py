"""Configured, server-side publishing for signed Runtime ESM extensions."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import uuid
from collections.abc import Callable
from datetime import UTC
from pathlib import Path

from agentv_runtime.extension_contract import RuntimeExtension
from eval_runner import config
from eval_runner.reference.signing import LocalEd25519SigningBackend

_IMPORT_RE = re.compile(
    r"(?:import|export)\s+(?:[^'\"]+?\s+from\s+)?['\"]([^'\"]+)['\"]|"
    r"import\(\s*['\"]([^'\"]+)['\"]\s*\)"
)


def _sri(data: bytes) -> str:
    return "sha3-256-" + base64.b64encode(hashlib.sha3_256(data).digest()).decode("ascii")


def _active_record_path(root: Path, publisher: str, extension_id: str) -> Path:
    return root / ".active-releases" / publisher / f"{extension_id}.json"


def _record_path(root: Path, extension_id: str, version: str) -> Path:
    return root / ".release-records" / extension_id / f"{version}.manifest.json"


def _descriptor(manifest: RuntimeExtension) -> dict:
    return {
        "remoteEntry": manifest.remote_entry,
        "sriHash": manifest.sri_hash,
        "manifest": manifest.to_dict(),
    }


def _relative_chunks(entry: Path) -> list[Path]:
    """Discover the local relative static-import graph without following escapes."""
    root = entry.parent.resolve()
    discovered: list[Path] = []
    pending = [entry.resolve()]
    seen = {entry.resolve()}
    while pending:
        current = pending.pop()
        source = current.read_text(encoding="utf-8")
        for match in _IMPORT_RE.findall(source):
            ref = match[0] or match[1]
            if not ref.startswith("."):
                continue
            child = (current.parent / ref).resolve()
            if child.suffix == "":
                child = child.with_suffix(".js")
            if not child.is_file() or root not in child.parents and child != root:
                raise ValueError(f"Extension import is not a local publishable chunk: {ref!r}")
            if child not in seen:
                seen.add(child)
                discovered.append(child)
                pending.append(child)
    return discovered


def publish_extension(
    *,
    entry: Path,
    extension_id: str,
    publisher: str,
    version: str,
    private_key_pem: Callable[[str], bytes],
    artifact_root: Path | None = None,
    manifest_declaration: dict | None = None,
    activate: bool = False,
) -> dict:
    """Sign and atomically publish an ESM bundle to the configured local store."""
    entry = entry.resolve()
    if not entry.is_file():
        raise ValueError("entry must name a readable ESM file")
    if not extension_id or "/" in extension_id or "\\" in extension_id or ".." in extension_id:
        raise ValueError("extension_id must be a single safe identifier")
    root = (artifact_root or config.EXTENSION_ARTIFACT_DIR).resolve()
    target = root / extension_id / version
    staging = root / ".staging" / uuid.uuid4().hex
    staging.mkdir(parents=True, exist_ok=False)
    try:
        chunks = _relative_chunks(entry)
        entry_name = "entry" + entry.suffix
        entry_bytes = entry.read_bytes()
        (staging / entry_name).write_bytes(entry_bytes)
        verified_chunks: dict[str, str] = {}
        for chunk in chunks:
            relative = chunk.relative_to(entry.parent).as_posix()
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            data = chunk.read_bytes()
            destination.write_bytes(data)
            verified_chunks["./" + relative] = _sri(data)
        remote_entry = f"/extensions/{extension_id}/{version}/{entry_name}"
        declared = dict(manifest_declaration or {})
        for name, expected in (
            ("extension_id", extension_id),
            ("version", version),
            ("publisher", publisher),
        ):
            if name in declared and declared[name] != expected:
                raise ValueError(f"manifest {name} must match the publish argument")
        declared.update(
            {
                "extension_id": extension_id,
                "version": version,
                "publisher": publisher,
                "remote_entry": remote_entry,
                "sri_hash": _sri(entry_bytes),
                "verified_chunks": verified_chunks,
                "signature": "",
            }
        )
        if not manifest_declaration:
            declared.update(
                {
                    "display_name": extension_id,
                    "capabilities": ["header"],
                    "required_permissions": [],
                    "routes": [],
                    "nav_group": "extensions",
                    "host_apis": [],
                    "slot": "header",
                    "react_peer": True,
                }
            )
        manifest = RuntimeExtension.from_dict(declared)
        violations = manifest.validate(require_signature=False)
        if violations:
            raise ValueError("; ".join(violations))
        signature = LocalEd25519SigningBackend().sign_payload(
            manifest.canonical_bytes(), private_key_pem(publisher)
        )
        signed = RuntimeExtension(**{**manifest.to_dict(), "signature": signature})
        (staging / "entry.manifest.json").write_text(
            json.dumps(signed.to_dict(), sort_keys=True), encoding="utf-8"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            existing_files = sorted(
                path.relative_to(target) for path in target.rglob("*") if path.is_file()
            )
            staged_files = sorted(
                path.relative_to(staging) for path in staging.rglob("*") if path.is_file()
            )
            if existing_files == staged_files and all(
                (target / item).read_bytes() == (staging / item).read_bytes()
                for item in staged_files
            ):
                shutil.rmtree(staging)
                desc = _descriptor(
                    RuntimeExtension.from_dict(
                        json.loads((target / "entry.manifest.json").read_text(encoding="utf-8"))
                    )
                )
                if activate:
                    active_info = activate_extension(
                        extension_id=extension_id,
                        version=version,
                        publisher=publisher,
                        artifact_root=root,
                    )
                    desc["active"] = True
                    desc["active_record"] = active_info.get("active_record")
                return desc
            raise ValueError(
                "extension version already published with different bytes; publish a new version"
            )
        os.replace(staging, target)
        record = _record_path(root, extension_id, version)
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps(signed.to_dict(), sort_keys=True), encoding="utf-8")
        desc = _descriptor(signed)
        if activate:
            active_info = activate_extension(
                extension_id=extension_id,
                version=version,
                publisher=publisher,
                artifact_root=root,
            )
            desc["active"] = True
            desc["active_record"] = active_info.get("active_record")
        return desc
    except (OSError, ValueError):
        shutil.rmtree(staging, ignore_errors=True)
        raise


def unpublish_extension(
    *, extension_id: str, version: str, artifact_root: Path | None = None
) -> dict:
    """Atomically withdraw a release; repeated withdrawal is a safe no-op."""
    root = (artifact_root or config.EXTENSION_ARTIFACT_DIR).resolve()
    target = root / extension_id / version
    if not target.exists():
        return {"status": "not_found", "extension_id": extension_id, "version": version}
    quarantine = root / ".quarantine" / f"{extension_id}-{version}-{uuid.uuid4().hex}"
    quarantine.parent.mkdir(parents=True, exist_ok=True)
    os.replace(target, quarantine)
    shutil.rmtree(quarantine)

    active_dir = root / ".active-releases"
    if active_dir.is_dir():
        for rec in active_dir.glob(f"*/{extension_id}.json"):
            try:
                data = json.loads(rec.read_text(encoding="utf-8"))
                if data.get("version") == version:
                    rec.unlink(missing_ok=True)
            except (OSError, json.JSONDecodeError):
                pass

    return {"status": "unpublished", "extension_id": extension_id, "version": version}


def activate_extension(
    *,
    extension_id: str,
    version: str,
    publisher: str | None = None,
    public_key_pem: Callable[[str], bytes | None] | None = None,
    artifact_root: Path | None = None,
) -> dict:
    """Atomically activate an installed, verified extension release."""
    from datetime import datetime

    if not extension_id or "/" in extension_id or "\\" in extension_id or ".." in extension_id:
        raise ValueError("extension_id must be a single safe identifier")
    if not version or "/" in version or "\\" in version or ".." in version:
        raise ValueError("version must be a single safe identifier")
    root = (artifact_root or config.EXTENSION_ARTIFACT_DIR).resolve()
    target = root / extension_id / version
    if not target.is_dir():
        raise ValueError(f"Extension '{extension_id}' version '{version}' is not installed")

    if public_key_pem is None:
        from .routes.trust import _public_key_pem_bytes

        public_key_pem = _public_key_pem_bytes

    verification = verify_extension(
        extension_id=extension_id,
        version=version,
        public_key_pem=public_key_pem,
        artifact_root=root,
    )
    if not verification.get("valid"):
        reason = verification.get("reason", "unknown")
        raise ValueError(f"Activation failed: release verification failed: {reason}")

    manifest_file = target / "entry.manifest.json"
    manifest = RuntimeExtension.from_dict(json.loads(manifest_file.read_text(encoding="utf-8")))
    if publisher and manifest.publisher != publisher:
        raise ValueError(
            f"Activation failed: publisher mismatch (expected '{publisher}', "
            f"got '{manifest.publisher}')"
        )
    eff_publisher = manifest.publisher

    active_payload = {
        "extension_id": extension_id,
        "publisher": eff_publisher,
        "version": version,
        "activated_at": datetime.now(UTC).isoformat(),
        "remote_entry": manifest.remote_entry,
        "sri_hash": manifest.sri_hash,
        "status": "active",
    }

    staging = root / ".staging" / f"activate-{uuid.uuid4().hex}"
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_text(json.dumps(active_payload, sort_keys=True), encoding="utf-8")

    rec_path = _active_record_path(root, eff_publisher, extension_id)
    rec_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, rec_path)

    return {
        "status": "activated",
        "extension_id": extension_id,
        "publisher": eff_publisher,
        "version": version,
        "active_record": active_payload,
        **_descriptor(manifest),
    }


def rollback_extension(
    *,
    extension_id: str,
    version: str,
    publisher: str | None = None,
    public_key_pem: Callable[[str], bytes | None] | None = None,
    artifact_root: Path | None = None,
) -> dict:
    """Roll back to a retained verified release without re-signing it."""
    res = activate_extension(
        extension_id=extension_id,
        version=version,
        publisher=publisher,
        public_key_pem=public_key_pem,
        artifact_root=artifact_root,
    )
    res["status"] = "rolled_back"
    return res


def get_active_release(
    *,
    extension_id: str,
    publisher: str | None = None,
    artifact_root: Path | None = None,
) -> dict | None:
    """Retrieve the active release record for an extension identity."""
    root = (artifact_root or config.EXTENSION_ARTIFACT_DIR).resolve()
    if publisher:
        rec = _active_record_path(root, publisher, extension_id)
        if rec.is_file():
            try:
                return json.loads(rec.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        return None
    active_dir = root / ".active-releases"
    if not active_dir.is_dir():
        return None
    matches = list(active_dir.glob(f"*/{extension_id}.json"))
    if not matches:
        return None
    try:
        return json.loads(matches[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_active_releases(artifact_root: Path | None = None) -> list[dict]:
    """List all active release records across all extensions."""
    root = (artifact_root or config.EXTENSION_ARTIFACT_DIR).resolve()
    active_dir = root / ".active-releases"
    if not active_dir.is_dir():
        return []
    results: list[dict] = []
    seen: set[str] = set()
    for rec_file in sorted(active_dir.glob("*/*.json")):
        try:
            data = json.loads(rec_file.read_text(encoding="utf-8"))
            ext_id = data.get("extension_id")
            if ext_id and ext_id not in seen:
                seen.add(ext_id)
                results.append(data)
        except (OSError, json.JSONDecodeError):
            continue
    return results


def verify_extension(
    *,
    extension_id: str,
    version: str,
    public_key_pem: Callable[[str], bytes | None],
    artifact_root: Path | None = None,
) -> dict:
    """Read-only integrity and publisher verification for one installed release."""
    root = (artifact_root or config.EXTENSION_ARTIFACT_DIR).resolve()
    target = root / extension_id / version
    manifest_file = target / "entry.manifest.json"
    if not manifest_file.is_file():
        return {"valid": False, "reason": "missing-manifest"}
    try:
        manifest = RuntimeExtension.from_dict(json.loads(manifest_file.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValueError) as exc:
        return {"valid": False, "reason": f"invalid-manifest: {exc}"}
    key = public_key_pem(manifest.publisher)
    if not key or not LocalEd25519SigningBackend().verify_signature(
        manifest.canonical_bytes(), manifest.signature, key
    ):
        return {"valid": False, "reason": "publisher-verification-failed"}
    entry = target / Path(manifest.remote_entry).name
    if not entry.is_file() or _sri(entry.read_bytes()) != manifest.sri_hash:
        return {"valid": False, "reason": "entry-sri-mismatch"}
    for rel, expected in manifest.verified_chunks.items():
        chunk = target / rel.removeprefix("./")
        if not chunk.is_file() or _sri(chunk.read_bytes()) != expected:
            return {"valid": False, "reason": f"chunk-sri-mismatch:{rel}"}
    return {"valid": True, "descriptor": _descriptor(manifest)}


def repair_extension(
    *,
    entry: Path,
    extension_id: str,
    publisher: str,
    version: str,
    public_key_pem: Callable[[str], bytes | None],
    artifact_root: Path | None = None,
) -> dict:
    """Restore an installed release only when candidate bytes match its retained signed record."""
    root = (artifact_root or config.EXTENSION_ARTIFACT_DIR).resolve()
    record = _record_path(root, extension_id, version)
    if not record.is_file():
        raise ValueError("no retained trusted release record exists for repair")
    try:
        manifest = RuntimeExtension.from_dict(json.loads(record.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"retained release record is invalid: {exc}") from exc
    if manifest.publisher != publisher:
        raise ValueError("repair publisher does not match the retained signed release")
    key = public_key_pem(publisher)
    if not key or not LocalEd25519SigningBackend().verify_signature(
        manifest.canonical_bytes(), manifest.signature, key
    ):
        raise ValueError("retained release record publisher verification failed")
    entry = entry.resolve()
    chunks = _relative_chunks(entry)
    if _sri(entry.read_bytes()) != manifest.sri_hash:
        raise ValueError("repair entry bytes do not match retained release SRI")
    candidate_chunks = {
        "./" + path.relative_to(entry.parent).as_posix(): _sri(path.read_bytes()) for path in chunks
    }
    if candidate_chunks != manifest.verified_chunks:
        raise ValueError("repair chunk graph or bytes do not match retained release")
    target = root / extension_id / version
    staging = root / ".staging" / uuid.uuid4().hex
    staging.mkdir(parents=True, exist_ok=False)
    try:
        entry_name = Path(manifest.remote_entry).name
        (staging / entry_name).write_bytes(entry.read_bytes())
        for chunk in chunks:
            destination = staging / chunk.relative_to(entry.parent)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(chunk.read_bytes())
        (staging / "entry.manifest.json").write_bytes(record.read_bytes())
        target.parent.mkdir(parents=True, exist_ok=True)
        prior = root / ".quarantine" / f"repair-{extension_id}-{version}-{uuid.uuid4().hex}"
        if target.exists():
            prior.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, prior)
        try:
            os.replace(staging, target)
        except OSError:
            if prior.exists():
                os.replace(prior, target)
            raise
        if prior.exists():
            shutil.rmtree(prior)
        return {"status": "repaired", **_descriptor(manifest)}
    except (OSError, ValueError):
        shutil.rmtree(staging, ignore_errors=True)
        raise
