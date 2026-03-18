import pytest
import os
from pathlib import Path
import json
from eval_runner import catalog
ScenarioCatalog = catalog.ScenarioCatalog

def test_catalog_indexing(tmp_path):
    # Setup mock industries directory
    industries_dir = tmp_path / "industries"
    ind_a = industries_dir / "ind_a" / "scenarios"
    ind_a.mkdir(parents=True)
    
    scen_1 = {
        "id": "scen_1",
        "title": "Scenario One",
        "metadata": {"industry": "ind_a", "difficulty": "1", "tags": ["tag1"]}
    }
    with open(ind_a / "scen_1.json", "w") as f:
        json.dump(scen_1, f)
        
    # ScenarioCatalog uses index_path in __init__ and root_dir in build_index
    index_file = tmp_path / "index.json"
    catalog = ScenarioCatalog(index_path=str(index_file))
    
    catalog.build_index(root_dir=str(industries_dir))
    assert index_file.exists()
    
    with open(index_file, "r") as f:
        data = json.load(f)
        assert len(data) == 1
        assert data[0]["id"] == "scen_1"

def test_catalog_search(tmp_path):
    catalog = ScenarioCatalog()
    catalog.scenarios = [
        {"id": "s1", "title": "Telecom Test", "industry": "telecom", "difficulty": "1", "tags": ["mobile"], "description": "desc1"},
        {"id": "s2", "title": "Finance Test", "industry": "finance", "difficulty": "3", "tags": ["banking"], "description": "desc2"},
        {"id": "s3", "title": "Mobile Test", "industry": "telecom", "difficulty": "2", "tags": ["roaming"], "description": "desc3"}
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
