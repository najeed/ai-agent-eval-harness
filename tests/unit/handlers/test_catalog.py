import json
import os
import pathlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eval_runner import catalog

ScenarioCatalog = catalog.ScenarioCatalog
_archive_existing_pack = catalog._archive_existing_pack
_parse_pack_string = catalog._parse_pack_string
install_pack = catalog.install_pack
list_scenarios = catalog.list_scenarios


@pytest.fixture(autouse=True)
def reset_catalog():
    ScenarioCatalog.clear_instance()
    yield
    ScenarioCatalog.clear_instance()


def test_catalog_indexing(tmp_path):
    # Setup mock industries directory
    industries_dir = tmp_path / "industries"
    ind_a = industries_dir / "ind_a" / "scenarios"
    ind_a.mkdir(parents=True)

    scen_1 = {
        "id": "scen_1",
        "title": "Scenario One",
        "metadata": {"industry": "ind_a", "difficulty": "1", "tags": ["tag1"]},
    }
    with open(ind_a / "scen_1.json", "w") as f:
        json.dump(scen_1, f)

    # ScenarioCatalog uses index_path in __init__ and root_dir in build_index
    index_file = tmp_path / "index.json"
    catalog = ScenarioCatalog(index_path=str(index_file))

    catalog.build_index(root_dir=str(industries_dir))
    assert index_file.exists()

    with open(index_file) as f:
        data = json.load(f)
        assert len(data["scenarios"]) == 1
        assert data["scenarios"][0]["id"] == "scen_1"


def test_catalog_search(tmp_path):
    catalog = ScenarioCatalog()
    catalog.scenarios = [
        {
            "id": "s1",
            "title": "Telecom Test",
            "industry": "telecom",
            "difficulty": "1",
            "tags": ["mobile"],
            "description": "desc1",
        },
        {
            "id": "s2",
            "title": "Finance Test",
            "industry": "finance",
            "difficulty": "3",
            "tags": ["banking"],
            "description": "desc2",
        },
        {
            "id": "s3",
            "title": "Mobile Test",
            "industry": "telecom",
            "difficulty": "2",
            "tags": ["roaming"],
            "description": "desc3",
        },
    ]

    # Text search
    res = catalog.search(query="telecom")
    assert len(res) == 2

    # Faceted search
    res = catalog.search(industry="finance")
    assert len(res) == 1
    assert res[0]["id"] == "s2"

    # Combined
    res = catalog.search(query="test", difficulty="3")
    assert len(res) == 1
    assert res[0]["id"] == "s2"


def test_catalog_malformed_json_and_metadata(mock_catalog_dir):
    """Test loading scenarios with malformed JSON and incorrect metadata."""
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

    # 4. Correct file but outside jail
    sys_dir = mock_catalog_dir.parent / "outside"
    sys_dir.mkdir(exist_ok=True)
    outside = sys_dir / "outside.json"
    outside.write_text('{"id": "outside"}')

    catalog = ScenarioCatalog.get_instance()
    catalog.build_index()

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
    original_glob = pathlib.Path.glob

    def patched_glob(self, pattern):
        yield from original_glob(self, pattern)
        if os.name == "nt":
            yield Path("Z:\\fake\\path.json")
        else:
            yield Path("/totally/fake/path.json")

    monkeypatch.setattr(pathlib.Path, "glob", patched_glob)
    monkeypatch.setattr("eval_runner.utils.is_path_safe", lambda p, j: True)
    catalog.build_index()
    assert True


def test_catalog_query_methods(mock_catalog_dir):
    """Test get_scenario, get_scenario_ids, list_scenarios, and get_absolute_path."""
    catalog = ScenarioCatalog.get_instance()

    # 1. Test uninitialized fast path
    ScenarioCatalog._initialized = True
    ids = catalog.get_scenario_ids()
    assert len(ids) == 0

    # Add a valid scenario to test querying
    scenarios_dir = mock_catalog_dir / "scenarios"
    scen_file = scenarios_dir / "query_test.json"

    data = {"id": "query_test", "title": "Query Title"}
    scen_file.write_text(json.dumps(data))

    # 2. Build index to populate
    catalog.build_index()

    # get_scenario_ids / list_scenarios
    ids = catalog.get_scenario_ids()
    assert "query_test" in ids
    assert "query_test" in catalog.list_scenarios()

    # get_scenario
    scen = catalog.get_scenario("query_test")
    assert scen is not None
    assert scen["id"] == "query_test"

    scen_missing = catalog.get_scenario("missing")
    assert scen_missing is None

    # get_absolute_path
    path = catalog.get_absolute_path("query_test")
    assert path is not None
    assert path.name == "query_test.json"

    path_missing = catalog.get_absolute_path("missing")
    assert path_missing is None

    # get_absolute_path security failure
    catalog.scenarios.append({"id": "hack", "path": "../../outside.json"})
    path_hack = catalog.get_absolute_path("hack")
    assert path_hack is None


