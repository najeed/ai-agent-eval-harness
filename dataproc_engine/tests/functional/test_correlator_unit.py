import pytest
from dataproc_engine.core.correlator import DataCorrelator
from dataproc_engine.core.base_provider import StandardSchema

def test_correlator_normalize_signal():
    # 1. Normalization
    assert DataCorrelator.normalize_signal(50, 0, 100) == 0.5
    assert DataCorrelator.normalize_signal(150, 0, 100) == 1.5
    assert DataCorrelator.normalize_signal("invalid", 0, 100) == 0.0

def test_correlator_full_pipeline():
    # Mock datasets
    finance_records = [
        StandardSchema(
            id="f1", 
            industry="finance", 
            data={"entity_name": "Apple", "revenue": 100, "date": "2023-01-01"}, 
            provenance={}, 
            checksum="c1"
        )
    ]
    energy_records = [
        StandardSchema(
            id="e1", 
            industry="energy", 
            data={"date": "2023-01-01", "latest_value": 50.0}, 
            provenance={}, 
            checksum="c2"
        )
    ]
    
    datasets = {
        "finance": finance_records,
        "energy": energy_records
    }
    
    correlated = DataCorrelator.correlate(datasets)
    
    # Verify enrichment
    fin_rec = correlated["finance"][0]
    assert "spatio_temporal_energy_cost" in fin_rec.data
    assert fin_rec.data["spatio_temporal_energy_cost"] == 50.0

def test_correlator_fallback_logic():
    datasets = {
        "finance": [StandardSchema(id="f1", industry="finance", data={"entity_name": "X"}, provenance={}, checksum="c1")],
        "energy": [StandardSchema(id="e1", industry="energy", data={"latest_value": 75.0}, provenance={}, checksum="c2")]
    }
    
    correlated = DataCorrelator.correlate(datasets)
    assert correlated["finance"][0].data["macro_energy_index_fallback"] == 75.0


