"""
eval_runner.reference.local_artifact
OSS Reference Implementation: LocalFileArtifactStore
"""

import json
from pathlib import Path
from typing import Any

import eval_runner.config as config
from eval_runner.interfaces.artifact import ArtifactStore


class LocalFileArtifactStore(ArtifactStore):
    """
    Local filesystem-backed reference artifact store.
    Saves artifacts directly to individual run directories under RUN_LOG_DIR.
    """

    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(base_dir or config.RUN_LOG_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_run_dir(self, run_id: str) -> Path:
        run_dir = self.base_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def store_artifact(
        self,
        run_id: str,
        artifact_name: str,
        content: bytes | str,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        run_dir = self._get_run_dir(run_id)
        target_path = run_dir / artifact_name
        target_path.parent.mkdir(parents=True, exist_ok=True)

        mode = "wb" if isinstance(content, bytes) else "w"
        encoding = None if isinstance(content, bytes) else "utf-8"

        with open(target_path, mode, encoding=encoding) as f:
            f.write(content)

        if metadata:
            meta_path = run_dir / f"{artifact_name}.meta.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)

        return str(target_path)

    def get_artifact(self, run_id: str, artifact_name: str) -> bytes | None:
        target_path = self._get_run_dir(run_id) / artifact_name
        if target_path.exists() and target_path.is_file():
            with open(target_path, "rb") as f:
                return f.read()
        return None

    def exists(self, run_id: str, artifact_name: str) -> bool:
        return (self._get_run_dir(run_id) / artifact_name).exists()

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        run_dir = self._get_run_dir(run_id)
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
