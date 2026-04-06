"""
utils.py

Architectural utilities for the MultiAgentEval harness.
"""

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
    Ensures that the target path (after full resolution) remains strictly within the base directory jail.  # noqa: E501
    """
    try:
        # Full Canonical Resolution (Handles symlink traversal attempts)
        target_path = Path(target).resolve()
        base_path = Path(base).resolve()

        # Windows Case-Insensitivity Normalization & Canonical Separators
        target_str = str(target_path).lower().replace("\\", "/").rstrip("/")
        base_str = str(base_path).lower().replace("\\", "/").rstrip("/")

        # Jail Check: Target must be equal to base or a child of base
        return target_str == base_str or target_str.startswith(f"{base_str}/")
    except Exception:
        # Fail-closed for any resolution errors (security standard)
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
    import threading
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()
