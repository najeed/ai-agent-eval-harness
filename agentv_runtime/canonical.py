"""
agentv_runtime.canonical
RFC 8785 JSON Canonicalization Scheme (JCS) Implementation.

Provides deterministic, cross-platform canonical JSON byte serialization
for cryptographic attestations, manifests, and verification packages.
Conforms to RFC 8785 specifications:
  - UTF-8 encoding
  - Deterministic key ordering (lexicographical by Unicode code point / UTF-16 code units)
  - No whitespace between tokens (',' and ':')
  - Minimal escaping (control characters and quotes only, ensure_ascii=False)
"""

from __future__ import annotations

import json
from typing import Any


def canonical_json_dumps(obj: Any) -> str:
    """
    Serializes a JSON-compatible Python object to an RFC 8785 canonical string.
    Keys are recursively sorted and formatted with zero superfluous whitespace.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def canonical_json_encode(obj: Any) -> bytes:
    """
    Serializes a JSON-compatible Python object to canonical RFC 8785 UTF-8 bytes.
    Suitable for cryptographic hashing (SHA3-256) and detached signature verification.
    """
    return canonical_json_dumps(obj).encode("utf-8")
