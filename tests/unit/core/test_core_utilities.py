"""
Consolidated Utilities Test Suite for AgentV Evaluation Harness.
Verifies support infrastructure: Loader, Config Discovery, Discovery Engine,
CLI Extensions, PathResolver, RESILIENT rmtree, and Failure Corpus.
"""

import asyncio
import json
import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from eval_runner import cli, config, discovery, failure_corpus, loader, utils
from eval_runner.utils import PathResolver

# --- 1. Loader & Validation ---


def test_loader_scenarios_rich(tmp_path):
    s_file = tmp_path / "rich.json"
    s_data = {
        "aes_version": 1.4,
        "metadata": {"id": "rich-v14", "name": "Rich", "compliance_level": "Standard"},
        "workflow": {"nodes": [{"id": "t1", "task_description": "d"}], "edges": []},
        "evaluation": {"ija_threshold": 0.8},
    }
    s_file.write_text(json.dumps(s_data))
    loaded = loader.load_scenario(s_file)
    assert loaded["metadata"]["id"] == "rich-v14"


# --- 2. Discovery & Extensions ---


def test_discovery_engine():
    """Verify class discovery in modules."""

    class Base:
        pass

    class Sub(Base):
        pass

    mock_mod = MagicMock()
    mock_mod.__name__ = "m"
    Sub.__module__ = "m"
    with patch("eval_runner.discovery.inspect.getmembers", return_value=[("Sub", Sub)]):
        found = discovery.discover_classes_in_module(mock_mod, Base, instantiate=False)
        assert Sub in found


def test_cli_extension_registration():
    """Verify EntryPoint-based CLI extensions."""
    cli._parser_cache = None
    mock_ep = MagicMock()
    mock_ep.name = "test_ext"

    def mock_reg(subparsers):
        subparsers.add_parser("ext-cmd").set_defaults(func=lambda args: 42)

    mock_ep.load.return_value = mock_reg

    with patch("importlib.metadata.entry_points", return_value=[mock_ep]):
        parser = cli.get_parser(is_help=True)
        subparsers = [a for a in parser._actions if isinstance(a, cli.argparse._SubParsersAction)][
            0
        ]
        assert "ext-cmd" in subparsers.choices


# --- 3. Path Resolver & Utilities ---


def test_path_resolver():
    data = {"users": [{"id": 1, "email": "u1@e.com"}]}
    assert PathResolver.resolve(data, "users[0].email") == "u1@e.com"


def test_utils_normalization():
    assert utils.normalize_industry("  FINTECH  ") == "finance"
    assert utils.normalize_industry(None) == "generic"


# --- 4. Config & Versioning ---


def test_config_redaction():
    data = {"api_key": "secret", "p": "v"}
    sanitized = config.RegistryManager._redact_sensitive_data(data)
    assert sanitized["api_key"] == "[REDACTED]"


# --- 5. Failure Corpus ---


def test_failure_corpus_smoke(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "run.jsonl").write_text(json.dumps({"triage_tag": "API_FAIL"}) + "\n")
    with patch("builtins.print") as mock_print:
        failure_corpus.search("api_fail")
        mock_print.assert_any_call("✅ Found 1 matching failure events:")


# --- 6. Extended Coverage ---


def test_path_safety_advanced(tmp_path, monkeypatch):
    base = tmp_path / "base"
    base.mkdir()

    # 1. Authoritative Anchoring (Absolute vs Relative vs Exact Base)
    assert utils.is_path_safe("sub/file.txt", base) is True
    assert utils.is_path_safe(base / "sub/file.txt", base) is True
    assert utils.is_path_safe(base, base) is True

    # 2. Escape Check
    assert utils.is_path_safe("../escape.txt", base) is False

    # 3. AEH_STRICT_JAIL
    temp_dir = Path(tempfile.gettempdir())

    monkeypatch.setenv("AEH_STRICT_JAIL", "1")
    assert utils.is_path_safe(temp_dir / "test.txt", base) is False

    monkeypatch.delenv("AEH_STRICT_JAIL", raising=False)
    # Zone B: System Temp
    assert utils.is_path_safe(temp_dir / "test.txt", base) is True

    # 4. Fail-Closed Resolution Error
    with patch.object(type(base), "resolve", side_effect=OSError("Resolution failure")):
        assert utils.is_path_safe("file.txt", base) is False


