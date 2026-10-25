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
import os
import time
from collections.abc import Generator
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


class TraceCorruptionError(ValueError):
    """Raised when a trace contains malformed JSON or corrupted records."""

    pass


def _canonical_digest(manifest: dict[str, Any]) -> str:
    """
    SHA3-256 canonical manifest digest via the unified hash utility layer
    (FIPS 202 standardization, CHANGELOG v1.6.0). Computed fresh on both the
    incoming and existing manifests at publication time; never persisted.
    """
    canonical = json.dumps(manifest, sort_keys=True, default=str).encode("utf-8")
    return crypto.checksum(canonical)


def _parse_scenario_from_run_id(run_id: str) -> str:
    parts = run_id.split("-")
    if len(parts) >= 3 and parts[0] == "run":
        return "-".join(parts[1:-1])
    if len(parts) == 2 and parts[0] == "run":
        return parts[1]
    return run_id


def _process_is_alive(pid: int) -> bool:
    """Return whether ``pid`` is live without sending it a signal.

    ``os.kill(pid, 0)`` is a Unix liveness probe.  It is not portable to
    Windows: this runtime raises ``WinError 87`` for signal zero, which caused
    the local provider to reclaim locks held by live processes.  Access-denied
    handles deliberately fail closed because the provider must never reclaim a
    lease it cannot prove is stale.
    """
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    import ctypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return ctypes.get_last_error() == error_access_denied
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


