"""Contained, serialized and atomic persistence for console scenario edits."""

import json
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

from agentv_runtime.manifest import compute_scenario_hash

_WRITE_LOCK = threading.RLock()
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}


class ScenarioRevisionConflict(ValueError):
    def __init__(self, current_hash, expected_hash):
        super().__init__("Revision conflict: read the current scenario before updating it.")
        self.current_hash = current_hash
        self.expected_hash = expected_hash


def scenario_save_path(project_root, industry, scenario_id):
    for identifier in (industry, scenario_id):
        if (
            not isinstance(identifier, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", identifier) is None
            or identifier.upper() in _RESERVED
        ):
            raise ValueError("Invalid industry or scenario directory identifier")
    project = Path(project_root).resolve()
    root = (project / "industries").resolve()
    directory = (root / industry / "scenarios").resolve()
    target = (directory / f"{scenario_id}.json").resolve()
    if (
        not root.is_relative_to(project)
        or not directory.is_relative_to(root)
        or not target.is_relative_to(directory)
    ):
        raise ValueError("Scenario path is outside the scenario directory")
    return target


@contextmanager
def _directory_write_lock(directory):
    # The thread lock covers same-process callers; the OS lock covers workers.
    # Keep the lock inode stable across atomic replacement of scenario files.
    with _WRITE_LOCK:
        directory.mkdir(parents=True, exist_ok=True)
        lock_path = directory / ".scenario-write.lock"
        if lock_path.resolve() != lock_path:
            raise ValueError("Scenario lock path must not be redirected")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def write_scenario(path, data, expected_revision, *, preserve_status=True):
    """Compare one durable revision and replace it while holding the writer lock."""
    with _directory_write_lock(path.parent):
        try:
            with path.open(encoding="utf-8") as stream:
                current = json.load(stream)
            if not isinstance(current, dict):
                raise ValueError("Stored scenario must be a JSON object")
        except FileNotFoundError:
            current = None
        # All other read/parse/hash errors propagate; none permits an overwrite.
        current_hash = compute_scenario_hash(current) if current is not None else None
        if (current is not None and not expected_revision) or expected_revision != current_hash:
            raise ScenarioRevisionConflict(current_hash, expected_revision)
        metadata = data.setdefault("metadata", {})
        if preserve_status:
            metadata["status"] = (
                (current.get("metadata") or {}).get("status") or current.get("status") or "Draft"
                if current is not None
                else "Draft"
            )
        scenario_hash = compute_scenario_hash(data)
        metadata["content_hash"] = scenario_hash
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return scenario_hash
