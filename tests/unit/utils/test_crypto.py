"""
tests/unit/utils/test_crypto.py

100% branch and line coverage for eval_runner/utils/crypto.py.

Tests verify:
- Both modes of content_hash() (fixed SHA3-256 and XOF SHAKE-256)
- file_hash() streaming correctness
- shake256_digest() raw-bytes output
- record_id() short identifier contract
- checksum() full-length contract
- All edge cases: empty input, str vs bytes equivalence, length variants
- Module-level constant correctness
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from eval_runner.utils.crypto import (
    CHECKSUM_LENGTH,
    DIGEST_LENGTH,
    HASH_ALGORITHM,
    RECORD_ID_LENGTH,
    checksum,
    content_hash,
    file_hash,
    record_id,
    shake256_digest,
)

# ---------------------------------------------------------------------------
# content_hash()
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_str_input_produces_sha3_256(self):
        result = content_hash("hello")
        expected = hashlib.sha3_256(b"hello").hexdigest()
        assert result == expected

    def test_bytes_input_produces_sha3_256(self):
        result = content_hash(b"hello")
        assert result == hashlib.sha3_256(b"hello").hexdigest()

    def test_str_and_bytes_equivalent(self):
        assert content_hash("agentv") == content_hash(b"agentv")

    def test_fixed_output_is_64_hex_chars(self):
        result = content_hash("test data")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_xof_mode_str_input(self):
        result = content_hash("hello", length=16)
        expected = hashlib.shake_256(b"hello").digest(16).hex()
        assert result == expected

    def test_xof_mode_bytes_input(self):
        result = content_hash(b"hello", length=16)
        assert result == hashlib.shake_256(b"hello").digest(16).hex()

    def test_xof_output_length_8(self):
        result = content_hash("x", length=8)
        assert len(result) == 16  # 8 bytes = 16 hex chars

    def test_xof_output_length_32(self):
        result = content_hash("x", length=32)
        assert len(result) == 64  # 32 bytes = 64 hex chars

    def test_xof_output_length_64(self):
        result = content_hash("x", length=64)
        assert len(result) == 128  # 64 bytes = 128 hex chars

    def test_xof_prefix_consistency(self):
        """SHAKE-256 is an XOF: shorter outputs are prefixes of longer ones."""
        r8 = content_hash("data", length=8)
        r32 = content_hash("data", length=32)
        assert r32.startswith(r8)

    def test_empty_string(self):
        result = content_hash("")
        assert len(result) == 64
        assert result == hashlib.sha3_256(b"").hexdigest()

    def test_empty_bytes(self):
        result = content_hash(b"")
        assert len(result) == 64

    def test_empty_xof(self):
        result = content_hash("", length=8)
        assert len(result) == 16

    def test_deterministic(self):
        assert content_hash("same") == content_hash("same")

    def test_different_inputs_differ(self):
        assert content_hash("abc") != content_hash("abd")

    def test_sha3_256_not_sha2(self):
        """Ensure we're not accidentally using SHA-256."""
        data = b"sentinel"
        sha2 = hashlib.sha256(data).hexdigest()
        sha3 = content_hash(data)
        assert sha2 != sha3


# ---------------------------------------------------------------------------
# file_hash()
# ---------------------------------------------------------------------------


