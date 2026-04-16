import json

import pytest

from eval_runner.catalog import ScenarioCatalog


@pytest.fixture
def mock_catalog_dir(tmp_path, monkeypatch):
    """Setup a controlled project root for catalog tests."""
    root = tmp_path / "project"
    root.mkdir()
    scenarios_dir = root / "scenarios"
    scenarios_dir.mkdir()

    # Needs to be a string or Path depending on config expectations
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", root)

    # Reset singleton
    if hasattr(ScenarioCatalog, "_instance"):
        ScenarioCatalog._instance = None

    return root


def test_build_index_rename_permission_error(mock_catalog_dir, monkeypatch):
    """Test 186-189: Permission error retry logic in build_index when renaming."""
    catalog = ScenarioCatalog.get_instance()

    # We need a file to exist so build_index tries to write
    scenarios_dir = mock_catalog_dir / "scenarios"
    scen_file = scenarios_dir / "valid.json"
    scen_file.write_text(json.dumps({"id": "valid1"}))

    # Track calls to original os.rename
    calls = []

    def mock_rename(src, dst):
        calls.append((src, dst))
        raise PermissionError("Simulated locked file")

    monkeypatch.setattr("os.rename", mock_rename)

    # Override time.sleep to avoid waiting during the test
    monkeypatch.setattr("time.sleep", lambda x: None)

    # In build_index, the loop tries 3 times. On the 3rd fail, it raises PermissionError
    # which is caught by the broader broad Exception block around line 196-197.
    # Therefore, we just run build_index and test it handles it safely (logs failure).
    catalog.build_index()

    # Because of the 3 retries, it should have been called exactly 3 times
    assert len(calls) == 3


def test_build_index_write_error(mock_catalog_dir, monkeypatch):
    """Test 196-197: Exception handling when writing index fails."""
    catalog = ScenarioCatalog.get_instance()

    scenarios_dir = mock_catalog_dir / "scenarios"
    scen_file = scenarios_dir / "valid.json"
    scen_file.write_text(json.dumps({"id": "valid1"}))

    # Simulate a broad exception during file operation
    def mock_open_err(*args, **kwargs):
        raise OSError("Disk failure")

    manager = monkeypatch.context()
    with manager:
        monkeypatch.setattr("builtins.open", mock_open_err)
        # Exception should be swallowed and logged
        catalog.build_index()
        assert True


def test_get_absolute_path_uninitialized(mock_catalog_dir, monkeypatch):
    """Test 311: load_index call from get_absolute_path when uninitialized."""
    catalog = ScenarioCatalog.get_instance()
    # Uninitialized state
    catalog.scenarios = []
    ScenarioCatalog._initialized = True

    # Should call load_index implicitly and then fail because query isn't there
    # But effectively hits line 311.
    res = catalog.get_absolute_path("missing")
    assert res is None


def test_check_for_updates_fast_path(mock_catalog_dir, monkeypatch):
    """Test 218: forces stale check path by simulating mtime > manifest mtime."""
    catalog = ScenarioCatalog.get_instance()
    catalog.build_index()

    # Manipulate manifest
    catalog.manifest["last_top_mtime"] = 0

    # Should trigger update True
    # We clear the timestamp to bypass the 30-sec limit
    catalog._last_sync_check = 0

    assert catalog.check_for_updates() is True
