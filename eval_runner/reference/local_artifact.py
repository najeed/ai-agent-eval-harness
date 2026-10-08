"""
eval_runner.reference.local_artifact
OSS Reference Implementation: LocalFileArtifactStore
"""

import hashlib
import json
import logging
from datetime import UTC
from pathlib import Path
from typing import Any

import eval_runner.config as config
from eval_runner.interfaces.artifact import ArtifactStore
from eval_runner.utils.safe_path import SafeRunPathResolver

logger = logging.getLogger(__name__)


class LocalFileArtifactStore(ArtifactStore):
    """
    Local filesystem-backed reference artifact store.
    Saves artifacts directly to individual run directories under RUN_LOG_DIR
    with strict path-safety boundaries and cryptographic tamper evidence.

    This OSS store is logically sealed through the ArtifactStore API; it is
    not a physical WORM or retention-enforcing filesystem. Deployments that
    require immutable retention must supply an ArtifactStore backed by an
    external WORM/retention system (for example Object Lock).
    """

    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir or config.RUN_LOG_DIR).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.immutability_guarantee = "TAMPER_EVIDENT_LOGICAL_SEAL"

    def _get_run_dir(self, run_id: str, create: bool = False) -> Path:
        return SafeRunPathResolver.resolve_run_dir(self.base_dir, run_id, create=create)

    def is_sealed(self, run_id: str) -> bool:
        try:
            run_dir = self._get_run_dir(run_id, create=False)
        except (ValueError, PermissionError):
            return False
        if not run_dir.exists():
            return False
        return (run_dir / ".sealed").exists() or (run_dir / "trace_seal.json").exists()

    def seal(self, run_id: str, metadata: dict[str, Any] | None = None) -> None:
        run_dir = self._get_run_dir(run_id, create=True)
        seal_marker = run_dir / ".sealed"
        seal_data = dict(metadata or {})
        seal_data.setdefault("sealed", True)
        seal_data.setdefault("run_id", run_id)

        # WORM retention and legal hold (SOC 2 CC6.8 / DF-03)
        retention_days = seal_data.get("retention_days") or getattr(
            config, "WORM_RETENTION_DAYS", 0
        )
        legal_hold = (
            seal_data.get("legal_hold")
            if "legal_hold" in seal_data
            else getattr(config, "WORM_LEGAL_HOLD", False)
        )
        if retention_days:
            seal_data["retention_days"] = retention_days
            if "retention_until" not in seal_data:
                from datetime import datetime, timedelta

                retain_until = datetime.now(UTC) + timedelta(days=retention_days)
                seal_data["retention_until"] = retain_until.isoformat()
        if legal_hold:
            seal_data["legal_hold"] = True

        with open(seal_marker, "w", encoding="utf-8") as f:
            json.dump(seal_data, f, indent=2)

    def unseal(self, run_id: str) -> None:
        """
        Rollback helper: unseals a vault if rollback is required during transactional recovery.
        In production, permanently sealed runs cannot be unsealed.
        Under active legal hold or unexpired WORM retention, unsealing is strictly prohibited.
        """
        from eval_runner.run_lifecycle import RunLifecycleState, get_run_lifecycle_state

        is_prod = config.is_production()
        if is_prod and get_run_lifecycle_state(run_id) == RunLifecycleState.SEALED:
            raise PermissionError(
                f"ProductionImmutabilityViolation: Cannot unseal permanently "
                f"sealed run '{run_id}' in production."
            )

        try:
            run_dir = self._get_run_dir(run_id, create=False)
            if run_dir.exists():
                seal_marker = run_dir / ".sealed"
                if seal_marker.exists():
                    try:
                        with open(seal_marker, encoding="utf-8") as sf:
                            seal_data = json.load(sf)
                    except Exception:
                        seal_data = {}
                    if seal_data.get("legal_hold"):
                        raise PermissionError(
                            f"WORMImmutabilityViolation: Cannot unseal run "
                            f"'{run_id}' under active legal hold."
                        )
                    retention_until_str = seal_data.get("retention_until")
                    if retention_until_str:
                        from datetime import datetime

                        try:
                            retention_until = datetime.fromisoformat(retention_until_str)
                            if datetime.now(UTC) < retention_until:
                                raise PermissionError(
                                    f"WORMImmutabilityViolation: Cannot unseal run "
                                    f"'{run_id}' prior to retention expiry ({retention_until_str})."
                                )
                        except (ValueError, TypeError):
                            pass
                    seal_marker.unlink(missing_ok=True)
        except PermissionError:
            raise
        except OSError as unlink_err:
            logger.debug("Failed to unseal run directory for %s: %s", run_id, unlink_err)

    def store_artifact(
        self,
        run_id: str,
        artifact_name: str,
        content: bytes | str,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        overwrite: bool = True,
        append: bool = False,
        **kwargs: Any,
    ) -> str:
        # Check if already sealed (only internal seal markers allowed)
        if self.is_sealed(run_id) and artifact_name not in (
            ".sealed",
            "trace_seal.json",
        ):
            raise PermissionError(
                f"Artifact vault for run '{run_id}' is sealed; "
                "mutations and new artifacts are prohibited."
            )

        run_dir = self._get_run_dir(run_id, create=True)
        target_path = SafeRunPathResolver.resolve_artifact_path(run_dir, artifact_name)

        if target_path.exists() and not overwrite and not append:
            raise PermissionError(
                f"Artifact '{artifact_name}' already exists and overwrite is disabled (Sealed)"
            )

        target_path.parent.mkdir(parents=True, exist_ok=True)

        if append:
            mode = "ab" if isinstance(content, bytes) else "a"
        else:
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

        # WORM retention metadata (SOC 2 CC6.8 / DF-03)
        retention_days = (
            kwargs.get("retention_days")
            or meta_dict.get("retention_days")
            or getattr(config, "WORM_RETENTION_DAYS", 0)
        )
        legal_hold = (
            kwargs.get("legal_hold")
            if "legal_hold" in kwargs
            else (
                meta_dict.get("legal_hold")
                if "legal_hold" in meta_dict
                else getattr(config, "WORM_LEGAL_HOLD", False)
            )
        )
        compliance_mode = (
            kwargs.get("compliance_mode")
            or meta_dict.get("compliance_mode")
            or getattr(config, "WORM_COMPLIANCE_MODE", "COMPLIANCE")
        )

        if retention_days:
            meta_dict["retention_days"] = retention_days
            if "retention_until" not in meta_dict and "retention_until" not in kwargs:
                from datetime import datetime, timedelta

                retain_until = datetime.now(UTC) + timedelta(days=retention_days)
                meta_dict["retention_until"] = retain_until.isoformat()
            elif "retention_until" in kwargs:
                meta_dict["retention_until"] = kwargs["retention_until"]
        if legal_hold:
            meta_dict["legal_hold"] = True
        if compliance_mode:
            meta_dict["compliance_mode"] = compliance_mode

        meta_path = run_dir / f"{target_path.name}.meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta_dict, f, indent=2)

        # Zero-Touch extension hook: notify plugins of artifact creation
        try:
            from eval_runner.plugins import manager

            manager.trigger(
                "on_artifact_created",
                run_id=run_id,
                artifact_name=artifact_name,
                artifact_path=str(target_path),
                metadata=meta_dict,
            )
        except Exception as p_err:
            logger.debug("on_artifact_created plugin dispatch notice: %s", p_err)

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
