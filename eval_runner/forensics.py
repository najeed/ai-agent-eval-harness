import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

from agentv_runtime.contracts import EvidenceBoundednessLimits

from . import config
from .utils.crypto import file_hash as _file_hash, shake256_digest as _shake256_digest

logger = logging.getLogger(__name__)


def compute_file_hash(file_path: Path) -> str:
    """Computes SHA3-256 hash of a file. (Module Level Utility)"""
    return _file_hash(file_path)


def compute_shake256_digest(data: bytes, length: int = 32) -> bytes:
    """Computes SHAKE-256 digest of bytes. Required for ML-DSA-65 (ZES)."""
    return _shake256_digest(data, length=length)


def _bound_interaction_payload(
    data: Any, max_bytes: int = EvidenceBoundednessLimits.MAX_INTERACTION_BYTES
) -> Any:
    """
    Evidence Boundedness Contract:
    Ensures interaction payloads written to adapter_trace.jsonl never exceed max_bytes.
    Large payloads are truncated with an RFC 8785 SHA3-256 digest commitment.
    """
    if data is None:
        return None
    try:
        raw_str = json.dumps(data, default=str)
        if len(raw_str.encode("utf-8")) <= max_bytes:
            return data

        import hashlib

        from agentv_runtime.canonical import canonical_json_encode

        try:
            canonical_bytes = canonical_json_encode(data)
        except Exception:
            canonical_bytes = raw_str.encode("utf-8")

        digest = f"sha3_256:{hashlib.sha3_256(canonical_bytes).hexdigest()}"

        sample: Any
        if isinstance(data, dict):
            sample = {k: data[k] for k in list(data.keys())[:5]}
        elif isinstance(data, list):
            sample = data[:5]
        else:
            sample = str(data)[:256]

        return {
            "__BOUNDED_INTERACTION__": {
                "content_hash": digest,
                "byte_length": len(canonical_bytes),
                "sample": sample,
                "truncated": True,
            }
        }
    except Exception as err:
        logger.debug("Failed bounding interaction payload: %s", err)
        return data


