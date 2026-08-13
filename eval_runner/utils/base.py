"""
utils.py

Architectural utilities for the AgentV harness.
"""

import os
import shutil
import stat
import time
from pathlib import Path
from typing import Any

INDUSTRY_MAPPING = {
    "fintech": "finance",
    "medtech": "healthcare",
    "telecommunications": "telecom",
    "media_entertainment": "media_and_entertainment",
    "industrial": "manufacturing",
}


def normalize_industry(industry: str) -> str:
    """Normalizes industry identifier to the AES standard."""
    if not industry:
        return "generic"
    clean_industry = str(industry).lower().strip().replace(" ", "_")
    return INDUSTRY_MAPPING.get(clean_industry, clean_industry)


def is_path_safe(target: str | Path, base: str | Path) -> bool:
    """
    Industrial Path-Traversal Protection (Symlink-Hardened).
    Ensures that the target path (after full resolution) remains strictly within the jail.
    Default: Allows access to system temp directories for CI/CD compatibility.
    Strict: Opt-in via AEH_STRICT_JAIL=1 to block external temp access.
    """
    import os
    import re
    import tempfile

    try:
        raw_target = str(target).replace("\\", "/")
        raw_base = str(base).replace("\\", "/")
        if os.name != "nt" and re.search("(?:^|/)(?:[a-zA-Z]:|//)", raw_target):
            raw_target = "/" + re.sub("^(?:.*/)?(?:[a-zA-Z]:|//+)", "", raw_target).lstrip("/")
        is_raw_relative = not Path(raw_target).is_absolute()
        target_p = Path(raw_target)
        if is_raw_relative:
            target_p = Path(raw_base) / target_p
        target_path = target_p.resolve()
        base_path = Path(raw_base).resolve()
        temp_dir = Path(tempfile.gettempdir()).resolve()
        target_str = str(target_path).lower().replace("\\", "/").rstrip("/")
        base_str = str(base_path).lower().replace("\\", "/").rstrip("/")
        temp_str = str(temp_dir).lower().replace("\\", "/").rstrip("/")
        if target_str == base_str or target_str.startswith(f"{base_str}/"):
            return True

        if is_raw_relative:
            return False

        if os.environ.get("AEH_STRICT_JAIL") != "1":
            if target_str == temp_str or target_str.startswith(f"{temp_str}/"):
                return True

        return False
    except Exception as e:
        import sys

        sys.stderr.write(f"   [Utils] CRITICAL: Path resolution error (Fail-Closed): {e}\n")
        return False


def get_canonical_path(path_str: str) -> str:
    """
    Normalizes a path string for industrial cross-platform consistency.
    """
    if not path_str:
        return ""
    return path_str.lower().replace("\\", "/")


def normalize_uri(p: Path) -> str:
    """Industrial-grade URI normalization for Windows (Lower-case drive letters)."""
    posix_path = p.as_posix()
    if ":" in posix_path:
        drive, rest = posix_path.split(":", 1)
        posix_path = f"{drive.lower()}:{rest}"
    return f"file:///{posix_path}"


def safe_run_async(coro):
    """
    Industrial-grade async runner (v2.0).
    Supports execution from sync contexts even when an event loop is already running
    in the current thread (common in pytest-asyncio and industrial CI).
    """
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()


def rmtree_resilient(path: str | Path, retries: int = 5, delay: float = 0.2):
    """
    Industrial-grade directory removal.
    Resolves common Windows WinError 145/PermissionError races during teardown.
    """
    p = Path(path)
    if not p.exists():
        return

    def handle_errors(func, path, exc_info):
        """On-error handler to fix read-only bits (common in industrial repos)."""
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception as e:
            import sys

            sys.stderr.write(f"   [Utils] Warning: Failed to force R/W bits on {path}: {e}\n")

    for attempt in range(retries):
        try:
            shutil.rmtree(p, onerror=handle_errors)
            return
        except (PermissionError, OSError):
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                try:
                    temp_name = p.parent / f"{p.name}.deleted.{int(time.time())}"
                    p.rename(temp_name)
                    shutil.rmtree(temp_name, ignore_errors=True)
                except Exception as e:
                    import sys

                    sys.stderr.write(
                        f"   [Utils] Warning: Failed to remove {p} after all retries: {e}\n"
                    )


def generate_id(prefix: str = "id") -> str:
    """
    Generates a unique, sortable, and human-readable industrial ID.
    Format: {prefix}-{hex_timestamp}-{random_suffix}
    """
    import random
    import string

    timestamp = hex(int(time.time()))[2:]
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"{prefix}-{timestamp}-{suffix}"


def deep_diff(d1: Any, d2: Any, path: str = "") -> list[str]:
    """
    Computes a structural difference between two nested objects.
    Returns a list of human-readable differences.
    Used for Industrial State Parity verification (AES v1.4).
    """
    diffs = []
    if isinstance(d1, (int, float)) and isinstance(d2, (int, float)):
        pass
    elif type(d1) is not type(d2):
        diffs.append(f"{path}: types differ ({type(d1).__name__} vs {type(d2).__name__})")
        return diffs
    if isinstance(d1, dict):
        keys1 = set(d1.keys())
        keys2 = set(d2.keys())
        for k in keys1 - keys2:
            diffs.append(f"{path}.{k}: key missing in target" if path else f"{k}: key missing")
        for k in keys2 - keys1:
            diffs.append(f"{path}.{k}: key extra in target" if path else f"{k}: key extra")
        for k in keys1 & keys2:
            diffs.extend(deep_diff(d1[k], d2[k], f"{path}.{k}" if path else k))
    elif isinstance(d1, list | tuple):
        if len(d1) != len(d2):
            diffs.append(f"{path}: lengths differ ({len(d1)} vs {len(d2)})")
        else:
            for i in range(len(d1)):
                diffs.extend(deep_diff(d1[i], d2[i], f"{path}[{i}]"))
    elif d1 != d2:
        diffs.append(f"{path}: values differ ({d1!r} vs {d2!r})")
    return diffs
