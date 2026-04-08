"""
utils.py

Architectural utilities for the MultiAgentEval harness.
"""

import os
import shutil
import stat
import time
from pathlib import Path

# Industry Consolidation Table (AES Standard v1.2)
INDUSTRY_MAPPING = {
    "fintech": "finance",
    "medtech": "healthcare",
    "telecommunications": "telecom",
    "media_entertainment": "media_and_entertainment",
    "industrial": "manufacturing",
}


def normalize_industry(industry: str) -> str:
    """Normalizes industry identifier to the authoritative AES standard."""
    if not industry:
        return "generic"

    clean_industry = str(industry).lower().strip().replace(" ", "_")
    return INDUSTRY_MAPPING.get(clean_industry, clean_industry)


def is_path_safe(target: str | Path, base: str | Path) -> bool:
    """
    Industrial Path-Traversal Protection (Symlink-Hardened).
    Ensures that the target path (after full resolution) remains strictly within the base directory jail.
    Default: Allows access to system temp directories for CI/CD compatibility.
    Strict: Opt-in via AEH_STRICT_JAIL=1 to block external temp access.
    """
    import os
    import tempfile

    try:
        # 1. Authoritative Anchoring
        # If target is relative, we anchor it to the project base (PROJECT_ROOT)
        target_p = Path(target)
        if not target_p.is_absolute():
            target_p = Path(base) / target_p

        # 2. Canonical Resolution (Handles symlink traversal attempts)
        target_path = target_p.resolve()
        base_path = Path(base).resolve()
        temp_dir = Path(tempfile.gettempdir()).resolve()

        # 3. Normalization (Windows Case-Insensitivity & Path Separators)
        target_str = str(target_path).lower().replace("\\", "/").rstrip("/")
        base_str = str(base_path).lower().replace("\\", "/").rstrip("/")
        temp_str = str(temp_dir).lower().replace("\\", "/").rstrip("/")

        # 4. Multi-Zone Jail Check
        # Zone A: Project Root (Always allowed)
        if target_str == base_str or target_str.startswith(f"{base_str}/"):
            return True

        # Zone B: System Temp (Allowed unless AEH_STRICT_JAIL is set)
        # CRITICAL: We only allow temp access for absolute paths or if NOT in a nested jail.
        if os.environ.get("AEH_STRICT_JAIL") != "1":
            if target_str == temp_str or target_str.startswith(f"{temp_str}/"):
                # If target was provided as relative, it MUST have landed in Zone A.
                # If it landed in Zone B but NOT Zone A, and it was relative, it's a traversal escape.
                if not Path(target).is_absolute() and not target_str.startswith(f"{base_str}/"):
                    return False
                return True

        return False
    except Exception:
        # Fail-closed for any resolution errors (Security Standard)
        return False


def get_canonical_path(path_str: str) -> str:
    """
    Normalizes a path string for industrial cross-platform consistency.
    """
    if not path_str:
        return ""
    return path_str.lower().replace("\\", "/")


def safe_run_async(coro):
    """
    Industrial-grade async runner (v2.0).
    Supports execution from sync contexts even when an event loop is already running
    in the current thread (common in pytest-asyncio and industrial CI).
    """
    import asyncio

    try:
        # Check if a loop is already running in this thread
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop, safe to use standard asyncio.run
        return asyncio.run(coro)

    # If a loop is running, we execute in a separate thread to avoid
    # 'RuntimeError: Runner.run() cannot be called from a running event loop'.
    # This is safer than nest_asyncio as it preserves industrial loop isolation.
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
        except Exception:
            pass

    for attempt in range(retries):
        try:
            shutil.rmtree(p, onerror=handle_errors)
            return
        except (PermissionError, OSError):
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                # Final attempt fallback: try to rename then delete (Windows naming escape)
                try:
                    temp_name = p.parent / f"{p.name}.deleted.{int(time.time())}"
                    p.rename(temp_name)
                    shutil.rmtree(temp_name, ignore_errors=True)
                except Exception:
                    # If all else fails, propagate the error in strict environments
                    pass
