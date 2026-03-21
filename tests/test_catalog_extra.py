import pytest
import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
from eval_runner.catalog import ScenarioCatalog, list_scenarios

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
        json.dump({"scenario_id": "s1"}, f)
    
    index_path = tmp_path / "index.json"
    cat = ScenarioCatalog(index_path=str(index_path))
    
    # 1. First build
    cat.build_index(root_dir=str(industries_dir))
    mtime = scen_file.stat().st_mtime
    assert len(cat.scenarios) == 1
    
    # 2. Second build - cache hit
    # Check that mtime is preserved in memory and cache hit branch (line 41) is taken
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
    # Should skip the corrupt file and continute
    cat.build_index(root_dir=str(industries_dir))
    assert cat.scenarios == []

def test_check_for_updates_no_industries(tmp_path):
    cat = ScenarioCatalog()
    # Need to move industries out of the way or mock Path.exists
    with patch("eval_runner.catalog.Path.exists", return_value=False):
        assert cat.check_for_updates() is False

def test_load_index_sync_mismatch(tmp_path):
    index_path = tmp_path / "index.json"
    with open(index_path, "w") as f:
        json.dump([{"id": "old", "path": "p1"}], f)
        
    cat = ScenarioCatalog(index_path=str(index_path))
    
    # Mock check_for_updates to return True
    with patch.object(cat, "check_for_updates", return_value=True), \
         patch.object(cat, "build_index") as mock_build:
        cat.load_index()
        mock_build.assert_called()

def test_load_index_no_file(tmp_path):
    index_path = tmp_path / "index.json" # Not created
    cat = ScenarioCatalog(index_path=str(index_path))
    with patch.object(cat, "build_index") as mock_build:
        cat.load_index()
        mock_build.assert_called()

def test_list_scenarios_branches(capsys):
    # 1. No scenarios found
    with patch("eval_runner.catalog.ScenarioCatalog.load_index"), \
         patch("eval_runner.catalog.ScenarioCatalog.search", return_value=[]):
        list_scenarios("query")
        out, _ = capsys.readouterr()
        assert "No scenarios found." in out
        
    # 2. > 50 results
    many_results = [{"id": f"s{i}", "industry": "i", "difficulty": 1, "title": "t"} for i in range(55)]
    with patch("eval_runner.catalog.ScenarioCatalog.load_index"), \
         patch("eval_runner.catalog.ScenarioCatalog.search", return_value=many_results):
        list_scenarios("query")
        out, _ = capsys.readouterr()
        assert "and 5 more" in out

def test_search_auto_load(tmp_path):
    index_path = tmp_path / "index.json"
    cat_data = [{"id": "s1", "title": "t1", "industry": "fin", "description": "d", "tags": []}]
    with open(index_path, "w") as f:
        json.dump(cat_data, f)
    cat = ScenarioCatalog(index_path=str(index_path))
    # search() should call load_index() if scenarios is empty
    res = cat.search(query="t1")
    assert len(res) == 1

def test_search_faceted_filters():
    cat = ScenarioCatalog()
    cat.scenarios = [
        {"id": "s1", "industry": "fin", "difficulty": 1, "tags": []},
        {"id": "s2", "industry": "tech", "difficulty": 2, "tags": []}
    ]
    # Test line 130: faceted filter loop
    res = cat.search(industry="fin")
    assert len(res) == 1
    assert res[0]["id"] == "s1"

def test_list_scenarios_no_query(capsys):
    with patch("eval_runner.catalog.ScenarioCatalog.load_index"), \
         patch("eval_runner.catalog.ScenarioCatalog.scenarios", [{"id": "s1", "industry": "i", "difficulty": 1, "title": "t"}]):
        list_scenarios(query=None)
        out, _ = capsys.readouterr()
        assert "Scenario Catalog: (1 total)" in out

