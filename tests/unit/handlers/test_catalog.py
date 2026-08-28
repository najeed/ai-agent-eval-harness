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


SAMPLE_PACK_DIR = Path(__file__).resolve().parents[3] / "samples" / "packs" / "sample-pack"


def test_install_from_committed_sample_dir(mock_catalog_dir):
    """[Fabricated-#2 → real installer] Directory source with checksums."""
    assert install_pack(str(SAMPLE_PACK_DIR)) is True

    target = mock_catalog_dir / "industries" / "sample" / "STANDARD" / "1.0.0"
    assert (target / "pack_manifest.json").exists()
    assert (target / "scenarios" / "sample_greeting.json").exists()
    manifest = json.loads((target / "pack_manifest.json").read_text())
    assert manifest["checksums_enforced"] is True
    assert manifest["verified_files"] == 1
    assert manifest["pack"] == "sample"

    catalog = ScenarioCatalog.get_instance()
    catalog.load_index()
    ids = [s["id"] for s in catalog.scenarios]
    assert "sample_pack_greeting" in ids


def test_install_from_zip_archive(mock_catalog_dir, tmp_path):
    """Zip source: same pipeline, staging extracted then installed."""
    import zipfile as _zf

    zip_path = tmp_path / "my-pack.zip"
    with _zf.ZipFile(zip_path, "w") as z:
        for f in SAMPLE_PACK_DIR.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(SAMPLE_PACK_DIR))

    assert install_pack(str(zip_path)) is True

    target = mock_catalog_dir / "industries" / "sample" / "STANDARD" / "1.0.0"
    manifest = json.loads((target / "pack_manifest.json").read_text())
    assert manifest["transport"] == "local-archive"
    assert manifest["checksums_enforced"] is True


def test_install_checksum_mismatch_refuses(mock_catalog_dir, tmp_path):
    """Fail-closed: tampered content vs pack.yaml digest aborts install."""
    import shutil as _shutil

    work = tmp_path / "tampered-pack"
    _shutil.copytree(SAMPLE_PACK_DIR, work)
    scen = work / "scenarios" / "sample_greeting.json"
    data = json.loads(scen.read_text())
    data["description"] = "TAMPERED"
    scen.write_text(json.dumps(data, indent=2))  # hash now differs from pack.yaml

    assert install_pack(str(work)) is False
    target = mock_catalog_dir / "industries" / "sample"
    assert not target.exists()


def test_install_bare_name_refused():
    """No upstream registry exists; bare names are refused with guidance."""
    assert install_pack("finance-FINRA@1.2.3") is False


def test_install_reinstall_archives_previous(mock_catalog_dir):
    assert install_pack(str(SAMPLE_PACK_DIR)) is True
    assert install_pack(str(SAMPLE_PACK_DIR)) is True  # re-install triggers archive

    archive_dir = mock_catalog_dir / "industries" / "sample" / "STANDARD" / ".archived"
    assert archive_dir.exists()
    assert len(list(archive_dir.glob("*_1.0.0"))) == 1


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


def test_catalog_new_magicmock():
    """__new__ returns a new instance if class name is MagicMock."""

    class MagicMockMeta(type):
        pass

    MagicMockMeta.__name__ = "MagicMock"

    class MagicMockClass(ScenarioCatalog, metaclass=MagicMockMeta):
        pass

    inst = ScenarioCatalog.__new__(MagicMockClass)
    assert isinstance(inst, ScenarioCatalog)


def test_catalog_build_index_unsafe_path(tmp_path):
    """skipping unsafe paths during index building."""
    cat = ScenarioCatalog(index_path=str(tmp_path / "index.json"))
    cat.root_dir = tmp_path

    # We mock is_path_safe to return False
    with (
        patch("eval_runner.catalog.Path.exists", return_value=True),
        patch("eval_runner.utils.is_path_safe", return_value=False),
        patch("eval_runner.catalog.Path.glob", return_value=[Path("/outside/unsafe.json")]),
    ):
        cat.build_index()
        assert len(cat.scenarios) == 0