def list_diff(old: list, new: list) -> list | dict:
    """
    Computes a differential between two lists, optimized for database-style row sets.
    Identifies primary keys (id, audit_id, etc.) to perform granular row tracking.
    Enforces Evidence Boundedness Contract limits on unkeyed and oversized list changes.
    """
    if not old or not new:
        if isinstance(new, list) and len(new) > EvidenceBoundednessLimits.MAX_INLINE_ITEMS:
            import hashlib

            from agentv_runtime.canonical import canonical_json_encode

            try:
                c_bytes = canonical_json_encode(new)
            except Exception:
                c_bytes = json.dumps(new, default=str).encode("utf-8")
            digest = f"sha3_256:{hashlib.sha3_256(c_bytes).hexdigest()}"
            return {
                "__LIST_DIFF_BOUNDED__": {
                    "total_items": len(new),
                    "old_items": len(old) if old else 0,
                    "result_hash": digest,
                    "sample": new[:5],
                    "truncated": True,
                }
            }
        return new

    # Tier 1: Check if this is a list of dictionaries (likely a DB table)
    if not all(isinstance(x, dict) for x in old) or not all(isinstance(x, dict) for x in new):
        if len(new) > EvidenceBoundednessLimits.MAX_INLINE_ITEMS:
            import hashlib

            from agentv_runtime.canonical import canonical_json_encode

            try:
                c_bytes = canonical_json_encode(new)
            except Exception:
                c_bytes = json.dumps(new, default=str).encode("utf-8")
            digest = f"sha3_256:{hashlib.sha3_256(c_bytes).hexdigest()}"
            return {
                "__LIST_DIFF_BOUNDED__": {
                    "total_items": len(new),
                    "old_items": len(old),
                    "result_hash": digest,
                    "sample": new[:5],
                    "truncated": True,
                }
            }
        return new  # Full replacement for non-dictionary lists within bounds

    # Tier 2: Discover Authoritative Primary Key
    pk_candidates = ["id", "audit_id", "application_id", "applicant_id", "email"]
    pk = next(
        (k for k in pk_candidates if all(k in x for x in old) and all(k in x for x in new)), None
    )

    if not pk:
        if len(new) > EvidenceBoundednessLimits.MAX_INLINE_ITEMS:
            import hashlib

            from agentv_runtime.canonical import canonical_json_encode

            try:
                c_bytes = canonical_json_encode(new)
            except Exception:
                c_bytes = json.dumps(new, default=str).encode("utf-8")
            digest = f"sha3_256:{hashlib.sha3_256(c_bytes).hexdigest()}"
            return {
                "__LIST_DIFF_BOUNDED__": {
                    "total_items": len(new),
                    "old_items": len(old),
                    "result_hash": digest,
                    "sample": new[:5],
                    "truncated": True,
                }
            }
        return new  # Full replacement if no reliable identity found within bounds

    # Tier 3: Record-Level Differential Analysis
    old_map = {x[pk]: x for x in old}
    diff = {"added": [], "modified": [], "deleted": []}

    new_pks = set()
    for item in new:
        val = item[pk]
        new_pks.add(val)
        if val not in old_map:
            diff["added"].append(item)
        elif old_map[val] != item:
            # Recursive check for deep dict changes within a row
            row_diff = dict_diff(old_map[val], item)
            if row_diff:
                diff["modified"].append({pk: val, **row_diff})

    # Track removals (Non-Repudiation Requirement)
    for val in old_map:
        if val not in new_pks:
            diff["deleted"].append(val)

    # Optimization: Return None if state is identical to prevent empty diff files
    if not any(diff.values()):
        return None

    # Enforce bounded diff size
    total_mutations = len(diff["added"]) + len(diff["modified"]) + len(diff["deleted"])
    if total_mutations > EvidenceBoundednessLimits.MAX_INLINE_ITEMS:
        import hashlib

        from agentv_runtime.canonical import canonical_json_encode

        try:
            diff_bytes = canonical_json_encode(diff)
        except Exception:
            diff_bytes = json.dumps(diff, default=str).encode("utf-8")
        diff_hash = f"sha3_256:{hashlib.sha3_256(diff_bytes).hexdigest()}"
        return {
            "__LIST_DIFF_BOUNDED__": {
                "added_count": len(diff["added"]),
                "modified_count": len(diff["modified"]),
                "deleted_count": len(diff["deleted"]),
                "added_sample": diff["added"][:3],
                "modified_sample": diff["modified"][:3],
                "deleted_sample": diff["deleted"][:3],
                "diff_hash": diff_hash,
                "truncated": True,
            }
        }

    return {"__LIST_DIFF__": diff}


