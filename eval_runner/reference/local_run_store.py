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
        return SafeRunPathResolver.resolve_run_dir(self.log_dir, run_id, create=create)

    @staticmethod
    def _record_path(run_vault: Path) -> Path:
        return run_vault / "run_record.json"

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
        temporary.replace(path)

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
                            first_line = f.readline()
                            if not first_line or not first_line.strip():
                                return None
                            first_ev = self._read_event(first_line.strip())
                            if not first_ev:
                                return None
                    except (OSError, UnicodeDecodeError):
                        return None
                    record = {
                        "run_id": run_id,
                        "status": "SEALED" if self._is_sealed(run_vault) else "OPEN",
                    }
            elif marker_status and record.get("status") != marker_status:
                record["status"] = marker_status
                record["lifecycle"] = marker_status

            if context:
                if not context_allows_record(record, context):
                    return None
                if manifest_data is not None and not context_allows_record(manifest_data, context):
                    return None

            trace_path = run_vault / "run.jsonl"
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
        return self._read_json(vault / "run_manifest.json")

    def get_events(
        self, run_id: str, offset: int = 0, limit: int = 1000, context: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        if context and self.get_run(run_id, context=context) is None:
            return []
        try:
            trace = self._get_run_vault(run_id) / "run.jsonl"
        except (ValueError, PermissionError):
            return []
        if not trace.exists():
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

    @staticmethod
    def _read_event_strict(line: str, line_number: int = 1) -> dict[str, Any]:
        try:
            value = json.loads(line)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"MalformedTraceRecord:{line_number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"InvalidTraceRecord:{line_number}: expected object")
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
        with trace.open("a", encoding="utf-8") as stream:
            for event in events:
                stream.write(json.dumps(event, default=str, separators=(",", ":")) + "\n")
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
        self._write_json(self._record_path(run_vault), record)
        try:
            (run_vault / ".run_lifecycle").write_text(status, encoding="utf-8")
        except OSError:
            pass
        if status == "SEALED":
            (run_vault / ".sealed").touch(exist_ok=True)
        return True

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