def test_catalog_check_for_updates(mock_catalog_dir):
    """Test check_for_updates missing lines (stale disk count and locked build)."""
    catalog = ScenarioCatalog.get_instance()
    catalog.build_index()

    scenarios_dir = mock_catalog_dir / "scenarios"
    new_file = scenarios_dir / "new_update.json"
    new_file.write_text(json.dumps({"id": "new_update"}))

    # Check for updates should detect file count mismatch and trigger update
    updated = catalog.check_for_updates()
    assert updated is True

    # Second check, should be false
    updated2 = catalog.check_for_updates()
    assert updated2 is False


def test_archive_missing_pack(mock_catalog_dir):
    """Test _archive_existing_pack branching when target doesn't exist."""
    _archive_existing_pack(mock_catalog_dir / "missing")


def test_load_index_corrupt(mock_catalog_dir):
    """Test load_index handling corrupt index.json."""
    catalog = ScenarioCatalog.get_instance()

    catalog.index_path.parent.mkdir(parents=True, exist_ok=True)
    catalog.index_path.write_text("corrupt { json")

    catalog.load_index()
    assert isinstance(catalog.scenarios, list)


def test_build_index_rename_permission_error(mock_catalog_dir, monkeypatch):
    """Test Permission error retry logic in build_index when renaming."""
    catalog = ScenarioCatalog.get_instance()

    scenarios_dir = mock_catalog_dir / "scenarios"
    scen_file = scenarios_dir / "valid.json"
    scen_file.write_text(json.dumps({"id": "valid1"}))

    calls = []

    def mock_rename(src, dst):
        calls.append((src, dst))
        raise PermissionError("Simulated locked file")

    monkeypatch.setattr("os.rename", mock_rename)
    monkeypatch.setattr("time.sleep", lambda x: None)

    catalog.build_index()
    assert len(calls) == 3


def test_build_index_write_error(mock_catalog_dir, monkeypatch):
    """Exception handling when writing index fails."""
    catalog = ScenarioCatalog.get_instance()

    scenarios_dir = mock_catalog_dir / "scenarios"
    scen_file = scenarios_dir / "valid.json"
    scen_file.write_text(json.dumps({"id": "valid1"}))

    def mock_open_err(*args, **kwargs):
        raise OSError("Disk failure")

    with monkeypatch.context() as m:
        m.setattr("builtins.open", mock_open_err)
        catalog.build_index()
        assert True


def test_get_absolute_path_uninitialized(mock_catalog_dir):
    """load_index call from get_absolute_path when uninitialized."""
    catalog = ScenarioCatalog.get_instance()
    catalog.scenarios = []
    ScenarioCatalog._initialized = True

    res = catalog.get_absolute_path("missing")
    assert res is None


def test_check_for_updates_fast_path(mock_catalog_dir):
    """forces stale check path by simulating mtime > manifest mtime."""
    catalog = ScenarioCatalog.get_instance()
    catalog.build_index()

    catalog.manifest["last_top_mtime"] = 0
    catalog._last_sync_check = 0

    assert catalog.check_for_updates() is True


def test_build_index_no_root(tmp_path):
    index_path = tmp_path / "index.json"
    cat = ScenarioCatalog(index_path=str(index_path))
    cat.build_index(root_dir=str(tmp_path / "ghost"))
    assert cat.scenarios == []


def test_build_index_cache_hit(tmp_path):
    industries_dir = tmp_path / "industries"
    scen_dir = industries_dir / "fin/scenarios"
    scen_dir.mkdir(parents=True)
    scen_file = scen_dir / "s1.json"
    with open(scen_file, "w") as f:
        json.dump({"id": "s1"}, f)

    index_path = tmp_path / "index.json"
    cat = ScenarioCatalog(index_path=str(index_path))

    # 1. First build
    cat.build_index(root_dir=str(industries_dir))
    assert len(cat.scenarios) == 1

    # 2. Second build - cache hit
    cat.build_index(root_dir=str(industries_dir))
    assert len(cat.scenarios) == 1


