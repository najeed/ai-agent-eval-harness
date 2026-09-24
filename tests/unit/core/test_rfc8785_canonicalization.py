"""
tests/unit/core/test_rfc8785_canonicalization.py

Comprehensive test suite validating RFC 8785 JSON Canonicalization Scheme (JCS)
conformance across property ordering, number serialization, escaping, and error constraints.
"""

import pytest

from agentv_runtime.canonical import canonical_json_dumps, canonical_json_encode


def test_rfc8785_utf16_code_unit_property_ordering():
    """
    RFC 8785 Section 3.2.3 requires sorting by UTF-16 code units.
    Supplementary characters (U+10000..U+10FFFF) use surrogate pairs (0xD800..0xDBFF),
    meaning they must sort BEFORE characters in U+E000..U+FFFF (like U+FFFF).
    In standard code point order (Python sorted): "\\uffff" < "\\U0001f600".
    In UTF-16 code unit order (RFC 8785): "\\U0001f600" < "\\uffff".
    """
    obj = {
        "\uffff": "high BMP",
        "\U0001f600": "supplementary plane emoji",
        "a": "ascii a",
        "\u00e9": "latin e acute",
    }
    dumped = canonical_json_dumps(obj)
    # Expected key order:
    # "a" (0x0061)
    # "\u00e9" (0x00e9)
    # "\U0001f600" (UTF-16: 0xd83d, 0xde00)
    expected = (
        '{"a":"ascii a","\u00e9":"latin e acute",'
        '"\U0001f600":"supplementary plane emoji","\uffff":"high BMP"}'
    )
    assert dumped == expected


def test_rfc8785_number_serialization():
    """
    RFC 8785 Section 3.2.2.3 requires ECMAScript 2020 Number.prototype.toString formatting.
    """
    cases = [
        (0, "0"),
        (-0.0, "0"),
        (0.0, "0"),
        (1.0, "1"),
        (-1.0, "-1"),
        (100.0, "100"),
        (-100.0, "-100"),
        (12.34, "12.34"),
        (0.00123, "0.00123"),
        (1e-6, "0.000001"),
        (-1e-6, "-0.000001"),
        (1e-7, "1e-7"),
        (-1e-7, "-1e-7"),
        (1e20, "100000000000000000000"),
        (1e21, "1e+21"),
        (1.5e23, "1.5e+23"),
        (-1.5e-7, "-1.5e-7"),
    ]
    for num, exp in cases:
        assert canonical_json_dumps(num) == exp, f"Failed for {num}"


def test_rfc8785_non_finite_numbers_fail():
    """RFC 8785 and I-JSON strictly forbid NaN and Infinity."""
    for bad_num in [float("nan"), float("inf"), float("-inf")]:
        with pytest.raises(ValueError, match="non-finite number violation"):
            canonical_json_dumps(bad_num)


def test_rfc8785_string_escaping():
    """
    RFC 8785 Section 3.2.2.2:
    Only quote, reverse solidus, and control characters 0x00..0x1F are escaped.
    Solidus (/) and literal Unicode MUST NOT be escaped.
    """
    assert canonical_json_dumps("hello/world") == '"hello/world"'
    assert canonical_json_dumps('quote: " and backslash: \\') == r'"quote: \" and backslash: \\"'
    assert canonical_json_dumps("line1\nline2\ttab\r\b\f") == r'"line1\nline2\ttab\r\b\f"'
    assert canonical_json_dumps("\x00\x1f") == r'"\u0000\u001f"'
    assert canonical_json_dumps("Hello, 世界! 🚀") == '"Hello, 世界! 🚀"'


def test_rfc8785_lone_surrogate_fails():
    """RFC 8785 forbids lone surrogates."""
    with pytest.raises(ValueError, match="lone surrogate"):
        canonical_json_dumps("\ud800")


def test_rfc8785_non_string_keys_fail():
    """Object keys must be strings."""
    with pytest.raises(TypeError, match="object keys must be strings"):
        canonical_json_dumps({123: "val"})