def test_path_safety_drive_prefix_non_windows(tmp_path):
    """
    Mutation Assurance Test: Verifies non-Windows drive prefix normalization
    (kills os.name != 'nt' -> os.name == 'nt' and '+' -> '-' mutations in base.py).
    """
    base = tmp_path / "base"
    base.mkdir()

    class FakePosixPath:
        def __init__(self, p):
            self.p = str(p)

        def is_absolute(self):
            return True

        def resolve(self):
            return self

        def __str__(self):
            return self.p

        def __truediv__(self, other):
            return FakePosixPath(self.p + "/" + str(other))

    with (
        patch("eval_runner.utils.base.os.name", "posix"),
        patch("eval_runner.utils.base.Path", FakePosixPath),
    ):
        assert utils.is_path_safe("C:/outside_jail", "/base") is False
        assert utils.is_path_safe("C:/base/safe.txt", "/base") is True

    assert utils.is_path_safe("C:/outside_jail", base) is False
    assert utils.is_path_safe(base / "safe.txt", base) is True


def test_get_canonical_path_edge():
    assert utils.get_canonical_path("") == ""
    assert utils.get_canonical_path(None) == ""


def test_normalize_uri_windows(tmp_path):
    p = Path("C:/Users/Test/file.txt")
    uri = utils.normalize_uri(p)
    assert uri == "file:///c:/Users/Test/file.txt"


def test_safe_run_async_advanced():
    async def sample_coro():
        return 42

    # 1. Standard run (no loop)
    assert utils.safe_run_async(sample_coro()) == 42

    # 2. Nested run (running loop)
    async def nested_caller():
        return utils.safe_run_async(sample_coro())

    assert asyncio.run(nested_caller()) == 42


def test_rmtree_resilient_advanced(tmp_path):
    # Missing path check
    utils.rmtree_resilient(tmp_path / "non_existent")

    # Read-only bit handle_errors
    d = tmp_path / "readonly_dir"
    d.mkdir()
    f = d / "file.txt"
    f.write_text("data")

    # Make it read-only
    os.chmod(f, stat.S_IREAD)

    # Should still delete successfully via handle_errors
    utils.rmtree_resilient(d)
    assert not d.exists()

    # Retries and Fallback
    d2 = tmp_path / "busy_dir"
    d2.mkdir()

    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise PermissionError("Busy")
        return

    with (
        patch("eval_runner.utils.base.shutil.rmtree", side_effect=side_effect),
        patch("eval_runner.utils.base.time.sleep") as mock_sleep,
    ):
        utils.rmtree_resilient(d2, retries=3, delay=1.0)
        assert call_count == 3
        from unittest.mock import call

        assert mock_sleep.call_args_list == [call(1.0), call(2.0)]

    # Test Rename Fallback
    d3 = tmp_path / "locked_dir"
    d3.mkdir(parents=True, exist_ok=True)
    with patch("eval_runner.utils.base.shutil.rmtree", side_effect=PermissionError("Always Busy")):
        with patch.object(Path, "rename") as mock_rename:
            utils.rmtree_resilient(d3, retries=1, delay=0)
            mock_rename.assert_called()


def test_deep_diff_advanced():
    # Numeric comparison
    assert utils.deep_diff(1, 1) == []

    # Types differ
    diff = utils.deep_diff({"a": 1}, {"a": "1"})
    assert any("types differ" in d for d in diff)

    # Lengths differ
    diff = utils.deep_diff([1], [1, 2])
    assert any("lengths differ" in d for d in diff)

    # List and tuple matching (kills list | tuple -> list & tuple mutation at line 185)
    assert utils.deep_diff([1, 2, 3], [1, 2, 3]) == []
    assert utils.deep_diff((1, 2), (1, 2)) == []


def test_generate_id_advanced():
    id1 = utils.generate_id("eval")
    id2 = utils.generate_id("eval")
    assert id1.startswith("eval-")
    assert id2.startswith("eval-")
    assert id1 != id2


def test_deep_diff_keys_advanced():
    diff = utils.deep_diff({"a": 1}, {})
    assert any("key missing" in d for d in diff)
    assert not any("." in d for d in diff)

    diff2 = utils.deep_diff({}, {"b": 2})
    assert any("key extra" in d for d in diff2)


def test_rmtree_resilient_rename_fallback_ignore_errors(tmp_path):
    """
    Mutation Assurance Test: Verifies shutil.rmtree(temp_name, ignore_errors=True)
    in rename fallback (kills ignore_errors=True -> False at line 142 in base.py).
    """
    d = tmp_path / "locked_dir_fallback"
    d.mkdir(parents=True, exist_ok=True)
    calls = []

    def mock_rmtree(target, onerror=None, ignore_errors=False):
        calls.append({"target": str(target), "ignore_errors": ignore_errors})
        if not ignore_errors:
            raise PermissionError("Locked file inside")

    with patch("eval_runner.utils.base.shutil.rmtree", side_effect=mock_rmtree):
        utils.rmtree_resilient(d, retries=1, delay=0)
    assert any(c["ignore_errors"] is True for c in calls)
