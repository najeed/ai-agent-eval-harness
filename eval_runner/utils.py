"""
utils.py

Architectural utilities for the MultiAgentEval harness.
"""

import os
from pathlib import Path
from typing import Union


def is_path_safe(target: Union[str, Path], base: Union[str, Path]) -> bool:
    """
    Industrial Path-Traversal Protection (Symlink-Hardened).
    Ensures that the target path (after full resolution) remains strictly within the base directory jail.
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