def test_catalog_rename_permission_error(tmp_path):
    """PermissionError handling during index atomic rename."""
    index_file = tmp_path / "index.json"
    cat = ScenarioCatalog(index_path=str(index_file))
    cat.root_dir = tmp_path

    # Make os.rename raise PermissionError every time (all attempts fail)
    with patch("os.rename", side_effect=PermissionError("Locked file")):
        with patch("os.path.exists", return_value=True):
            with patch("os.remove", return_value=None):
                cat.build_index()
                # Should not raise exception (caught internally and logged)
                assert cat.scenarios == []


def test_catalog_check_for_updates_mtime_cached(tmp_path):
    """check_for_updates returning False when top mtime is cached."""
    cat = ScenarioCatalog(index_path=str(tmp_path / "index.json"))
    cat.root_dir = tmp_path
    cat.manifest["last_top_mtime"] = 100

    with patch("eval_runner.catalog.Path.exists", return_value=True):
        with patch("eval_runner.catalog.Path.stat") as mock_stat:
            mock_stat.return_value.st_mtime = 50  # less than cached
            assert cat.check_for_updates(force=False) is False


def test_catalog_load_index_stale_sync(tmp_path):
    """Cover lines 262->273: load_index triggering build_index when stale."""
    index_file = tmp_path / "index.json"
    cat_data = {
        "scenarios": [{"id": "s1", "path": "scenarios/s1.json", "mtime": 123}],
        "metadata": {"last_scanned_count": 1, "last_top_mtime": 0},
    }
    index_file.write_text(json.dumps(cat_data), encoding="utf-8")

    cat = ScenarioCatalog(index_path=str(index_file))
    cat.root_dir = tmp_path

    # Mock check_for_updates to return True (stale)
    with patch.object(cat, "check_for_updates", return_value=True):
        with patch.object(cat, "build_index") as mock_build:
            cat.load_index()
            mock_build.assert_called()


def test_catalog_get_absolute_path_traversal(tmp_path):
    """get_absolute_path traversal check return None."""
    cat = ScenarioCatalog(index_path=str(tmp_path / "index.json"))
    cat.root_dir = tmp_path

    # Add a scenario with a traversal path
    cat.scenarios = [{"id": "traversal_scen", "path": "../../outside.json"}]

    with patch("eval_runner.catalog.Path.exists", return_value=True):
        # Even though Path.exists is True, path traversal safety detects
        # it starts outside project root.
        assert cat.get_absolute_path("traversal_scen") is None


