import hashlib
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

from . import config

logger = logging.getLogger(__name__)


def compute_file_hash(file_path: Path) -> str:
    """Computes SHA-256 hash of a file. (Module Level Utility)"""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


class ForensicRelevanceEngine:
    """
    Authoritative Filtering Engine for Participation-First Artifact Collection.
    Optimizes evidence ledgers by enforcing strict relevance criteria across three tiers.
    """

    def __init__(self, profile: dict | None = None):
        profile = profile or {}
        policy = config.get_forensic_policy()

        self.allowed_exts = set(profile.get("extensions", policy["extensions"]))
        self.mandatory_patterns = profile.get("mandatory_patterns", policy["mandatory_patterns"])
        self.exclusion_patterns = profile.get("exclusion_patterns", policy["exclusion_patterns"])
        self.max_size = profile.get("max_artifact_size", policy["max_artifact_size"])
        self.aliases = config.FORENSIC_EXTENSION_ALIASES

    def is_relevant(
        self, path: Path, run_id: str | None = None, is_dedicated_dir: bool = False
    ) -> bool:
        """
        Determines relevance based on the three-tier model:
        Tier 1: Participatory Root (forensics/) -> Always Included.
        Tier 2: Mandatory Patterns -> Always Included (Bypasses Size Cap).
        Tier 3: Functional Extensions -> Included if size < MAX_ARTIFACT_SIZE.

        Namespace Affinity: If NOT in a dedicated directory, only allow run_id prefixed files.
        """
        # 1. Tier 1: Absolute Mandatory (Participation Root)
        is_forensics_subdir = "forensics" in path.parts
        if is_forensics_subdir:
            return True

        # 2. Global Safety: Hidden files, manifest files, and System Junk
        if (
            path.name.startswith(".")
            or path.name.endswith("_manifest.json")
            or path.name.endswith("_vc.json")
        ):
            return False

        if path.name in config.SYSTEM_JUNK_FILES:
            return False

        if any(path.name.endswith(ext) for ext in config.SYSTEM_JUNK_EXTENSIONS):
            return False

        if any(re.match(p, path.name) for p in self.exclusion_patterns):
            return False

        # 3. Namespace Affinity Enforcement
        # If NOT in a dedicated dir and NOT in forensics/, only allow run_id prefixed files
        if not is_dedicated_dir and not is_forensics_subdir:
            if run_id and not path.name.startswith(run_id):
                return False

        # 4. Tier 2: Mandatory Patterns (Administrative Override)
        if any(re.match(p, path.name) for p in self.mandatory_patterns):
            return True

        # 5. Tier 3: Functional Extension Whitelist
        suffix = path.suffix.lower()
        canonical_suffix = self.aliases.get(suffix, suffix)

        if canonical_suffix not in self.allowed_exts:
            return False

        # Apply Storage Safety (Size Cap) for Tier 3 only
        try:
            if path.stat().st_size > self.max_size:
                logger.debug(
                    f"[Forensics] Excluding oversized artifact "
                    f"({path.stat().st_size}b): {path.name}"
                )
                return False
        except (FileNotFoundError, PermissionError):
            return False

        return True

    def compute_filtered_ledger(
        self, directory: Path, exclude_files: list[str], run_id: str | None = None
    ) -> dict[str, str]:
        """
        Computes a filtered forensic ledger for a directory.
        Implements Namespace Affinity Enforcement.
        """
        ledger = {}
        is_dedicated_dir = run_id and directory.name == run_id

        for root, _, files in os.walk(directory):
            for file in files:
                file_path = Path(root) / file
                if file in exclude_files:
                    continue

                if self.is_relevant(file_path, run_id=run_id, is_dedicated_dir=is_dedicated_dir):
                    rel_path = file_path.relative_to(directory).as_posix()
                    try:
                        ledger[rel_path] = compute_file_hash(file_path)
                    except Exception as e:
                        logger.warning(f"[Forensics] Failed to hash {rel_path}: {e}")
        return ledger


class ForensicCollector:
    """
    Industrial Forensic Collector for session artifacts.
    Gather sidecar files (logs, DB snapshots, world states) for cryptographic verification.
    Ensures O(N) memory scaling by offloading heavy state data to sidecar JSON files.
    """

    def __init__(self, run_id: str, run_log_dir: Path):
        self.run_id = run_id
        self.target_dir = run_log_dir / "forensics"
        self._artifacts: list[dict[str, Any]] = []
        self._state_snapshots: dict[int, Path] = {}

    def register_artifact(self, path: Path, alias: str):
        """Registers a file path to be collected at the end of the session."""
        if path.exists():
            self._artifacts.append({"path": path, "alias": alias})
            logger.debug(f"[Forensics] Registered artifact: {alias} -> {path}")

    def archive_plugin(self, path: Path) -> str:
        """
        Archives a plugin's source code into the forensic artifact vault.
        Ensures 100% reproducibility of ad-hoc injected code.
        Returns the SHA-256 hash of the content.
        """
        if not path.exists():
            raise FileNotFoundError(f"Plugin source not found: {path}")

        file_hash = compute_file_hash(path)
        dest_filename = f"{path.stem}.{file_hash[:12]}.py"
        target_path = self.target_dir / "plugins" / dest_filename

        target_path.parent.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.copy2(path, target_path)

        # Link artifact to the session lifecycle
        # We use a specialized alias to facilitate automated replay discovery
        self.register_artifact(target_path, f"plugins/{dest_filename}")

        return file_hash

    def snapshot_state(self, state: dict[str, Any], turn: int):
        """
        Saves a JSON snapshot of the world state to disk.
        Prevents O(N^2) memory growth in SessionManager.
        """
        self.target_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = self.target_dir / f"state_turn_{turn:03d}.json"

        try:
            with open(snapshot_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=4)
            self._state_snapshots[turn] = snapshot_path
            logger.debug(f"[Forensics] State snapshot saved for turn {turn}: {snapshot_path.name}")
        except Exception as e:
            logger.error(f"[Forensics] Failed to save state snapshot for turn {turn}: {e}")

    def collect(self) -> dict[str, str]:
        """
        Physically gathers all registered artifacts and snapshots into the forensics directory.
        Returns a ledger (SHA-256 map) for inclusion in the VC v3 manifest.
        """
        self.target_dir.mkdir(parents=True, exist_ok=True)
        ledger = {}

        # 1. Collect registered artifacts
        for art in self._artifacts:
            src = art["path"]
            alias = art["alias"]
            dest = self.target_dir / alias

            try:
                if src.resolve() != dest.resolve():
                    shutil.copy2(src, dest)
                ledger[alias] = compute_file_hash(dest)
            except Exception as e:
                logger.error(f"[Forensics] Failed to collect artifact {alias}: {e}")

        # 2. Add snapshots to ledger
        for _, path in self._state_snapshots.items():
            rel_path = f"forensics/{path.name}"
            ledger[rel_path] = compute_file_hash(path)

        return ledger
