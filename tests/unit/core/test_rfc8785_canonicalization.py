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
