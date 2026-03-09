import pytest
import json
from pathlib import Path
from eval_runner import loader

def test_load_dataset_single_json(tmp_path):
    scenario_file = tmp_path / "test.json"
    scenario_data = {
        "scenario_id": "test-123",
        "version": "2.0.0",
        "title": "Test",
        "industry": "test",
        "tasks": []
    }
    scenario_file.write_text(json.dumps(scenario_data))
    
    # Mocking the schema validation for unit test if needed, 
    # but here we use the real one since it's available.
    results = loader.load_dataset(scenario_file)
    assert len(results) == 1
    assert results[0]["scenario_id"] == "test-123"

def test_load_dataset_directory(tmp_path):
    (tmp_path / "s1.json").write_text(json.dumps({
        "scenario_id": "s1", "version": "2.0.0", "title": "S1", "industry": "i1", "tasks": []
    }))
    (tmp_path / "s2.json").write_text(json.dumps({
        "scenario_id": "s2", "version": "2.0.0", "title": "S2", "industry": "i2", "tasks": []
    }))
    (tmp_path / "other.txt").write_text("not a json")
    
    results = loader.load_dataset(tmp_path)
    assert len(results) == 2
    ids = [r["scenario_id"] for r in results]
    assert "s1" in ids
    assert "s2" in ids