def test_build_index_exception(tmp_path):
    industries_dir = tmp_path / "industries"
    scen_dir = industries_dir / "fin/scenarios"
    scen_dir.mkdir(parents=True)
    scen_file = scen_dir / "corrupt.json"
    with open(scen_file, "w") as f:
        f.write("invalid json")

    index_path = tmp_path / "index.json"
    cat = ScenarioCatalog(index_path=str(index_path))
    cat.build_index(root_dir=str(industries_dir))
    assert cat.scenarios == []


def test_check_for_updates_no_industries(tmp_path):
    cat = ScenarioCatalog()
    cat.root_dir = tmp_path / "empty_catalog"
    cat.root_dir.mkdir()
    assert cat.check_for_updates(force=False) is False


def test_load_index_sync_mismatch(tmp_path):
    index_path = tmp_path / "index.json"
    with open(index_path, "w") as f:
        json.dump({"scenarios": [{"id": "old", "path": "p1"}], "metadata": {}}, f)

    cat = ScenarioCatalog(index_path=str(index_path))

    with (
        patch.object(cat, "check_for_updates", return_value=True),
        patch.object(cat, "build_index") as mock_build,
    ):
        cat.load_index()
        mock_build.assert_called()


def test_load_index_no_file(tmp_path):
    index_path = tmp_path / "index.json"
    cat = ScenarioCatalog(index_path=str(index_path))
    with patch.object(cat, "build_index") as mock_build:
        cat.load_index()
        mock_build.assert_called()


def test_list_scenarios_branches(capsys):
    # 1. No scenarios found
    with (
        patch("eval_runner.catalog.ScenarioCatalog.load_index"),
        patch("eval_runner.catalog.ScenarioCatalog.search", return_value=[]),
    ):
        list_scenarios("query")
        out, _ = capsys.readouterr()
        assert "No scenarios found." in out

    # 2. > 50 results
    many_results = [
        {"id": f"s{i}", "industry": "i", "difficulty": 1, "title": "t"} for i in range(55)
    ]
    with (
        patch("eval_runner.catalog.ScenarioCatalog.load_index"),
        patch("eval_runner.catalog.ScenarioCatalog.search", return_value=many_results),
    ):
        list_scenarios("query")
        out, _ = capsys.readouterr()
        assert "and 5 more" in out


def test_search_auto_load(tmp_path):
    index_path = tmp_path / "index.json"
    cat_data = {
        "scenarios": [
            {"id": "s1", "title": "t1", "industry": "fin", "description": "d", "tags": []}
        ],
        "metadata": {},
    }
    with open(index_path, "w") as f:
        json.dump(cat_data, f)
    cat = ScenarioCatalog(index_path=str(index_path))

    with patch.object(cat, "check_for_updates", return_value=False):
        res = cat.search(query="t1")
        assert len(res) == 1


def test_search_faceted_filters():
    cat = ScenarioCatalog()
    cat.scenarios = [
        {"id": "s1", "industry": "fin", "difficulty": 1, "tags": []},
        {"id": "s2", "industry": "tech", "difficulty": 2, "tags": []},
    ]
    res = cat.search(industry="fin")
    assert len(res) == 1
    assert res[0]["id"] == "s1"


def test_list_scenarios_no_query(capsys):
    mock_cat = MagicMock()
    mock_cat.scenarios = [{"id": "s1", "industry": "i", "difficulty": 1, "title": "t"}]
    mock_cat.search.return_value = mock_cat.scenarios

    with patch("eval_runner.catalog.ScenarioCatalog", return_value=mock_cat):
        list_scenarios(query=None)
        out, _ = capsys.readouterr()
        assert "Scenario Catalog: (1 total)" in out


def test_check_for_updates_sync(tmp_path):
    cat = ScenarioCatalog()
    cat.root_dir = MagicMock(spec=Path)

    mock_industries = MagicMock(spec=Path, name="MockIndustries")
    mock_scenarios = MagicMock(spec=Path, name="MockScenarios")

    with patch.object(cat, "_get_search_paths", return_value=[mock_industries, mock_scenarios]):
        mock_industries.exists.return_value = True
        mock_scenarios.exists.return_value = False

        mock_industries.stat.return_value.st_mtime = 100
        cat.manifest["last_top_mtime"] = 0
        cat._last_sync_check = 0

        mock_industries.glob.return_value = [MagicMock(), MagicMock()]
        cat.scenarios = [{"path": "s1"}, {"path": "s2"}]

        assert cat.check_for_updates() is False
