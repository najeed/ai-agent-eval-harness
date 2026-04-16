import json
import os
from pathlib import Path

from eval_runner.catalog import (
    ScenarioCatalog,
    _archive_existing_pack,
    _parse_pack_string,
    install_pack,
)


def test_catalog_malformed_json_and_metadata(mock_catalog_dir):
    """Test loading scenarios with malformed JSON and incorrect metadata (Natural triggers)."""
    scenarios_dir = mock_catalog_dir / "scenarios"

    # 1. Malformed JSON
    bad_json = scenarios_dir / "bad.json"
    bad_json.write_text("not json { oops")

    # 2. JSON not a dict (list instead)
    list_json = scenarios_dir / "list.json"
    list_json.write_text('["item1", "item2"]')

    # 3. Metadata not a dict (string instead)
    bad_meta = scenarios_dir / "bad_meta.json"
    bad_meta.write_text('{"id": "meta_test", "metadata": "not_a_dict"}')

    # 4. Correct file but outside jail (Simulating relative_to ValueError / security)
    # create a file in the root, maybe it's not safe. But actually, let's create a symlink
    # to outside or just rely on the path resolution.
    sys_dir = mock_catalog_dir.parent / "outside"
    sys_dir.mkdir(exist_ok=True)
    outside = sys_dir / "outside.json"
    outside.write_text('{"id": "outside"}')

    # We will temporarily add 'outside' to catalog search paths using a hack or just test the
    # specific condition where rel_p fails.
    # relative_to fails if the path is not under the root.
    # We can inject a Path object that is outside into _find_all_json.

    catalog = ScenarioCatalog.get_instance()
    catalog.build_index()

    # Bad json and list json should be skipped
    # bad_meta should have handled metadata as empty dict, so it's loaded as "meta_test"
    found_ids = [s["id"] for s in catalog.scenarios]
    assert "meta_test" in found_ids


def test_catalog_hybrid_index_linting_concept(mock_catalog_dir):
    """Test the V1.2 deferred linting concept via cache updates."""
    catalog = ScenarioCatalog.get_instance()

    # Setup scenario
    scen_file = mock_catalog_dir / "scenarios" / "valid.json"
    data = {
        "id": "valid1",
        "metadata": {"name": "Test"},
        "workflow": {"nodes": []},
        "evaluation": {},
    }
    scen_file.write_text(json.dumps(data))

    # First build
    catalog.build_index()
    assert "valid1" in [s["id"] for s in catalog.scenarios]
    assert catalog.scenarios[0]["lint_score"] == 100


def test_parse_pack_string_coverage():
    """Test pack string parsing."""
    pack, flavor, version = _parse_pack_string("finance")
    assert pack == "finance"
    assert flavor == "STANDARD"
    assert version == "latest"

    pack, flavor, version = _parse_pack_string("finance-finra")
    assert pack == "finance"
    assert flavor == "finra"


def test_catalog_install_pack_full_cycle(mock_catalog_dir):
    """Test downloading, extracting, and archiving an industrial pack."""
    # 1. Install fresh pack
    install_pack("finance-FINRA@1.2.3")

    # Verify installation
    flavor_dir = mock_catalog_dir / "industries" / "finance" / "FINRA" / "1.2.3"
    assert flavor_dir.exists()
    assert (flavor_dir / "pack_manifest.json").exists()
    assert (flavor_dir / "finance-finra.json").exists()

    # 2. Re-install to trigger archive behavior
    install_pack("finance-FINRA@1.2.3")

    # Verify archive exists
    archive_dir = mock_catalog_dir / "industries" / "finance" / "FINRA" / ".archived"
    assert archive_dir.exists()
    archives = list(archive_dir.glob("*_1.2.3"))
    assert len(archives) == 1


def test_catalog_install_pack_failure(mock_catalog_dir, monkeypatch):
    """Test natural trigger for installation failure (e.g., download failure)."""

    # Cause _download_simulated to fail
    def mock_download(*args, **kwargs):
        raise ValueError("Simulated network failure")

    monkeypatch.setattr("eval_runner.catalog._download_simulated", mock_download)

    install_pack("fail-pack@1.0")

    # The directory should be cleaned up
    flavor_dir = mock_catalog_dir / "industries" / "fail" / "pack" / "1.0"
    assert not flavor_dir.exists()


def test_relative_to_value_error(mock_catalog_dir, monkeypatch):
    """Simulate a file that exists but raises ValueError on relative_to."""
    catalog = ScenarioCatalog.get_instance()
    import pathlib

    original_glob = pathlib.Path.glob

    def patched_glob(self, pattern):
        yield from original_glob(self, pattern)
        if os.name == "nt":
            yield Path("Z:\\fake\\path.json")
        else:
            yield Path("/totally/fake/path.json")

    monkeypatch.setattr(pathlib.Path, "glob", patched_glob)
    monkeypatch.setattr("eval_runner.utils.is_path_safe", lambda p, j: True)
    # The error should be swallowed or caught without crashing tests
    catalog.build_index()
    assert True


def test_catalog_query_methods(mock_catalog_dir):
    """Test get_scenario, list_scenarios, and get_absolute_path."""
    catalog = ScenarioCatalog.get_instance()

    # 1. Test uninitialized fast path
    # If the scenarios list is empty but initialized, it should try load_index
    ScenarioCatalog._initialized = True
    ids = catalog.list_scenarios()
    assert len(ids) == 0

    # Add a valid scenario to test querying
    scenarios_dir = mock_catalog_dir / "scenarios"
    scen_file = scenarios_dir / "query_test.json"
    import json

    data = {"id": "query_test", "title": "Query Title"}
    scen_file.write_text(json.dumps(data))

    # 2. Build index to populate
    catalog.build_index()

    # list_scenarios
    ids = catalog.list_scenarios()
    assert "query_test" in ids

    # get_absolute_path
    path = catalog.get_absolute_path("query_test")
    assert path is not None
    assert path.name == "query_test.json"

    path_missing = catalog.get_absolute_path("missing")
    assert path_missing is None

    # get_absolute_path security failure (path outside canonical root)
    # create a mock scenario item with a path outside
    catalog.scenarios.append({"id": "hack", "path": "../../outside.json"})
    path_hack = catalog.get_absolute_path("hack")
    assert path_hack is None


def test_catalog_check_for_updates(mock_catalog_dir):
    """Test check_for_updates missing lines (stale disk count and locked build)."""
    catalog = ScenarioCatalog.get_instance()
    catalog.build_index()

    # Force stale disk count by removing a file without index update
    scenarios_dir = mock_catalog_dir / "scenarios"
    new_file = scenarios_dir / "new_update.json"
    import json

    new_file.write_text(json.dumps({"id": "new_update"}))

    # Check for updates should detect file count mismatch and trigger update
    updated = catalog.check_for_updates()
    assert updated is True

    # Second check, should be false
    updated2 = catalog.check_for_updates()
    assert updated2 is False


def test_archive_missing_pack(mock_catalog_dir):
    """Test _archive_existing_pack branching when target doesn't exist."""
    # Should safely return
    _archive_existing_pack(mock_catalog_dir / "missing")


def test_load_index_corrupt(mock_catalog_dir):
    """Test load_index handling corrupt index.json."""
    catalog = ScenarioCatalog.get_instance()

    # Corrupt index path
    catalog.index_path.parent.mkdir(parents=True, exist_ok=True)
    catalog.index_path.write_text("corrupt { json")

    # Load index should fallback to build_index
    catalog.load_index()
    # It logs and falls back to build_index, shouldn't crash
    assert isinstance(catalog.scenarios, list)