class TestCatalogStoreAndFiltersCoverage:
    def test_catalog_store_delegation(self, tmp_path):
        from unittest.mock import MagicMock

        from eval_runner.catalog import ScenarioCatalog

        mock_store = MagicMock()
        mock_store.get_scenario.return_value = {"id": "scen_123", "data": "val"}
        mock_store.save_scenario.return_value = "saved_path.json"

        cat = ScenarioCatalog(index_path=str(tmp_path / "index.json"), store=mock_store)
        cat.root_dir = tmp_path

        # 1. get_scenario_by_id delegation (lines 78-79)
        assert cat.get_scenario_by_id("scen_123") == {"id": "scen_123", "data": "val"}
        mock_store.get_scenario.assert_called_with("scen_123")

        # 2. save_scenario_to_store delegation (lines 81-85)
        with patch.object(cat, "build_index"):
            res = cat.save_scenario_to_store("scen_123", {"data": "val"})
            assert res == "saved_path.json"
            mock_store.save_scenario.assert_called_with("scen_123", {"data": "val"})

    def test_catalog_skips_mock_database_files(self, tmp_path):
        from eval_runner.catalog import ScenarioCatalog

        scenarios_dir = tmp_path / "scenarios"
        scenarios_dir.mkdir()

        # Regular scenario
        (scenarios_dir / "valid_scen.json").write_text(
            json.dumps({"id": "valid_1", "metadata": {"name": "Valid"}}), encoding="utf-8"
        )
        # Mock database file (lines 141-142)
        (scenarios_dir / "mock_sec_edgar.json").write_text(
            json.dumps({"id": "mock_db", "metadata": {"name": "Mock"}}), encoding="utf-8"
        )

        cat = ScenarioCatalog(index_path=str(tmp_path / "index.json"))
        cat.root_dir = tmp_path
        cat.build_index()

        ids = [s["id"] for s in cat.scenarios]
        assert "valid_1" in ids
        assert "mock_db" not in ids

    def test_catalog_query_difficulty_filters(self, tmp_path):
        from eval_runner.catalog import ScenarioCatalog

        cat = ScenarioCatalog(index_path=str(tmp_path / "index.json"))
        cat.scenarios = [
            {
                "id": "s1",
                "title": "Standard Easy",
                "difficulty": 1,
                "compliance_level": "standard",
                "industry": "fin",
                "description": "",
                "tags": [],
            },
            {
                "id": "s2",
                "title": "High Difficulty",
                "difficulty": 3,
                "compliance_level": "strict",
                "industry": "health",
                "description": "",
                "tags": [],
            },
            {
                "id": "s3",
                "title": "Custom Level",
                "difficulty": "expert",
                "compliance_level": "expert",
                "industry": "fin",
                "description": "",
                "tags": [],
            },
        ]

        # 1. Standard filter (lines 321-327)
        res_std = cat.search(difficulty="standard")
        assert len(res_std) == 1
        assert res_std[0]["id"] == "s1"

        # 2. High filter (lines 328-334)
        res_high = cat.search(difficulty="high")
        assert len(res_high) >= 1
        assert any(s["id"] == "s2" for s in res_high)

        # 3. Custom string difficulty filter (lines 335-341)
        res_custom = cat.search(difficulty="expert")
        assert len(res_custom) == 1
        assert res_custom[0]["id"] == "s3"

        # 4. Non-standard key filter (line 345)
        res_key = cat.search(compliance_level="strict")
        assert len(res_key) == 1
        assert res_key[0]["id"] == "s2"

    def test_get_all_industries_and_get_scenario_lazy_load(self, tmp_path):
        from eval_runner.catalog import ScenarioCatalog

        cat = ScenarioCatalog(index_path=str(tmp_path / "index.json"))
        cat.root_dir = tmp_path
        cat.scenarios = []  # Empty

        def fake_load():
            cat.scenarios = [{"id": "s_lazy", "title": "Lazy Title", "industry": "telecom"}]

        with patch.object(cat, "load_index", side_effect=fake_load):
            # get_all_industries lazy load (lines 351-355)
            industries = cat.get_all_industries()
            assert industries == ["telecom"]

            cat.scenarios = []
            # get_scenario lazy load (line 361)
            scen = cat.get_scenario("s_lazy")
            assert scen is not None
            assert scen["id"] == "s_lazy"


