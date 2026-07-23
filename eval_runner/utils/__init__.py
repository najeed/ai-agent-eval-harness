"""
eval_runner.utils

Industrial utilities package for the AgentV harness.
Maintains backward compatibility for legacy imports.
"""

from pathlib import Path
from typing import Any

from .base import (
    INDUSTRY_MAPPING,
    deep_diff,
    generate_id,
    get_canonical_path,
    is_path_safe,
    normalize_industry,
    normalize_uri,
    rmtree_resilient,
    safe_run_async,
)
from .crypto import checksum, content_hash, file_hash, record_id, shake256_digest
from .path_resolver import PathResolver

__all__ = [
    "INDUSTRY_MAPPING",
    "normalize_industry",
    "is_path_safe",
    "get_canonical_path",
    "normalize_uri",
    "safe_run_async",
    "rmtree_resilient",
    "generate_id",
    "deep_diff",
    "PathResolver",
    "Path",
    "Any",
    # Crypto utilities (SHA-3 family)
    "checksum",
    "content_hash",
    "file_hash",
    "record_id",
    "shake256_digest",
]