def dict_diff(old: dict, new: dict) -> dict:
    """
    Computes a recursive differential between two dictionaries.
    Returns a dict containing only the changed or new keys.
    Deleted keys are marked as '__DELETED__'.
    """
    diff = {}
    # Find changed and new keys
    for k, v in new.items():
        if k not in old:
            diff[k] = v
        elif old[k] != v:
            if isinstance(v, dict) and isinstance(old[k], dict):
                sub_diff = dict_diff(old[k], v)
                if sub_diff:
                    diff[k] = sub_diff
            elif isinstance(v, list) and isinstance(old[k], list):
                # Industrial Optimization: List-level differential
                l_diff = list_diff(old[k], v)
                if l_diff is not None:
                    diff[k] = l_diff
            else:
                diff[k] = v

    # Find deleted keys
    for k in old:
        if k not in new:
            diff[k] = "__DELETED__"

    return diff


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

        # 2. Global Safety: Hidden files, manifest files, and Policy-based Exclusions
        if (
            path.name.startswith(".")
            or path.name.endswith("_manifest.json")
            or path.name.endswith("_vc.json")
        ):
            return False

        # 2b. [INDUSTRIAL BLACKLIST]: Prevent environment leakage from shared temp folders
        # Matches patterns found in common test runners and detention jails
        if any(p in path.name for p in ["pytest-", "aes_test_jail-"]):
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
            current_size = path.stat().st_size
            if current_size > self.max_size:
                logger.debug(
                    f"[Forensics] Excluding oversized artifact ({current_size}b): {path.name}"
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
        Implements Namespace Affinity Enforcement and Path Jailing.
        """
        ledger = {}
        is_dedicated_dir = run_id and directory.name == run_id

        # [AgentV v1.6.0] Trace-Jailing enforcement: If not a dedicated dir,
        # we refuse to walk subdirectories.
        # This prevents accidental "inhaling" of neighbors in shared /tmp directories.
        max_depth = 1 if not is_dedicated_dir else 5
        base_depth = len(directory.parts)

        for root, dirs, files in os.walk(directory):
            curr_depth = len(Path(root).parts) - base_depth
            if curr_depth > max_depth:
                # Prune the walk to prevent crossing boundaries in non-vaulted environments
                dirs[:] = []
                continue

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
        self._last_state: dict[str, Any] = {}
        self._branch_states: dict[str, dict[str, Any]] = {}
        self.evidence_incomplete: bool = False

    @property
    def resource_telemetry(self) -> dict[str, Any]:
        """Returns the current resource usage (CPU/RAM) for the harness process."""
        import os
        import time

        try:
            import psutil

            process = psutil.Process(os.getpid())
            return {
                "timestamp": time.time(),
                "memory_mb": process.memory_info().rss / 1024 / 1024,
                "cpu_percent": process.cpu_percent(interval=None),
                "threads": process.num_threads(),
            }
        except Exception:
            return {"timestamp": time.time(), "status": "telemetry_unavailable"}

    def register_artifact(self, path: Path, alias: str):
        """Registers a file path to be collected at the end of the session."""
        if not path.exists():
            return

        # Industrial Rule: Respect the Relevance Engine (Size Caps & Patterns)
        engine = ForensicRelevanceEngine()
        if not engine.is_relevant(path):
            logger.warning(
                f"   [Forensics] Artifact '{alias}' rejected by relevance policy "
                f"({path.stat().st_size} bytes)."
            )
            return

        self._artifacts.append({"path": path, "alias": alias})
        logger.debug(f"[Forensics] Registered artifact: {alias} -> {path}")

    def archive_plugin(self, path: Path) -> str:
        """
        Archives a plugin's source code into the forensic artifact vault.
        Ensures 100% reproducibility of ad-hoc injected code.
        Returns the SHA3-256 hash of the content.
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

    def record_external_receipts(self, receipts: list[dict[str, Any]], turn: int, node_id: str):
        """
        Record external agent execution receipts into forensic artifacts.
        Preserves provenance ('external_agent_telemetry' / 'reported') and binds receipt hashes.
        """
        if not receipts:
            return
        if not hasattr(self, "_external_receipts"):
            self._external_receipts = []
        self._external_receipts.extend(receipts)
        self.target_dir.mkdir(parents=True, exist_ok=True)
        receipt_filename = f"external_receipts_turn_{turn:03d}_{node_id}.json"
        target_path = self.target_dir / receipt_filename
        try:
            target_path.write_text(json.dumps(receipts, indent=2, default=str), encoding="utf-8")
            self.register_artifact(target_path, f"receipts/{receipt_filename}")
        except OSError as e:
            logger.debug("Failed writing receipt artifact: %s", e)

    def snapshot_state(self, state: dict[str, Any], turn: int, branch_id: str | None = None):
        """
        Saves a JSON snapshot of the world state to disk.
        Uses differential encoding (dict_diff) isolated per branch to prevent cross-contamination.
        """
        self.target_dir.mkdir(parents=True, exist_ok=True)
        branch_key = branch_id or "default"
        prior_state = self._branch_states.get(branch_key, self._last_state)
        is_full = turn == 0 or not prior_state

        prefix = f"state_turn_{turn:03d}"
        if branch_id:
            prefix += f"_{branch_id}"

        if is_full:
            snapshot_path = self.target_dir / f"{prefix}_full.json"
            content = state
        else:
            snapshot_path = self.target_dir / f"{prefix}_diff.json"
            content = dict_diff(prior_state, state)
            if not content:
                # Zero-Change optimization: Don't write empty diffs
                return

        # Evidence Boundedness Contract: verify total snapshot size does not exceed ceiling
        raw_content = json.dumps(content, indent=4, default=str)
        if len(raw_content.encode("utf-8")) > EvidenceBoundednessLimits.MAX_SNAPSHOT_BYTES:
            import hashlib

            from agentv_runtime.canonical import canonical_json_encode

            try:
                c_bytes = canonical_json_encode(content)
            except Exception:
                c_bytes = raw_content.encode("utf-8")

            snap_hash = f"sha3_256:{hashlib.sha3_256(c_bytes).hexdigest()}"
            content = {
                "__BOUNDED_SNAPSHOT__": {
                    "status": "BOUNDED_SNAPSHOT",
                    "keys": list(content.keys()) if isinstance(content, dict) else [],
                    "snapshot_hash": snap_hash,
                    "byte_size": len(c_bytes),
                    "truncated": True,
                    "summary": (
                        "State snapshot exceeded EvidenceBoundednessLimits.MAX_SNAPSHOT_BYTES. "
                        "Materialized bounded cryptographic commitment."
                    ),
                }
            }

        try:
            with open(snapshot_path, "w", encoding="utf-8") as f:
                json.dump(content, f, indent=4, default=str)

            self._state_snapshots[turn] = snapshot_path
            self._branch_states[branch_key] = state
            self._last_state = state  # Update cache for next turn
            logger.debug(
                f"[Forensics] {'Full' if is_full else 'Diff'} snapshot saved: {snapshot_path.name}"
            )
        except Exception as e:
            self.evidence_incomplete = True
            logger.error(f"[Forensics] Failed to save state snapshot for turn {turn}: {e}")

    def init_telemetry(self, headers: list[str]):
        """
        Initializes the telemetry CSV file with a header.
        Ensures O(1) header writing at session start.
        """
        self.target_dir.mkdir(parents=True, exist_ok=True)
        telemetry_path = self.target_dir / "telemetry.csv"

        try:
            with open(telemetry_path, "w", encoding="utf-8") as f:
                f.write(",".join(headers) + "\n")
            logger.debug(f"[Forensics] Telemetry CSV initialized at {telemetry_path}")
        except Exception as e:
            logger.error(f"[Forensics] Failed to initialize telemetry CSV: {e}")

    def register_raw_interaction(self, payload: dict, response: dict):
        """
        Logs a raw adapter interaction (stimulus/response) to the forensic vault.
        Ensures bit-for-bit auditability of agent-harness communication while
        enforcing the Evidence Boundedness Contract to prevent unbounded dumps.
        """
        self.target_dir.mkdir(parents=True, exist_ok=True)
        trace_path = self.target_dir / "adapter_trace.jsonl"

        import time

        bounded_payload = _bound_interaction_payload(payload)
        bounded_response = _bound_interaction_payload(response)

        entry = {
            "timestamp": time.time(),
            "payload": bounded_payload,
            "response": bounded_response,
        }

        try:
            with open(trace_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.error(f"[Forensics] Failed to log raw interaction: {e}")

    def collect(self) -> dict[str, str]:
        """
        Physically gathers all registered artifacts and snapshots into the forensics directory.
        Returns a ledger (SHA3-256 map) for inclusion in the VC v4 manifest.
        """
        if not self._artifacts and not self._state_snapshots:
            return {}

        self.target_dir.mkdir(parents=True, exist_ok=True)
        ledger = {}

        # 1. Collect registered artifacts
        for art in self._artifacts:
            src = art["path"]
            alias = art["alias"]
            dest = self.target_dir / alias

            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if src.resolve() != dest.resolve():
                    shutil.copy2(src, dest)
                ledger[alias] = compute_file_hash(dest)
            except Exception as e:
                self.evidence_incomplete = True
                logger.error(f"[Forensics] Failed to collect artifact {alias}: {e}")

        # 2. Add snapshots to ledger
        for _, path in self._state_snapshots.items():
            rel_path = f"forensics/{path.name}"
            if path.exists():
                ledger[rel_path] = compute_file_hash(path)

        return ledger
