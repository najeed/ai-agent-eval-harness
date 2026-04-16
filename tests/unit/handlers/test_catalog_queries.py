from eval_runner.catalog import ScenarioCatalog


def test_catalog_query_methods(mock_catalog_dir):
    """Test get_scenario, get_scenario_ids, and get_absolute_path."""
    catalog = ScenarioCatalog.get_instance()

    # 1. Test uninitialized fast path
    # If the scenarios list is empty but initialized, it should try load_index
    ScenarioCatalog._initialized = True
    ids = catalog.get_scenario_ids()
    assert len(ids) == 0

    # Add a valid scenario to test querying
    scenarios_dir = mock_catalog_dir / "scenarios"
    scen_file = scenarios_dir / "query_test.json"
    import json

    data = {"id": "query_test", "title": "Query Title"}
    scen_file.write_text(json.dumps(data))

    # 2. Build index to populate
    catalog.build_index()

    # get_scenario_ids
    ids = catalog.get_scenario_ids()
    assert "query_test" in ids

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
    from eval_runner.catalog import _archive_existing_pack

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