class TestFileHash:
    def test_matches_sha3_256_single_pass(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"agentv harness integrity")
        result = file_hash(f)
        expected = hashlib.sha3_256(b"agentv harness integrity").hexdigest()
        assert result == expected

    def test_streaming_large_file_matches(self, tmp_path: Path):
        """Chunked streaming must produce same digest as single-pass."""
        content = b"x" * 100_000  # well above the 8192-byte chunk boundary
        f = tmp_path / "big.bin"
        f.write_bytes(content)
        result = file_hash(f)
        expected = hashlib.sha3_256(content).hexdigest()
        assert result == expected

    def test_output_is_64_hex(self, tmp_path: Path):
        f = tmp_path / "file.bin"
        f.write_bytes(b"\x00" * 64)
        result = file_hash(f)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        result = file_hash(f)
        assert result == hashlib.sha3_256(b"").hexdigest()

    def test_binary_file(self, tmp_path: Path):
        content = bytes(range(256))
        f = tmp_path / "binary.bin"
        f.write_bytes(content)
        assert file_hash(f) == hashlib.sha3_256(content).hexdigest()

    def test_different_files_differ(self, tmp_path: Path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_bytes(b"file one")
        f2.write_bytes(b"file two")
        assert file_hash(f1) != file_hash(f2)

    def test_not_sha2(self, tmp_path: Path):
        f = tmp_path / "sentinel.txt"
        f.write_bytes(b"check")
        sha2 = hashlib.sha256(b"check").hexdigest()
        assert file_hash(f) != sha2


# ---------------------------------------------------------------------------
# shake256_digest()
# ---------------------------------------------------------------------------


class TestShake256Digest:
    def test_returns_bytes(self):
        result = shake256_digest(b"data")
        assert isinstance(result, bytes)

    def test_default_length_is_digest_length(self):
        result = shake256_digest(b"data")
        assert len(result) == DIGEST_LENGTH  # 32 bytes

    def test_custom_length(self):
        result = shake256_digest(b"data", length=64)
        assert len(result) == 64

    def test_custom_length_8(self):
        result = shake256_digest(b"data", length=8)
        assert len(result) == 8

    def test_matches_hashlib_directly(self):
        data = b"shake test vector"
        expected = hashlib.shake_256(data).digest(32)
        assert shake256_digest(data) == expected

    def test_prefix_consistency(self):
        data = b"xof test"
        short = shake256_digest(data, length=8)
        long = shake256_digest(data, length=32)
        assert long[:8] == short

    def test_empty_bytes(self):
        result = shake256_digest(b"")
        assert len(result) == DIGEST_LENGTH

    def test_not_sha3_256_bytes(self):
        """shake256_digest returns SHAKE-256 bytes, not SHA3-256."""
        data = b"distinguish"
        sha3 = bytes.fromhex(hashlib.sha3_256(data).hexdigest())
        shake = shake256_digest(data)
        assert sha3 != shake


# ---------------------------------------------------------------------------
# record_id()
# ---------------------------------------------------------------------------


class TestRecordId:
    def test_is_16_hex_chars(self):
        rid = record_id("unique-key-12345")
        assert len(rid) == 16

    def test_only_hex_chars(self):
        rid = record_id("test")
        assert all(c in "0123456789abcdef" for c in rid)

    def test_str_and_bytes_equivalent(self):
        assert record_id("hello") == record_id(b"hello")

    def test_deterministic(self):
        assert record_id("same") == record_id("same")

    def test_different_inputs_differ(self):
        assert record_id("key-1") != record_id("key-2")

    def test_matches_content_hash_xof_8(self):
        data = "reference data"
        assert record_id(data) == content_hash(data, length=RECORD_ID_LENGTH)

    def test_empty_input(self):
        rid = record_id("")
        assert len(rid) == 16

    def test_not_truncated_sha256(self):
        """record_id must not be a SHA-256 truncation."""
        data = "record"
        sha256_truncated = hashlib.sha256(data.encode()).hexdigest()[:16]
        assert record_id(data) != sha256_truncated


# ---------------------------------------------------------------------------
# checksum()
# ---------------------------------------------------------------------------


class TestChecksum:
    def test_is_64_hex_chars(self):
        cs = checksum("some data")
        assert len(cs) == 64

    def test_only_hex_chars(self):
        cs = checksum("test")
        assert all(c in "0123456789abcdef" for c in cs)

    def test_str_and_bytes_equivalent(self):
        assert checksum("hello") == checksum(b"hello")

    def test_deterministic(self):
        assert checksum("abc") == checksum("abc")

    def test_different_inputs_differ(self):
        assert checksum("abc") != checksum("abd")

    def test_matches_content_hash_default(self):
        data = "reference"
        assert checksum(data) == content_hash(data)

    def test_matches_sha3_256(self):
        data = "verify algo"
        assert checksum(data) == hashlib.sha3_256(data.encode()).hexdigest()

    def test_empty_input(self):
        cs = checksum("")
        assert len(cs) == 64

    def test_not_sha256(self):
        data = "sentinel"
        sha256 = hashlib.sha256(data.encode()).hexdigest()
        assert checksum(data) != sha256


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_hash_algorithm_is_sha3_256(self):
        assert HASH_ALGORITHM == "sha3_256"

    def test_digest_length_is_32(self):
        assert DIGEST_LENGTH == 32

    def test_record_id_length_is_8(self):
        assert RECORD_ID_LENGTH == 8

    def test_checksum_length_is_32(self):
        assert CHECKSUM_LENGTH == 32

    def test_constants_are_consistent(self):
        """CHECKSUM_LENGTH and DIGEST_LENGTH should agree."""
        assert CHECKSUM_LENGTH == DIGEST_LENGTH
