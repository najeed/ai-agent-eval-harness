"""
agentv_runtime.canonical
RFC 8785 JSON Canonicalization Scheme (JCS) Implementation.

Provides deterministic, cross-platform canonical JSON byte serialization
for cryptographic attestations, manifests, and verification packages.
Fully conforms to RFC 8785 specifications:
  - UTF-8 encoding
  - Deterministic key ordering (lexicographical by UTF-16 code units)
  - No whitespace between tokens (',' and ':')
  - Minimal escaping (quotation mark, reverse solidus, and control characters 0x00..0x1F only)
  - ECMAScript-compatible (ECMA-262 7.1.12.1) number serialization (I-JSON compliant)
  - Rejection of non-finite numbers (NaN, Infinity) and lone surrogates
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

# Precomputed escape table for control characters 0x00-0x1F
_CONTROL_ESCAPES: dict[int, str] = {
    0x08: r"\b",
    0x09: r"\t",
    0x0A: r"\n",
    0x0C: r"\f",
    0x0D: r"\r",
}
for c in range(0x20):
    if c not in _CONTROL_ESCAPES:
        _CONTROL_ESCAPES[c] = f"\\u{c:04x}"


def _escape_string(s: str) -> str:
    """
    Serializes a string according to RFC 8785 Section 3.2.2.2.
    Only quote, reverse solidus, and control characters U+0000..U+001F are escaped.
    All other Unicode characters are preserved literally in UTF-8 without escaping.
    Lone surrogates are rejected per I-JSON constraints.
    """
    chars: list[str] = ['"']
    for ch in s:
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            raise ValueError(f"Invalid Unicode string: lone surrogate U+{code:04X} detected")
        if ch == '"':
            chars.append(r"\"")
        elif ch == "\\":
            chars.append(r"\\")
        elif code < 0x20:
            chars.append(_CONTROL_ESCAPES[code])
        else:
            chars.append(ch)
    chars.append('"')
    return "".join(chars)


def _serialize_number(val: int | float) -> str:
    """
    Serializes numbers according to RFC 8785 Section 3.2.2.3 and ECMA-262 Section 7.1.12.1.
    - Integers: standard decimal representation
    - Negative zero (-0.0) serialized as "0"
    - Floats: ECMAScript shortest-representation decimal or exponential notation
    - NaN and +/-Infinity raise ValueError
    """
    if math.isnan(val) or math.isinf(val):
        raise ValueError(f"RFC 8785 non-finite number violation: {val} is not permitted in JSON")

    if isinstance(val, int) and not isinstance(val, bool):
        return str(val)

    # Float handling
    if val == 0.0:
        return "0"

    sign = "-" if math.copysign(1.0, val) < 0 else ""
    abs_val = abs(val)
    r = repr(abs_val)

    if "e" in r or "E" in r:
        mantissa, exp_s = r.lower().split("e")
        exp = int(exp_s)
        if "." in mantissa:
            ip, fp = mantissa.split(".")
            digits = ip + fp
            n = exp + len(ip)
        else:
            digits = mantissa
            n = exp + len(mantissa)
    else:
        ip, fp = r.split(".")
        if fp == "0":
            digits = ip
            n = len(ip)
        else:
            digits = (ip + fp).lstrip("0")
            if ip != "0":
                n = len(ip)
            else:
                n = -(len(fp) - len(fp.lstrip("0")))

    k = len(digits)
    if k <= n <= 21:
        res = digits + "0" * (n - k)
    elif 0 < n <= 21:
        res = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        res = "0." + "0" * (-n) + digits
    else:
        if k == 1:
            base = digits
        else:
            base = digits[0] + "." + digits[1:]
        exp_val = n - 1
        exp_sign = "+" if exp_val >= 0 else "-"
        res = f"{base}e{exp_sign}{abs(exp_val)}"

    return sign + res


def canonical_json_dumps(obj: Any) -> str:
    """
    Serializes a JSON-compatible Python object to an RFC 8785 canonical string.
    Keys are sorted by UTF-16 code units and formatted with zero superfluous whitespace.
    """
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, (int, float)):
        return _serialize_number(obj)
    if isinstance(obj, str):
        return _escape_string(obj)
    if isinstance(obj, (list, tuple)) and not isinstance(obj, (bytes, bytearray)):
        inner = ",".join(canonical_json_dumps(item) for item in obj)
        return f"[{inner}]"
    if isinstance(obj, Mapping):
        # RFC 8785 property ordering: UTF-16 code unit lexicographical order
        def _utf16_key(k: Any) -> bytes:
            if not isinstance(k, str):
                msg = f"RFC 8785 error: object keys must be strings, got {type(k).__name__}"
                raise TypeError(msg)
            return k.encode("utf-16-be")

        sorted_keys = sorted(obj.keys(), key=_utf16_key)
        pairs: list[str] = []
        for k in sorted_keys:
            k_escaped = _escape_string(k)
            v_serialized = canonical_json_dumps(obj[k])
            pairs.append(f"{k_escaped}:{v_serialized}")
        return "{" + ",".join(pairs) + "}"

    raise TypeError(f"RFC 8785 unsupported type: {type(obj).__name__}")


def canonical_json_encode(obj: Any) -> bytes:
    """
    Serializes a JSON-compatible Python object to canonical RFC 8785 UTF-8 bytes.
    Suitable for cryptographic hashing (SHA3-256) and detached signature verification.
    """
    return canonical_json_dumps(obj).encode("utf-8")
