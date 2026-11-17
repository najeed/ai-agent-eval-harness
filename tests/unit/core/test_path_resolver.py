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


def test_resolve_list_string_index():
    data = {"items": [1, 2, 3]}
    assert PathResolver.resolve(data, "items.non_integer") is None
    assert PathResolver.resolve(data, "items[non_integer]") is None


def test_resolve_custom_error_container():
    class ErrorDict(dict):
        def __contains__(self, key):
            raise TypeError("boom")

        def get(self, key, default=None):
            raise TypeError("boom")

    err_dict = ErrorDict()
    assert PathResolver.resolve(err_dict, "foo") is None
    assert PathResolver.resolve_with_existence(err_dict, "foo") == (False, None)


def test_tokenize_none_val(monkeypatch):
    from unittest.mock import MagicMock

    mock_match = MagicMock()
    mock_match.group.return_value = None
    monkeypatch.setattr(
        "eval_runner.utils.path_resolver.re.compile",
        lambda *args, **kwargs: MagicMock(finditer=lambda s: [mock_match]),
    )
    assert PathResolver._tokenize("anything") == []


def test_resolve_with_existence_all_branches():
    data = {"a": {"b": 1, "c": None}, "list": [10, 20], "num": 42}

    # Empty path & None data
    assert PathResolver.resolve_with_existence(data, "") == (True, data)
    assert PathResolver.resolve_with_existence(None, "") == (False, None)
    assert PathResolver.resolve_with_existence(None, "a.b") == (False, None)

    # Invalid / empty tokens
    assert PathResolver.resolve_with_existence(data, "$$$") == (False, None)

    # Dict access
    assert PathResolver.resolve_with_existence(data, "a.b") == (True, 1)
    assert PathResolver.resolve_with_existence(data, "a.c") == (True, None)
    assert PathResolver.resolve_with_existence(data, "a.missing") == (False, None)

    # List access
    assert PathResolver.resolve_with_existence(data, "list[0]") == (True, 10)
    assert PathResolver.resolve_with_existence(data, "list[5]") == (False, None)
    assert PathResolver.resolve_with_existence(data, "list.not_an_index") == (False, None)

    # Primitive continuation
    assert PathResolver.resolve_with_existence(data, "num.property") == (False, None)
