"""
test_path_resolver.py

Industrial test suite for the PathResolver resolution engine.
"""

from eval_runner.utils import PathResolver


def test_resolve_simple_dot():
    data = {"a": {"b": 1}}
    assert PathResolver.resolve(data, "a.b") == 1
    assert PathResolver.resolve(data, "a.c") is None


def test_resolve_bracket_string():
    data = {"a": {"b": 1}}
    assert PathResolver.resolve(data, "a['b']") == 1
    assert PathResolver.resolve(data, 'a["b"]') == 1
    assert (
        PathResolver.resolve(data, "a[b]") == 1
    )  # Pattern handles unquoted internal keys for simplicity


def test_resolve_numeric_index():
    data = {"a": [10, 20, 30]}
    assert PathResolver.resolve(data, "a[0]") == 10
    assert PathResolver.resolve(data, "a[1]") == 20
    assert PathResolver.resolve(data, "a[5]") is None


def test_resolve_mixed_complex():
    data = {
        "tables": {
            "users": [
                {"id": 1, "email": "user1@example.com"},
                {"id": 2, "email": "user2@example.com"},
            ]
        }
    }
    assert PathResolver.resolve(data, "tables.users[0].email") == "user1@example.com"
    assert PathResolver.resolve(data, "tables['users'][1].id") == 2
    assert PathResolver.resolve(data, "tables.users[2]") is None


def test_resolve_none_data():
    assert PathResolver.resolve(None, "any.path") is None


def test_resolve_empty_path():
    data = {"a": 1}
    assert PathResolver.resolve(data, "") == data


def test_resolve_leaf_exhaustion():
    data = {"a": 1}
    assert PathResolver.resolve(data, "a.b") is None


def test_resolve_invalid_types():
    data = {"a": "string"}
    # Trying to dot-access a string
    assert PathResolver.resolve(data, "a.char") is None
    # Trying to index a dict with a non-existent key
    assert PathResolver.resolve(data, "b") is None


def test_tokenize_robustness():
    path = "a.b['c d'].e[0]"
    tokens = PathResolver._tokenize(path)
    assert tokens == ["a", "b", "c d", "e", "0"]
