import pytest
import os
import pandas as pd
import json
from dataproc_engine.core.correlator import DataCorrelator
from dataproc_engine.core.base_provider import StandardSchema

@pytest.fixture
def sample_datasets():
    # Finance: Apple Inc
    fin = StandardSchema(
        id="f1", industry="finance", 
        data={"entity_name": "Apple Inc.", "date": "2023-01-01"}, 
        provenance={}, checksum="xyz"
    )
    # Telecom: Apple (Fuzzy match candidate)
    tel = StandardSchema(
        id="t1", industry="telecom", 
        data={"entity_name": "Apple", "value": 500}, 
        provenance={}, checksum="abc"
    )
    # Energy: 2023-01-01 (Temporal match candidate)
    en = StandardSchema(
        id="e1", industry="energy", 
        data={"date": "2023-01-01", "latest_value": 85.0}, 
        provenance={}, checksum="def"
    )
    return {"finance": [fin], "telecom": [tel], "energy": [en], "healthcare": []}

def test_correlator_production_logic(sample_datasets):
    """Verify multi-vertical signal propagation and fuzzy resolution."""
    correlator = DataCorrelator()
    
    # Run correlation
    enriched = correlator.correlate(sample_datasets)
    
    fin_record = enriched["finance"][0]
    # 1. Fuzzy match worked (Apple Inc. -> Apple)
    assert fin_record.data["telecom_footprint_speed"] == 500
    # 2. Temporal match worked (2023-01-01)
    assert fin_record.data["spatio_temporal_energy_cost"] == 85.0

def test_correlator_file_discovery_resiliency(tmp_path):
    """Verify recursive discovery and load-failure handling (Lines 22-43)."""
    correlator = DataCorrelator()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    # 1. Valid JSONL
    valid_file = data_dir / "finance_live.jsonl"
    with open(valid_file, "w") as f:
        f.write(json.dumps({
            "id": "ext1", "industry": "finance", 
            "data": {"entity_name": "Tesla"}, 
            "provenance": {}, "checksum": "123"
        }) + "\n")
        
    # 2. Corrupt CSV (Should hit warning and continue)
    corrupt_file = data_dir / "telecom_bad.csv"
    with open(corrupt_file, "w") as f:
        f.write("id,industry\nbad_record") # Missing columns
        
    datasets = {}
    correlator.correlate(datasets, target_dir=str(data_dir))
    
    # Tesla should be discovered
    assert "finance" in datasets
    assert datasets["finance"][0].id == "ext1"

def test_correlator_signal_normalization():
    """Verify edge cases in signal normalization (Lines 109-117)."""
    # 0.5 (Midpoint)
    assert DataCorrelator.normalize_signal(150, 100, 200) == 0.5
    # Max bound
    assert DataCorrelator.normalize_signal(200, 100, 200) == 1.0
    # Division by zero protection
    assert DataCorrelator.normalize_signal(100, 100, 100) == 0.5
    # Type failure
    assert DataCorrelator.normalize_signal("invalid", 0, 100) == 0.0