class LocalFileRunStore(RunStore):
    """
    Local filesystem-backed reference RunStore.
    Manages run vaults and manifests under RUN_LOG_DIR with safe path resolution
    and append-only manifest immutability.
    """

    def __init__(self, log_dir: str | Path | None = None):
        self._custom_log_dir = Path(log_dir).resolve() if log_dir else None
        if self._custom_log_dir:
            self._custom_log_dir.mkdir(parents=True, exist_ok=True)

    @property
    def log_dir(self) -> Path:
        if self._custom_log_dir is not None:
            return self._custom_log_dir
        base = config.RUN_LOG_DIR
        if isinstance(base, Path):
            base.mkdir(parents=True, exist_ok=True)
            return base
        res = Path(base).resolve()
        res.mkdir(parents=True, exist_ok=True)
        return res

    @property
    def base_dir(self) -> Path:
        return self.log_dir

    def _get_run_vault(self, run_id: str, create: bool = False) -> Path:
        vault = SafeRunPathResolver.resolve_run_dir(self.log_dir, run_id, create=create)
        # Complete an interrupted certification before any read or competing
        # mutation observes a partially published terminal state.
        if vault.exists():
            self._recover_pending_certification(vault)
        return vault

    @staticmethod
    def _lease_path(run_vault: Path) -> Path:
        return run_vault / ".certification.lease"

    @staticmethod
    def _commit_journal_path(run_vault: Path) -> Path:
        return run_vault / ".certification.commit.json"

    @staticmethod
    def _lease_expired(payload: dict[str, Any]) -> bool:
        try:
            return float(payload.get("expires_at", 0)) <= time.time()
        except (TypeError, ValueError):
            return True

    @staticmethod
    def _write_bytes_durable(path: Path, content: bytes) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        with open(temporary, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(5):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt < 4:
                    time.sleep(0.01 * (attempt + 1))
                    continue
                raise
        LocalFileRunStore._sync_directory(path.parent)

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        """Persist rename/unlink metadata when the host filesystem supports it."""
        try:
            descriptor = os.open(str(directory), os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            # Windows commonly does not allow fsync on a directory.  The
            # individual file writes above remain durable; providers with a
            # stronger transactional substrate implement their own commit.
            pass
        finally:
            os.close(descriptor)

    @classmethod
    def _unlink_durable(cls, path: Path) -> None:
        path.unlink(missing_ok=True)
        cls._sync_directory(path.parent)

    @classmethod
    def _write_json_durable(cls, path: Path, value: dict[str, Any]) -> None:
        cls._write_bytes_durable(
            path, json.dumps(value, indent=2, default=str, sort_keys=True).encode("utf-8")
        )

    def _recover_pending_certification(self, run_vault: Path) -> None:
        """Finish a journaled certification commit after interruption.

        A durable journal is the local provider's commit decision.  Recovery
        never rolls it back: once recorded, it deterministically publishes the
        exact manifest and terminal seal before exposing the run to callers.
        """
        journal_path = self._commit_journal_path(run_vault)
        journal = self._read_json(journal_path)
        if journal is None:
            return
        manifest = journal.get("manifest")
        sealed_record = journal.get("sealed_record")
        if not isinstance(manifest, dict) or not isinstance(sealed_record, dict):
            raise RuntimeError("CertificationRecoveryJournalCorrupt")
        target = run_vault / "run_manifest.json"
        existing = self._read_json(target) if target.exists() else None
        expected_digest = _canonical_digest(manifest)
        if self._is_sealed(run_vault) and (
            existing is None or _canonical_digest(existing) != expected_digest
        ):
            raise RunManifestImmutableError(str(journal.get("run_id", "unknown")), target)
        # Before sealing, the journal is the durable transaction decision and
        # supersedes the execution manifest.  Certification necessarily
        # publishes a different, signed manifest; treating that difference as
        # a conflict made every first certification commit impossible.
        if existing is None or _canonical_digest(existing) != expected_digest:
            self._write_json_durable(target, manifest)
        self._write_json_durable(self._record_path(run_vault), sealed_record)
        self._write_bytes_durable(run_vault / ".run_lifecycle", b"SEALED")
        self._write_bytes_durable(run_vault / ".sealed", b"sealed\n")
        self._unlink_durable(journal_path)

    def acquire_certification_lease(
        self,
        run_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        timeout_seconds: float,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """Acquire a cross-process lease; filesystem use is provider-internal."""
        if self.get_run(run_id, context=context) is None:
            return False
        vault = self._get_run_vault(run_id, create=True)
        lease = self._lease_path(vault)
        current_lease = self._read_json(lease) if lease.exists() else None
        legacy_lock = vault / ".certification.lock"
        if current_lease is not None and self._lease_expired(current_lease):
            legacy_lock.unlink(missing_ok=True)
            try:
                self._unlink_durable(lease)
            except OSError:
                pass
        elif legacy_lock.exists():
            try:
                data = self._read_json(legacy_lock) or {}
                pid = data.get("pid")
                if pid and isinstance(pid, int):
                    if _process_is_alive(pid):
                        return False
                    legacy_lock.unlink(missing_ok=True)
            except Exception as e:
                logger.debug("Failed checking legacy lock: %s", e)
        deadline = time.monotonic() + timeout_seconds
        ttl_seconds = max(float(timeout_seconds), 60.0)
        while True:
            try:
                fd = os.open(str(lease), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                try:
                    payload = {
                        "owner_id": owner_id,
                        "fencing_token": fencing_token,
                        "run_id": run_id,
                        "expires_at": time.time() + ttl_seconds,
                    }
                    os.write(fd, json.dumps(payload, sort_keys=True).encode("utf-8"))
                    os.fsync(fd)
                finally:
                    os.close(fd)
                try:
                    legacy_payload = {
                        "run_id": run_id,
                        "pid": os.getpid(),
                        "fencing_token": fencing_token,
                        "acquired_at": time.time(),
                    }
                    legacy_lock.write_text(json.dumps(legacy_payload), encoding="utf-8")
                except OSError:
                    pass
                return True
            except FileExistsError:
                current = self._read_json(lease) or {}
                if self._lease_expired(current):
                    try:
                        self._unlink_durable(lease)
                    except OSError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.05)

    def verify_certification_lease(
        self,
        run_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        if self.get_run(run_id, context=context) is None:
            return False
        data = self._read_json(self._lease_path(self._get_run_vault(run_id))) or {}
        return (
            not self._lease_expired(data)
            and data.get("owner_id") == owner_id
            and data.get("fencing_token") == fencing_token
        )

    def renew_certification_lease(
        self,
        run_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        timeout_seconds: float,
        context: dict[str, Any] | None = None,
    ) -> bool:
        if not self.verify_certification_lease(
            run_id, owner_id=owner_id, fencing_token=fencing_token, context=context
        ):
            return False
        vault = self._get_run_vault(run_id)
        lease = self._lease_path(vault)
        payload = self._read_json(lease) or {}
        payload["expires_at"] = time.time() + max(float(timeout_seconds), 60.0)
        try:
            self._write_json_durable(lease, payload)
            return True
        except OSError:
            return False

    def release_certification_lease(
        self,
        run_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        if not self.verify_certification_lease(
            run_id, owner_id=owner_id, fencing_token=fencing_token, context=context
        ):
            return False
        try:
            self._unlink_durable(self._lease_path(self._get_run_vault(run_id)))
            legacy_lock = self._get_run_vault(run_id) / ".certification.lock"
            if legacy_lock.exists():
                legacy_lock.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def is_certification_leased(
        self, run_id: str, *, context: dict[str, Any] | None = None
    ) -> bool:
        if self.get_run(run_id, context=context) is None:
            return False
        lease = self._lease_path(self._get_run_vault(run_id))
        data = self._read_json(lease) or {}
        if self._lease_expired(data):
            try:
                self._unlink_durable(lease)
            except OSError:
                pass
            return False
        return lease.exists()

    @staticmethod
    def _record_path(run_vault: Path) -> Path:
        return run_vault / "run_record.json"

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        for attempt in range(10):
            try:
                if not path.exists():
                    # A missing sidecar (especially the certification commit
                    # journal) is the ordinary steady state.  Retrying it on
                    # every trace append imposed 550 ms of delay per event,
                    # which could prevent a run from reaching RUN_END before
                    # the acceptance timeout.  Atomic writers publish a file
                    # only after it is complete, so absence is a definitive
                    # read result rather than a transient parse condition.
                    return None
                value = json.loads(path.read_text(encoding="utf-8"))
                return value if isinstance(value, dict) else None
            except PermissionError:
                if attempt < 9:
                    time.sleep(0.01 * (attempt + 1))
                    continue
                return None
            except (OSError, ValueError, json.JSONDecodeError):
                if attempt < 9:
                    time.sleep(0.01 * (attempt + 1))
                    continue
                return None
        return None

    @staticmethod
    def _read_lifecycle_status(run_vault: Path) -> str:
        """Read the provider-owned lifecycle marker without routing through get_run."""
        marker = run_vault / ".run_lifecycle"
        try:
            raw = marker.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        if not raw:
            return ""
        try:
            decoded = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            return raw.upper()
        if isinstance(decoded, dict):
            return str(
                decoded.get("lifecycle") or decoded.get("status") or decoded.get("state") or ""
            ).upper()
        return ""

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        LocalFileRunStore._write_json_durable(path, value)

    def create_run(
        self,
        run_id: str,
        scenario_id: str,
        agent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "OPEN",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_vault = self._get_run_vault(run_id, create=True)
        record_path = self._record_path(run_vault)
        existing = self._read_json(record_path)
        if existing is not None:
            return existing
        record = {
            "run_id": run_id,
            "scenario_id": scenario_id,
            "scenario": scenario_id,
            "agent_id": agent_id,
            "metadata": metadata or {},
            "context": context or {},
            "status": status,
            "lifecycle": status,
            "created_at": datetime.now().astimezone().isoformat(),
        }
        self._write_json(record_path, record)
        return record

    @staticmethod
    def _is_sealed(run_vault: Path) -> bool:
        return (run_vault / ".sealed").exists() or (run_vault / "trace_seal.json").exists()

    def get_run(self, run_id: str, context: dict[str, Any] | None = None) -> dict[str, Any] | None:
        from eval_runner.console.auth_manager import context_allows_record

        try:
            run_vault = self._get_run_vault(run_id, create=False)
        except (ValueError, PermissionError):
            run_vault = None

        corrupted_manifest = False
        manifest_path = run_vault / "run_manifest.json" if run_vault else None
        if manifest_path and manifest_path.exists():
            manifest_data = self._read_json(manifest_path)
            if manifest_data is None:
                corrupted_manifest = True
                manifest_data = {}
            elif isinstance(manifest_data, dict) and "config_revision" not in manifest_data:
                exec_m = manifest_data.get("execution_manifest")
                if isinstance(exec_m, dict):
                    meta = exec_m.get("metadata")
                    if isinstance(meta, dict) and "config_revision" in meta:
                        manifest_data["config_revision"] = meta["config_revision"]
        else:
            manifest_data = None

        if run_vault and run_vault.exists() and run_vault.is_dir():
            record = self._read_json(self._record_path(run_vault))
            lifecycle_marker = run_vault / ".run_lifecycle"
            marker_status = None
            if lifecycle_marker.exists():
                try:
                    if lifecycle_marker.is_dir():
                        return {
                            "run_id": run_id,
                            "status": "INVALID",
                            "lifecycle": "INVALID",
                            "corrupted": True,
                        }
                    marker_val = lifecycle_marker.read_text(encoding="utf-8").strip()
                    if marker_val:
                        try:
                            parsed_marker = json.loads(marker_val)
                            if isinstance(parsed_marker, dict):
                                marker_status = (
                                    parsed_marker.get("lifecycle")
                                    or parsed_marker.get("status")
                                    or parsed_marker.get("state")
                                    or "INVALID"
                                )
                            else:
                                marker_status = "INVALID"
                        except (ValueError, json.JSONDecodeError):
                            marker_status = marker_val
                    else:
                        marker_status = "INVALID"
                except OSError:
                    return {
                        "run_id": run_id,
                        "status": "INVALID",
                        "lifecycle": "INVALID",
                        "corrupted": True,
                    }

            if record is None:
                if self._is_sealed(run_vault):
                    record = {
                        "run_id": run_id,
                        "status": "SEALED",
                        "lifecycle": "SEALED",
                        "manifest": manifest_data or {},
                    }
                elif corrupted_manifest:
                    record = {
                        "run_id": run_id,
                        "status": "INVALID",
                        "lifecycle": "INVALID",
                        "manifest": {},
                        "corrupted": True,
                    }
                elif marker_status:
                    record = {
                        "run_id": run_id,
                        "status": marker_status,
                        "lifecycle": marker_status,
                    }
                elif manifest_data is not None:
                    record = {
                        "run_id": run_id,
                        "status": "SEALED" if self._is_sealed(run_vault) else "OPEN",
                        "context": manifest_data.get("context")
                        or manifest_data.get("metadata", {}).get("runtime_context", {})
                        or manifest_data,
                    }
                else:
                    trace_path = run_vault / "run.jsonl"
                    if not trace_path.exists():
                        return None
                    try:
                        with trace_path.open(encoding="utf-8") as f:
                            first_line = ""
                            for line in f:
                                stripped = line.strip()
                                if stripped:
                                    first_line = stripped
                                    break
                            if not first_line:
                                return None
                            first_ev = self._read_event(first_line)
                            if not first_ev:
                                return None
                            record = {
                                "run_id": run_id,
                                "status": "SEALED" if self._is_sealed(run_vault) else "OPEN",
                            }
                    except (OSError, UnicodeDecodeError):
                        return None
            elif marker_status and record.get("status") != marker_status:
                record["status"] = marker_status
                record["lifecycle"] = marker_status

            if self._is_sealed(run_vault):
                record["status"] = "SEALED"
                record["lifecycle"] = "SEALED"

            if context:
                if not context_allows_record(record, context):
                    return None
                if manifest_data is not None:
                    manifest_scope = manifest_data.get("context")
                    if not isinstance(manifest_scope, dict):
                        metadata = manifest_data.get("metadata")
                        manifest_scope = (
                            metadata.get("runtime_context") if isinstance(metadata, dict) else None
                        )
                    if not isinstance(manifest_scope, dict):
                        execution_manifest = manifest_data.get("execution_manifest")
                        manifest_scope = (
                            execution_manifest.get("scope")
                            if isinstance(execution_manifest, dict)
                            else None
                        )
                    # A run record is the provider's authoritative scope
                    # ownership.  A manifest that does not repeat scope must
                    # not make that owned run disappear; an explicitly scoped
                    # manifest must still agree with the caller scope.
                    if isinstance(manifest_scope, dict) and not context_allows_record(
                        {"context": manifest_scope}, context
                    ):
                        return None

            trace_path = self._resolve_trace_file(run_id) or (run_vault / "run.jsonl")
            scenario = record.get("scenario") or record.get("scenario_id")
            if not scenario and manifest_data:
                scenario = (
                    manifest_data.get("scenario_id")
                    or manifest_data.get("scenario")
                    or manifest_data.get("metadata", {}).get("scenario_id")
                    or manifest_data.get("metadata", {}).get("scenario")
                )
            timestamp = record.get("timestamp") or record.get("created_at")
            if not timestamp and manifest_data:
                timestamp = manifest_data.get("timestamp") or manifest_data.get("created_at")

            if (not scenario or not timestamp) and trace_path.exists():
                try:
                    with trace_path.open(encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                ev = self._read_event(line)
                                if ev:
                                    data_obj = (
                                        ev.get("data") if isinstance(ev.get("data"), dict) else {}
                                    )
                                    if not scenario:
                                        scenario = (
                                            ev.get("scenario")
                                            or ev.get("scenario_id")
                                            or data_obj.get("scenario")
                                        )
                                    if not timestamp:
                                        timestamp = ev.get("timestamp") or data_obj.get("timestamp")
                                break
                except (OSError, UnicodeDecodeError):
                    pass

            if not scenario:
                scenario = _parse_scenario_from_run_id(run_id)

            return {
                **record,
                "run_id": run_id,
                "scenario": scenario or record.get("scenario", ""),
                "scenario_id": scenario or record.get("scenario_id", ""),
                "timestamp": timestamp or record.get("timestamp", ""),
                "created_at": timestamp or record.get("created_at", ""),
                "vault_path": str(run_vault),
                "has_trace": trace_path.exists(),
                "manifest": manifest_data or {},
                "sealed": self._is_sealed(run_vault),
            }

        # Check durable run index: .index/<run_id>.json
        index_file = self.log_dir / ".index" / f"{run_id}.json"
        if index_file.exists():
            index_data = self._read_json(index_file)
            if index_data is not None:
                if context and not context_allows_record(index_data, context):
                    return None
                return {
                    "run_id": run_id,
                    "scenario": index_data.get("scenario_id") or index_data.get("scenario"),
                    "scenario_id": index_data.get("scenario_id"),
                    "status": index_data.get("status", "PENDING"),
                    "lifecycle": "OPEN",
                    "created_at": index_data.get("created_at"),
                    "timestamp": index_data.get("created_at"),
                    "context": index_data.get("context", {}),
                    "provisional": True,
                    "verification_status": "NOT_EXECUTED",
                }

        # Check direct fragment: <run_id>.jsonl
        frag_file = self.log_dir / f"{run_id}.jsonl"
        candidates = (
            [frag_file]
            if frag_file.exists()
            else [p for p in self.log_dir.glob("*.jsonl") if p.name != "run.jsonl"]
        )
        for candidate in candidates:
            if not candidate.exists() or candidate.name == "run.jsonl":
                continue
            scenario = ""
            ts = ""
            found_event = False
            actual_run_id = candidate.stem
            try:
                with candidate.open(encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            data = json.loads(line)
                            found_event = True
                            actual_run_id = data.get("run_id") or actual_run_id
                            scenario = data.get("scenario") or data.get("scenario_id") or ""
                            ts = data.get("timestamp") or data.get("_ts_iso") or ""
                            if context and not context_allows_record(data, context):
                                return None
                            break
            except Exception:
                continue
            if not found_event:
                continue
            if candidate != frag_file and actual_run_id != run_id:
                continue
            if not scenario:
                scenario = _parse_scenario_from_run_id(actual_run_id)
            return {
                "run_id": actual_run_id,
                "scenario": scenario,
                "timestamp": ts,
                "has_trace": True,
                "status": "OPEN",
                "lifecycle": "OPEN",
                "_fragment_path": candidate.name,
            }

        return None

    def list_runs(
        self, limit: int = 100, offset: int = 0, context: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        from eval_runner.console.auth_manager import context_allows_record

        if not self.log_dir.exists():
            return []

        runs_map: dict[str, dict[str, Any]] = {}

        # 1. Direct fragments (*.jsonl)
        for frag in self.log_dir.glob("*.jsonl"):
            if frag.name == "run.jsonl":
                continue
            rid = frag.stem
            info = self.get_run(rid, context=context)
            if info:
                runs_map[info["run_id"]] = info

        # 2. Durable index (.index/*.json)
        index_dir = self.log_dir / ".index"
        if index_dir.is_dir():
            for idx_file in index_dir.glob("*.json"):
                rid = idx_file.stem
                if rid not in runs_map:
                    info = self.get_run(rid, context=context)
                    if info:
                        runs_map[rid] = info

        # 3. Vault folders (subdirs)
        for d in self.log_dir.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                rid = d.name
                info = self.get_run(rid, context=context)
                if info:
                    runs_map[rid] = info

        # 4. Master log file (run.jsonl directly under log_dir)
        master_log = self.log_dir / "run.jsonl"
        if master_log.exists():
            try:
                with master_log.open(encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        ev = self._read_event(line)
                        if ev and isinstance(ev, dict):
                            data_obj = ev.get("data") if isinstance(ev.get("data"), dict) else {}
                            rid = ev.get("run_id") or data_obj.get("run_id")
                            if rid and rid != "unknown" and rid not in runs_map:
                                if context and not context_allows_record(ev, context):
                                    continue
                                scen = (
                                    ev.get("scenario")
                                    or ev.get("scenario_id")
                                    or data_obj.get("scenario")
                                    or ""
                                )
                                ts = (
                                    ev.get("timestamp")
                                    or ev.get("_ts_iso")
                                    or data_obj.get("timestamp")
                                    or ""
                                )
                                runs_map[rid] = {
                                    "run_id": rid,
                                    "scenario": scen,
                                    "scenario_id": scen,
                                    "timestamp": ts,
                                    "created_at": ts,
                                    "has_trace": True,
                                    "status": ev.get("status") or data_obj.get("status") or "OPEN",
                                    "lifecycle": "OPEN",
                                    "provisional": True,
                                }
            except (OSError, UnicodeDecodeError):
                pass

        sorted_runs = sorted(
            runs_map.values(),
            key=lambda r: str(r.get("created_at") or r.get("timestamp") or ""),
            reverse=True,
        )
        return sorted_runs[offset : offset + limit]

    def search_runs(
        self,
        query: str = "",
        filters: dict[str, Any] | None = None,
        limit: int = 100,
        offset: int = 0,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        query = query.lower().strip()
        filters = filters or {}
        matches = []
        for run in self.list_runs(limit=10_000, context=context):
            haystack = " ".join(
                str(run.get(k, ""))
                for k in ("run_id", "scenario_id", "scenario", "agent_id", "status")
            )
            if query and query not in haystack.lower():
                continue
            if any(run.get(key) != value for key, value in filters.items()):
                continue
            matches.append(run)
        return matches[offset : offset + limit]

    def get_manifest(
        self, run_id: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        try:
            vault = self._get_run_vault(run_id)
        except (ValueError, PermissionError):
            return None
        if context:
            record = self._read_json(self._record_path(vault)) or {}
            if any(record.get("context", {}).get(k) not in (None, v) for k, v in context.items()):
                return None
        manifest_file = vault / "run_manifest.json"
        if manifest_file.exists():
            try:
                raw = manifest_file.read_text(encoding="utf-8")
                manifest = json.loads(raw)
                if not isinstance(manifest, dict):
                    return None
            except Exception as e:
                logger.debug("Failed reading manifest: %s", e)
                return None
        else:
            manifest = {}
        if "scenario_data" not in manifest:
            # These files are part of the local provider's immutable run
            # record.  Expose them through the provider rather than allowing
            # console consumers to inspect the vault directly.
            scenario = self._read_json(vault / "scenario_resolved.json")
            if scenario is None:
                scenario = self._read_json(vault / "scenario_original.json")
            if scenario is not None:
                manifest = {**manifest, "scenario_data": scenario}
        if "execution_manifest" not in manifest:
            exec_manifest_file = vault / "execution_manifest.json"
            if exec_manifest_file.exists():
                exec_m = self._read_json(exec_manifest_file)
                if exec_m is not None:
                    manifest = {**manifest, "execution_manifest": exec_m}
        if isinstance(manifest, dict) and "config_revision" not in manifest:
            exec_m = manifest.get("execution_manifest")
            if isinstance(exec_m, dict):
                meta = exec_m.get("metadata")
                if isinstance(meta, dict) and "config_revision" in meta:
                    manifest["config_revision"] = meta["config_revision"]
        return manifest or None

    get_run_manifest = get_manifest

    def _resolve_trace_file(self, run_id: str) -> Path | None:
        try:
            vault = self._get_run_vault(run_id)
            for cand in [vault / "run.jsonl", vault / f"{run_id}.jsonl"]:
                if cand.is_file():
                    return cand
        except (ValueError, PermissionError):
            pass
        frag = self.log_dir / f"{run_id}.jsonl"
        if frag.is_file():
            return frag
        return None

    def get_events(
        self, run_id: str, offset: int = 0, limit: int = 1000, context: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        if context and self.get_run(run_id, context=context) is None:
            return []
        trace = self._resolve_trace_file(run_id)
        if trace is None or not trace.exists():
            return []
        events: list[dict[str, Any]] = []
        try:
            with trace.open(encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    raw = line.strip()
                    if not raw:
                        continue
                    event = self._read_event_strict(raw, line_number)
                    events.append(event)
        except OSError:
            return []
        return events[max(offset, 0) : max(offset, 0) + max(limit, 0)]

    def get_trace_bytes(self, run_id: str, context: dict[str, Any] | None = None) -> bytes | None:
        """Return the exact trace serialization owned by this provider.

        This is deliberately exposed through the storage contract so signature
        verification never reaches around a provider to a filesystem path.
        """
        if context and self.get_run(run_id, context=context) is None:
            return None
        trace = self._resolve_trace_file(run_id)
        if trace is None:
            return None
        try:
            return trace.read_bytes() if trace.exists() else None
        except OSError:
            return None

    @staticmethod
    def _read_event_strict(line: str, line_number: int = 1) -> dict[str, Any]:
        try:
            value = json.loads(line)
        except (ValueError, json.JSONDecodeError) as exc:
            raise TraceCorruptionError(f"MalformedTraceRecord:{line_number}") from exc
        if not isinstance(value, dict):
            raise TraceCorruptionError(f"InvalidTraceRecord:{line_number}: expected object")
        return value

    @staticmethod
    def _read_event(line: str) -> dict[str, Any] | None:
        try:
            value = json.loads(line)
            return value if isinstance(value, dict) else None
        except (ValueError, json.JSONDecodeError):
            return None

    def append_events(
        self, run_id: str, events: list[dict[str, Any]], context: dict[str, Any] | None = None
    ) -> int:
        if not events:
            return 0
        run_vault = self._get_run_vault(run_id, create=True)
        if self._read_json(self._record_path(run_vault)) is None:
            self.create_run(run_id, scenario_id="unknown", context=context)
        record = self._read_json(self._record_path(run_vault)) or {}
        if str(record.get("status", "OPEN")).upper() in {
            "PAUSED_FOR_APPROVAL",
            "FINALIZING",
            "SEALED",
        }:
            raise RunManifestImmutableError(run_id, run_vault)
        if self._is_sealed(run_vault):
            raise RunManifestImmutableError(run_id, run_vault)
        trace = run_vault / "run.jsonl"
        # Persist exactly the canonical bytes exposed by ``get_trace_bytes``.
        # A verifier signs those bytes directly; recreating JSONL later from
        # event objects would permit whitespace/key-order drift.
        from agentv_runtime.canonical import canonical_json_encode

        with trace.open("ab") as stream:
            for event in events:
                stream.write(canonical_json_encode(event))
                stream.write(b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        self._sync_directory(trace.parent)
        return len(events)

    def stream_events(
        self, run_id: str, from_seq: int = 0, context: dict[str, Any] | None = None
    ) -> Generator[dict[str, Any], None, None]:
        yield from self.get_events(run_id, offset=from_seq, limit=10_000_000, context=context)

    def update_run_status(
        self,
        run_id: str,
        status: str,
        details: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> bool:
        run_vault = self._get_run_vault(run_id, create=True)
        record = self._read_json(self._record_path(run_vault))
        if record is None:
            record = self.create_run(run_id, scenario_id="unknown", context=context)
        if context and any(
            record.get("context", {}).get(k) not in (None, v) for k, v in context.items()
        ):
            return False
        record.update(
            {
                "status": status,
                "lifecycle": status,
                "updated_at": datetime.now().astimezone().isoformat(),
            }
        )
        if details:
            record["status_details"] = details
        self._write_json_durable(self._record_path(run_vault), record)
        try:
            self._write_bytes_durable(run_vault / ".run_lifecycle", status.encode("utf-8"))
        except OSError:
            return False
        if status == "SEALED":
            try:
                self._write_bytes_durable(run_vault / ".sealed", b"sealed\n")
            except OSError:
                return False
        return True

    def seal(self, run_id: str, metadata: dict[str, Any] | None = None) -> None:
        """Mark the run as sealed, enforcing cryptographic immutability."""
        self.update_run_status(run_id, "SEALED", details=metadata)

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

    def save_run_manifest(
        self, run_id: str, manifest: dict[str, Any], context: dict[str, Any] | None = None
    ) -> str:
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

        lifecycle = self._read_lifecycle_status(run_vault)
        if lifecycle == "FINALIZING":
            raise RunManifestImmutableError(run_id, target)

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

    def commit_certification(
        self,
        run_id: str,
        manifest: dict[str, Any],
        *,
        owner_id: str,
        fencing_token: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """Commit the signed manifest and terminal seal under the provider lease.

        This reference implementation keeps its filesystem mechanics private.
        It stages every mutable record before publishing the irreversible
        ``.sealed`` marker, and rejects a divergent retry once a manifest has
        been published.  Database providers implement the same contract in a
        single transaction; Runtime never depends on their implementation.
        """
        if not self.verify_certification_lease(
            run_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            context=context,
        ):
            return False
        vault = self._get_run_vault(run_id, create=False)
        record = self._read_json(self._record_path(vault))
        if record is None or (
            context
            and any(record.get("context", {}).get(k) not in (None, v) for k, v in context.items())
        ):
            return False
        target = vault / "run_manifest.json"
        incoming_digest = _canonical_digest(manifest)
        existing = self._read_json(target) if target.exists() else None
        if self._is_sealed(vault):
            return existing is not None and _canonical_digest(existing) == incoming_digest

        sealed_record = {
            **record,
            "status": "SEALED",
            "lifecycle": "SEALED",
            "updated_at": datetime.now().astimezone().isoformat(),
        }
        journal = {
            "version": 1,
            "run_id": run_id,
            "manifest": manifest,
            "sealed_record": sealed_record,
            "manifest_digest": incoming_digest,
        }
        try:
            # This is the durable commit decision.  Any interruption after
            # this write is recovered forward to the same sealed evidence.
            self._write_json_durable(self._commit_journal_path(vault), journal)
            self._recover_pending_certification(vault)
            for _ in range(10):
                published = self._read_json(target)
                if (
                    self._is_sealed(vault)
                    and published is not None
                    and (_canonical_digest(published) == incoming_digest)
                ):
                    return True
                time.sleep(0.02)
            return (
                self._is_sealed(vault)
                and published is not None
                and (_canonical_digest(published) == incoming_digest)
            )
        except OSError:
            return False

    def delete_run(self, run_id: str, context: dict[str, Any] | None = None) -> bool:
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