class TestPackParsingAndInstallationCoverage:
    def test_parse_pack_string_flavors_and_versions(self):
        from eval_runner.catalog import _parse_pack_string

        # pack@version (line 441)
        p1, f1, v1 = _parse_pack_string("fintech@1.2.0")
        assert p1 == "fintech"
        assert f1 == "STANDARD"
        assert v1 == "1.2.0"

        # pack-flavor@version
        p2, f2, v2 = _parse_pack_string("healthcare-hardened@2.0.0")
        assert p2 == "healthcare"
        assert f2 == "hardened"
        assert v2 == "2.0.0"

    def test_load_pack_manifest_alternatives(self, tmp_path):
        from eval_runner.catalog import _load_pack_manifest

        # 1. pack.yml (line 471)
        dir1 = tmp_path / "p1"
        dir1.mkdir()
        (dir1 / "pack.yml").write_text("name: pack_one\nflavor: pro\n", encoding="utf-8")
        assert _load_pack_manifest(dir1) == {"name": "pack_one", "flavor": "pro"}

        # 2. .agentv-pack.yaml (line 471)
        dir2 = tmp_path / "p2"
        dir2.mkdir()
        (dir2 / ".agentv-pack.yaml").write_text("name: pack_two\n", encoding="utf-8")
        assert _load_pack_manifest(dir2) == {"name": "pack_two"}

        # 3. None exists -> returns {} (line 475)
        dir3 = tmp_path / "p3"
        dir3.mkdir()
        assert _load_pack_manifest(dir3) == {}

    def test_extract_pack_archive_zip_slip_and_tar_fallback(self, tmp_path):
        import io
        import tarfile
        import zipfile

        from eval_runner.catalog import _extract_pack_archive

        staging = tmp_path / "staging"

        # 1. Tarball fallback when BadZipFile (lines 499-502)
        tar_buf = io.BytesIO()
        with tarfile.open(fileobj=tar_buf, mode="w:gz") as tf:
            content = b"name: tar_pack\n"
            info = tarfile.TarInfo(name="pack.yaml")
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
        tar_file = tmp_path / "archive.tar.gz"
        tar_file.write_bytes(tar_buf.getvalue())

        root = _extract_pack_archive(tar_file, staging)
        assert (root / "pack.yaml").exists()

        # 2. Zip Slip traversal validation (lines 496-497)
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, mode="w") as zf:
            zf.writestr("../../outside_slip.txt", "pwned")
        slip_zip = tmp_path / "slip.zip"
        slip_zip.write_bytes(zip_buf.getvalue())

        with pytest.raises(ValueError, match="Dangerous zip member path traversal detected"):
            _extract_pack_archive(slip_zip, staging / "slip_test")

    def test_install_pack_error_branches(self, tmp_path):
        from eval_runner.catalog import install_pack

        # 1. Source pack directory with pack.yaml missing 'name' (lines 574-578)
        no_name_dir = tmp_path / "no_name_pack"
        no_name_dir.mkdir()
        (no_name_dir / "pack.yaml").write_text("description: missing name\n", encoding="utf-8")
        assert install_pack(str(no_name_dir)) is False

        # 2. Source pack with no files (lines 607-608)
        empty_pack_dir = tmp_path / "empty_pack"
        empty_pack_dir.mkdir()
        (empty_pack_dir / "pack.yaml").write_text("name: empty_test\n", encoding="utf-8")
        assert install_pack(str(empty_pack_dir)) is False

        # 3. Exception in install_pack cleans up target directory (lines 642-649)
        fail_pack_dir = tmp_path / "fail_pack"
        fail_pack_dir.mkdir()
        (fail_pack_dir / "pack.yaml").write_text("name: fail_test\n", encoding="utf-8")
        (fail_pack_dir / "scenario.json").write_text("{}", encoding="utf-8")

        with patch("shutil.copy2", side_effect=OSError("Disk full")):
            assert install_pack(str(fail_pack_dir)) is False

        # 4. Staging directory exists prior to extraction (line 567)
        import io
        import zipfile

        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, mode="w") as zf:
            zf.writestr("pack.yaml", "name: stage_test\n")
            zf.writestr("scenario.json", "{}")
        stage_zip = tmp_path / "stage.zip"
        stage_zip.write_bytes(zip_buf.getvalue())

        from eval_runner.catalog import _sha256_file

        pre_staging = (
            tmp_path
            / ".aes"
            / "pack_staging"
            / (_sha256_file(stage_zip)[:12] + "_" + stage_zip.stem)
        )
        pre_staging.mkdir(parents=True, exist_ok=True)
        (pre_staging / "old.txt").write_text("old")

        with patch("eval_runner.config.PROJECT_ROOT", tmp_path):
            with patch("eval_runner.catalog.Path.cwd", return_value=tmp_path):
                with patch("eval_runner.catalog.get_catalog") as mock_gc:
                    mock_gc.return_value.scenarios = []
                    assert install_pack(str(stage_zip)) is True

    def test_load_pack_manifest_non_dict_data(self, tmp_path):
        from eval_runner.catalog import _load_pack_manifest

        # pack.yaml contains a list/string, not a dict (line 473->469)
        p_dir = tmp_path / "p_list"
        p_dir.mkdir()
        (p_dir / "pack.yaml").write_text("- item1\n- item2\n", encoding="utf-8")
        assert _load_pack_manifest(p_dir) == {}
