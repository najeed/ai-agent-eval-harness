"""
eval_runner.reference.local_run_store
OSS Reference Implementation: LocalFileRunStore

AgentV v2.0.0: runs are append-only. Manifest publication is immutable
after certification: once a vault is sealed, save_run_manifest refuses to
overwrite divergent content (RunManifestImmutableError). Pre-certification,
divergent republications are preserved as an append-only revision history;
the originally published manifest is never mutated.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from eval_runner import config
from eval_runner.interfaces.run_store import RunStore
from eval_runner.utils import crypto
from eval_runner.utils.safe_path import SafeRunPathResolver

logger = logging.getLogger(__name__)


class RunManifestImmutableError(PermissionError):
    """Raised when a certified (sealed) run manifest may not be overwritten."""

    def __init__(self, run_id: str, vault_path: Path):
        super().__init__(
            f"Run '{run_id}' is certified/sealed; manifest publication is immutable "
            f"({vault_path}). Divergent manifests must be published as new runs."
        )
        self.run_id = run_id
        self.vault_path = str(vault_path)


def _canonical_digest(manifest: dict[str, Any]) -> str:
    """
    SHA3-256 canonical manifest digest via the unified hash utility layer
    (FIPS 202 standardization, CHANGELOG v1.6.0). Computed fresh on both the
    incoming and existing manifests at publication time; never persisted.
    """
    canonical = json.dumps(manifest, sort_keys=True, default=str).encode("utf-8")
    return crypto.checksum(canonical)


class LocalFileRunStore(RunStore):
    """
    Local filesystem-backed reference RunStore.
    Manages run vaults and manifests under RUN_LOG_DIR with safe path resolution
    and append-only manifest immutability.
    """

    def __init__(self, log_dir: str | Path | None = None):
        self.log_dir = Path(log_dir or config.RUN_LOG_DIR).resolve()
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _get_run_vault(self, run_id: str, create: bool = False) -> Path:
        return SafeRunPathResolver.resolve_run_dir(self.log_dir, run_id, create=create)

    @staticmethod
    def _is_sealed(run_vault: Path) -> bool:
        return (run_vault / ".sealed").exists() or (run_vault / "trace_seal.json").exists()

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
            "sealed": self._is_sealed(run_vault),
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

    def list_manifest_revisions(self, run_id: str) -> list[str]:
        """Returns the append-only revision history for a run's manifests."""
        try:
            run_vault = self._get_run_vault(run_id, create=False)
        except (ValueError, PermissionError):
            return []
        rev_dir = run_vault / "manifest_revisions"
        if not rev_dir.exists():
            return []
        return sorted(p.name for p in rev_dir.glob("*.json"))

    def save_run_manifest(self, run_id: str, manifest: dict[str, Any]) -> str:
        """
        Append-only manifest publication.

        - First publication wins the authoritative run_manifest.json slot.
        - Identical republication is an idempotent no-op.
        - Divergent pre-certification republication is appended to
          manifest_revisions/ (history is never destroyed).
        - Divergent post-certification (sealed) republication raises
          RunManifestImmutableError.
        """
        run_vault = self._get_run_vault(run_id, create=True)
        target = run_vault / "run_manifest.json"

        incoming_digest = _canonical_digest(manifest)

        if target.exists():
            try:
                with open(target, encoding="utf-8") as f:
                    existing = json.load(f)
                existing_digest = _canonical_digest(existing)
            except Exception:
                existing = None
                existing_digest = None

            if existing_digest == incoming_digest:
                return str(target)

            if self._is_sealed(run_vault):
                raise RunManifestImmutableError(run_id, target)

            revisions = run_vault / "manifest_revisions"
            revisions.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f")
            rev_path = revisions / f"{ts}-{incoming_digest[:8]}.json"
            with open(rev_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
            logger.info(
                "Manifest divergence for run '%s' preserved as revision %s "
                "(original publication untouched).",
                run_id,
                rev_path.name,
            )
            return str(rev_path)

        tmp_path = target.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        tmp_path.replace(target)
        return str(target)

    def delete_run(self, run_id: str) -> bool:
        try:
            run_vault = self._get_run_vault(run_id, create=False)
        except (ValueError, PermissionError):
            return False

        if self._is_sealed(run_vault):
            logger.warning(
                "Refusing to delete certified run '%s': evidence vault is sealed.",
                run_id,
            )
            raise RunManifestImmutableError(run_id, run_vault)

        if run_vault.exists() and run_vault.is_dir():
            from eval_runner.utils import rmtree_resilient

            rmtree_resilient(run_vault)
            return True
        return False
