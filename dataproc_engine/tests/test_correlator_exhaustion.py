import pytest
import os
import pandas as pd
import json
from unittest.mock import patch, MagicMock
from dataproc_engine.core.correlator import DataCorrelator
from dataproc_engine.core.base_provider import StandardSchema
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_correlator_file_discovery(tmp_path):
    """Exercise Correlator's recursive file discovery (Lines 22-43)."""
    correlator = DataCorrelator()
    target_dir = str(tmp_path / "data")
    os.makedirs(target_dir)
    
    # Create a dummy jsonl file
    jsonl_file = os.path.join(target_dir, "finance_discovered.jsonl")
    with open(jsonl_file, "w") as f:
        f.write(json.dumps({"id": "1", "data": {"entity_name": "Apple", "revenue": 100}, "industry": "finance", "provenance": {}, "checksum": "abc"}) + "\n")
    
    datasets = {}
    correlator.correlate(datasets, target_dir=target_dir)
    assert "finance" in datasets
    assert len(datasets["finance"]) > 0

@pytest.mark.asyncio
async def test_correlator_fuzzy_and_temporal():
    """Exercise fuzzy matching and spatio-temporal logic (Lines 45-106)."""
    correlator = DataCorrelator()
    
    # 1. Finance Record
    fin_record = StandardSchema(
        id="f1", industry="finance", 
        data={"entity_name": "Apple Inc.", "date": "2023-01-01"}, 
        provenance={}, checksum="xyz"
    )
    
    # 2. Telecom Record (Fuzzy Match: Apple)
    tel_record = StandardSchema(
        id="t1", industry="telecom", 
        data={"entity_name": "Apple", "value": 50.5}, 
        provenance={}, checksum="abc"
    )
    
    # 3. Energy Record (Temporal Match)
    en_record = StandardSchema(
        id="e1", industry="energy", 
        data={"date": "2023-01-01", "latest_value": 80.0}, 
        provenance={}, checksum="def"
    )
    
    # 4. Ecommerce Record (Sentiment)
    ec_record = StandardSchema(
        id="ec1", industry="ecommerce", 
        data={"sentiment": 0.8}, 
        provenance={}, checksum="ghi"
    )
    
    datasets = {
        "finance": [fin_record],
        "telecom": [tel_record],
        "energy": [en_record],
        "ecommerce": [ec_record]
    }
    
    enriched = correlator.correlate(datasets)
    
    fin_data = enriched["finance"][0].data
    assert fin_data.get("telecom_footprint_speed") == 50.5
    assert fin_data.get("spatio_temporal_energy_cost") == 80.0
    assert fin_data.get("global_ecommerce_sentiment") == 0.8

@pytest.mark.asyncio
async def test_correlator_normalization():
    """Exercise normalization edge cases (Lines 109-117)."""
    val = DataCorrelator.normalize_signal(150, 100, 200)
    assert val == 0.5
    
    # Error branch
    val_err = DataCorrelator.normalize_signal("invalid", 100, 200)
    assert val_err == 0.0
