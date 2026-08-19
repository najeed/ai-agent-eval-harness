"""
eval_runner.reference.local_artifact
OSS Reference Implementation: LocalFileArtifactStore
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import eval_runner.config as config
from eval_runner.interfaces.artifact import ArtifactStore
from eval_runner.utils.safe_path import SafeRunPathResolver


class LocalFileArtifactStore(ArtifactStore):
    """
    Local filesystem-backed reference artifact store.
    Saves artifacts directly to individual run directories under RUN_LOG_DIR
    with strict path-safety boundary verification and optional immutability enforcement.
    """

    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir or config.RUN_LOG_DIR).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_run_dir(self, run_id: str, create: bool = False) -> Path:
        return SafeRunPathResolver.resolve_run_dir(self.base_dir, run_id, create=create)

    def store_artifact(
        self,
        run_id: str,
        artifact_name: str,
        content: bytes | str,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        overwrite: bool = True,
    ) -> str:
        run_dir = self._get_run_dir(run_id, create=True)
        target_path = SafeRunPathResolver.resolve_artifact_path(run_dir, artifact_name)

        if target_path.exists() and not overwrite:
            raise PermissionError(
                f"Artifact '{artifact_name}' already exists and overwrite is disabled (Sealed)"
            )

        target_path.parent.mkdir(parents=True, exist_ok=True)

        mode = "wb" if isinstance(content, bytes) else "w"
        encoding = None if isinstance(content, bytes) else "utf-8"

        with open(target_path, mode, encoding=encoding) as f:
            f.write(content)

        # Compute content SHA3-256 digest
        raw_bytes = content if isinstance(content, bytes) else content.encode("utf-8")
        sha3_hash = hashlib.sha3_256(raw_bytes).hexdigest()

        meta_dict = dict(metadata or {})
        meta_dict.setdefault("sha3_256", sha3_hash)
        meta_dict.setdefault("content_type", content_type or "application/octet-stream")
        meta_dict.setdefault("size_bytes", len(raw_bytes))

        meta_path = run_dir / f"{target_path.name}.meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta_dict, f, indent=2)

        return str(target_path)

    def get_artifact(self, run_id: str, artifact_name: str) -> bytes | None:
        run_dir = self._get_run_dir(run_id, create=False)
        if not run_dir.exists():
            return None
        target_path = SafeRunPathResolver.resolve_artifact_path(run_dir, artifact_name)
        if target_path.exists() and target_path.is_file():
            with open(target_path, "rb") as f:
                return f.read()
        return None

    def exists(self, run_id: str, artifact_name: str) -> bool:
        run_dir = self._get_run_dir(run_id, create=False)
        if not run_dir.exists():
            return False
        target_path = SafeRunPathResolver.resolve_artifact_path(run_dir, artifact_name)
        return target_path.exists()

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        run_dir = self._get_run_dir(run_id, create=False)
        if not run_dir.exists():
            return []

        artifacts = []
        for item in run_dir.glob("*"):
            if item.is_file() and not item.name.endswith(".meta.json"):
                artifacts.append(
                    {
                        "name": item.name,
                        "size_bytes": item.stat().st_size,
                        "path": str(item),
                    }
                )
        return artifacts