def test_rfc8785_structures():
    """Test nested arrays, objects, booleans, and null."""
    data = {
        "z": [1, 2.0, False, True, None],
        "a": {"c": 3, "b": "nested"},
        "empty_list": [],
        "empty_dict": {},
    }
    encoded = canonical_json_encode(data)
    expected = (
        b'{"a":{"b":"nested","c":3},"empty_dict":{},"empty_list":[],"z":[1,2,false,true,null]}'
    )
    assert encoded == expected


def test_rfc8785_ieee754_safe_integer_boundaries():
    """
    RFC 8785 & I-JSON (RFC 7493) IEEE-754 64-bit safe integer boundaries.
    Integers within [-(2**53 - 1), 2**53 - 1] ([-9007199254740991, 9007199254740991])
    must serialize accurately without precision loss across Python and JavaScript.
    """
    min_safe = -9007199254740991
    max_safe = 9007199254740991

    assert canonical_json_dumps(min_safe) == "-9007199254740991"
    assert canonical_json_dumps(max_safe) == "9007199254740991"
    assert canonical_json_dumps({"id": max_safe}) == '{"id":9007199254740991}'
    assert canonical_json_dumps({"id": min_safe}) == '{"id":-9007199254740991}'


def test_rfc8785_ieee754_unsafe_integers_fail():
    """
    Integers outside the safe IEEE-754 bounds must fail closed to prevent
    incompatible cryptographic commitments between Python and ECMAScript engines.
    """
    unsafe_high = 9007199254740992  # 2**53
    unsafe_low = -9007199254740992  # -(2**53)
    arbitrary_large = 10**30

    for unsafe_val in [unsafe_high, unsafe_low, arbitrary_large, -arbitrary_large]:
        with pytest.raises(ValueError, match="RFC 8785 / IEEE-754 integer range violation"):
            canonical_json_dumps(unsafe_val)

        with pytest.raises(ValueError, match="RFC 8785 / IEEE-754 integer range violation"):
            canonical_json_dumps({"amount": unsafe_val})


def test_rfc8785_official_spec_vectors():
    """
    Official RFC 8785 Section 3 Example Vectors:
    - Escapes and control characters
    - Property sorting
    - Whitespace stripping
    """
    # Vector: RFC 8785 Section 3.2.2.2 Escaping
    raw = {
        "\t": "tab",
        "\n": "newline",
        "\r": "return",
        '"': "quote",
        "\\": "backslash",
        "/": "solidus",
        "\u20ac": "euro",
    }
    dumped = canonical_json_dumps(raw)
    expected = (
        r'{"\t":"tab","\n":"newline","\r":"return","\"":"quote",'
        r'"/":"solidus","\\":"backslash","'
        "\u20ac"
        r'":"euro"}'
    )
    assert dumped == expected


def test_rfc8785_custom_object_with_to_dict():
    """Objects with a to_dict method serialize via to_dict."""

    class CustomPayload:
        def to_dict(self):
            return {"status": "ok", "count": 42}

    assert canonical_json_dumps(CustomPayload()) == '{"count":42,"status":"ok"}'


def test_rfc8785_unsupported_type_raises_type_error():
    """Objects without JSON/to_dict serialization raise TypeError."""

    class Unserializable:
        pass

    with pytest.raises(TypeError, match="RFC 8785 unsupported type: Unserializable"):
        canonical_json_dumps(Unserializable())


def test_rfc8785_compute_reference_hash():
    """Computes deterministic SHA3-256 digest of reference objects."""
    from agentv_runtime.canonical import compute_reference_hash

    ref1 = {"id": "ref_01", "type": "artifact", "hash": "sha3_256:abc"}
    ref2 = {"type": "artifact", "hash": "sha3_256:abc", "id": "ref_01"}

    h1 = compute_reference_hash(ref1)
    h2 = compute_reference_hash(ref2)

    assert h1.startswith("sha3_256:")
    assert h1 == h2
