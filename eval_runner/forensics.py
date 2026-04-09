import hashlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

class ForensicCollector:
    """
    Industrial Forensic Collector for session artifacts.
    Gather sidecar files (logs, DB snapshots, world states) for cryptographic verification.
    Ensures O(N) memory scaling by offloading heavy state data to sidecar JSON files.
    """

    def __init__(self, run_id: str, run_log_dir: Path):
        self.run_id = run_id
        self.target_dir = run_log_dir / "forensics"
        self._artifacts: List[Dict[str, Any]] = []
        self._state_snapshots: Dict[int, Path] = {}

    def register_artifact(self, path: Path, alias: str):
        """Registers a file path to be collected at the end of the session."""
        if path.exists():
            self._artifacts.append({"path": path, "alias": alias})
            logger.debug(f"[Forensics] Registered artifact: {alias} -> {path}")

    def snapshot_state(self, state: Dict[str, Any], turn: int):
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

    def collect(self) -> Dict[str, str]:
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
                shutil.copy2(src, dest)
                ledger[alias] = self._compute_hash(dest)
            except Exception as e:
                logger.error(f"[Forensics] Failed to collect artifact {alias}: {e}")

        # 2. Add snapshots to ledger
        for turn, path in self._state_snapshots.items():
            rel_path = f"forensics/{path.name}"
            ledger[rel_path] = self._compute_hash(path)

        return ledger

    @staticmethod
    def _compute_hash(file_path: Path) -> str:
        """Computes SHA-256 hash of a file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()
