"""
eval_runner.utils.crypto
========================

Canonical cryptographic hash utilities for the AgentV harness.

Unified SHA-3 family (FIPS 202):
  - sha3_256  — fixed 256-bit output for integrity hashing, checksums, fingerprints.
  - shake_256 — XOF (extendable output) for signing pre-images and variable-length IDs.

All hashing in the harness MUST route through this module so that algorithm
changes require a single-file edit and nothing else.

Design notes:
  - SHA3-256 is structurally immune to length-extension attacks (sponge construction).
  - SHAKE-256 is the required pre-hash XOF for ML-DSA-65 (FIPS 204) Zero-Exposure Signing.
  - Neither SHA-256 (legacy) nor BLAKE3 (not FIPS-approved) should be used in new code.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# ---------------------------------------------------------------------------
# Module-level constants — the single source of truth for algorithm identity
# ---------------------------------------------------------------------------

#: Algorithm identifier embedded in VC manifests and audit records.
HASH_ALGORITHM: str = "sha3_256"

#: Default output length for fixed-mode hashing (SHA3-256 → 32 bytes → 64 hex chars).
DIGEST_LENGTH: int = 32

#: Short output for record IDs (8 bytes → 16 hex chars).
RECORD_ID_LENGTH: int = 8

#: Full output for checksums (32 bytes → 64 hex chars).
CHECKSUM_LENGTH: int = 32


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def content_hash(data: bytes | str, *, length: int | None = None) -> str:
    """
    Canonical hash function for the AgentV harness.

    Two modes:
    - **Fixed** (``length=None``, default): SHA3-256, returns 64 hex characters.
      Use for: integrity hashing, checksums, fingerprints, state IDs.
    - **Variable** (``length=N``): SHAKE-256 XOF, returns ``2*N`` hex characters.
      Use for: signing pre-images (ML-DSA-65), short record identifiers.

    Args:
        data: Content to hash. ``str`` inputs are UTF-8 encoded automatically.
        length: If set, activates SHAKE-256 XOF mode with this many output **bytes**.

    Returns:
        Lowercase hex string of the digest.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")

    if length is not None:
        return hashlib.shake_256(data).digest(length).hex()

    return hashlib.sha3_256(data).hexdigest()


def file_hash(file_path: Path) -> str:
    """
    SHA3-256 streaming hash of a file.

    Reads in 8 KiB chunks for O(1) memory regardless of file size.
    Drop-in replacement for the legacy ``compute_file_hash()`` in forensics.py.

    Args:
        file_path: Absolute path to the file to hash.

    Returns:
        64-char lowercase hex SHA3-256 digest.
    """
    h = hashlib.sha3_256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def shake256_digest(data: bytes, *, length: int = DIGEST_LENGTH) -> bytes:
    """
    SHAKE-256 XOF digest — returns raw **bytes**, not hex.

    This is the correct pre-image function for Zero-Exposure Signing (ZES)
    with ML-DSA-65 (FIPS 204). The resulting bytes are passed directly to
    the PQC signing provider; only the digest leaves the trust boundary.

    Args:
        data: Raw bytes to hash.
        length: Number of output bytes. Defaults to 32 (256-bit).

    Returns:
        ``length`` bytes of SHAKE-256 output.
    """
    h = hashlib.shake_256()
    h.update(data)
    return h.digest(length)


def record_id(data: bytes | str) -> str:
    """
    Generate a compact 16-hex-char record identifier via SHAKE-256.

    Replaces the legacy pattern ``hashlib.sha256(x).hexdigest()[:16]``.
    Using SHAKE-256 XOF is semantically correct: truncating SHA3-256 is not
    equivalent to requesting a shorter output from an XOF.

    Args:
        data: Content to derive the ID from.

    Returns:
        16-char lowercase hex string (8 bytes of SHAKE-256 output).
    """
    return content_hash(data, length=RECORD_ID_LENGTH)


def checksum(data: bytes | str) -> str:
    """
    Full 64-hex-char SHA3-256 integrity checksum.

    Replaces the legacy pattern ``hashlib.sha256(x).hexdigest()``.

    Args:
        data: Content to checksum.

    Returns:
        64-char lowercase hex SHA3-256 digest.
    """
    return content_hash(data)
