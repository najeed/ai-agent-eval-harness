"""
eval_runner.reference.local_run_store
OSS Reference Implementation: LocalFileRunStore
"""

import json
import logging
from pathlib import Path
from typing import Any

from eval_runner import config
from eval_runner.interfaces.run_store import RunStore
from eval_runner.utils.safe_path import SafeRunPathResolver

logger = logging.getLogger(__name__)


class LocalFileRunStore(RunStore):
    """
    Local filesystem-backed reference RunStore.
    Manages run vaults and manifests under RUN_LOG_DIR with safe path resolution.
    """

    def __init__(self, log_dir: str | Path | None = None):
        self.log_dir = Path(log_dir or config.RUN_LOG_DIR).resolve()
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _get_run_vault(self, run_id: str, create: bool = False) -> Path:
        return SafeRunPathResolver.resolve_run_dir(self.log_dir, run_id, create=create)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        try:
            run_vault = self._get_run_vault(run_id, create=False)
        except (ValueError, PermissionError):
            return None

        if not run_vault.exists() or not run_vault.is_dir():
            return None

        manifest_path = run_vault / "run_manifest.json"
        manifest_data = {}
        if manifest_path.exists():
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    manifest_data = json.load(f)
            except Exception as e:
                logger.debug("Failed to parse manifest for run %s: %s", run_id, e)

        trace_path = run_vault / "run.jsonl"
        return {
            "run_id": run_id,
            "vault_path": str(run_vault),
            "has_trace": trace_path.exists(),
            "manifest": manifest_data,
        }

    def list_runs(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        runs = []
        if not self.log_dir.exists():
            return []

        subdirs = sorted(
            [d for d in self.log_dir.iterdir() if d.is_dir() and not d.name.startswith(".")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        for d in subdirs[offset : offset + limit]:
            r_info = self.get_run(d.name)
            if r_info:
                runs.append(r_info)
        return runs

    def save_run_manifest(self, run_id: str, manifest: dict[str, Any]) -> str:
        run_vault = self._get_run_vault(run_id, create=True)
        target = run_vault / "run_manifest.json"
        with open(target, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        return str(target)

    def delete_run(self, run_id: str) -> bool:
        try:
            run_vault = self._get_run_vault(run_id, create=False)
        except (ValueError, PermissionError):
            return False

        if run_vault.exists() and run_vault.is_dir():
            from eval_runner.utils import rmtree_resilient

            rmtree_resilient(run_vault)
            return True
        return False
