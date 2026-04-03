import pytest
import asyncio
from unittest.mock import patch, MagicMock
from dataproc_engine.core.engine import DatasetEngine
from dataproc_engine.core.llm_manager import LLMManager
from dataproc_engine.core.base_provider import StandardSchema

class MockResponse:
    """Explicit Async Context Manager for aiohttp mocks."""
    def __init__(self, status, json_data=None):
        self.status = status
        self._json = json_data or {}
    async def json(self): return self._json
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass

@pytest.mark.asyncio
@pytest.mark.parametrize("industry, custom_config", [
    ("finance", {"finance_mode": "sec_edgar"}),
    ("finance", {"finance_mode": "worldbank"}),
    ("finance", {"finance_mode": "credit_risk"}),
    ("energy", {"eia_mode": "opsd"}),
    ("healthcare", {"healthcare_mode": "clinical"}),
    ("healthcare", {"healthcare_mode": "who"}),
    ("telecom", {"telecom_mode": "fcc"}),
    ("telecom", {"telecom_mode": "ookla"}),
    ("ecommerce", {"ecommerce_mode": "uci"}),
    ("ecommerce", {"ecommerce_mode": "olist"}),
    ("agriculture", {"agriculture_mode": "faostat"}),
    ("transportation", {"transit_mode": "standard"}),
    ("unstructured", {"unstructured_mode": "document"}),
    ("demographics", {"demographics_mode": "census"}),
    ("labor", {"labor_mode": "bls"}),
    ("environment", {"environment_mode": "noaa"}),
    ("education", {"education_mode": "nces"}),
    ("housing", {"housing_mode": "hud"}),
    ("manufacturing", {"manufacturing_mode": "industrial_stats"}),
    ("media_and_entertainment", {"media_mode": "imdb"}),
    ("decision_support", {"decision_mode": "standard"}),
])
async def test_industry_parity(industry, custom_config):
    """
    Ensure all industrial providers adhere to the mission-critical architectural standards.
    """
    llm = LLMManager({"llm_strategy": "mock"})
    engine = DatasetEngine(llm_manager=llm)
    
    base_dir = "."
    config = {"limit": 1}
    config.update(custom_config)
    
    # 1. Mode-Aware High-Fidelity Mock for Finance domain validation
    if industry == "finance" and config.get("finance_mode") == "worldbank":
        mock_data = [
            {"page": 1},
            [{"country": {"value": "USA", "id": "US"}, "indicator": {"value": "GDP"}, "value": 1.0, "date": "2023"}]
        ]
    elif industry == "ecommerce":
        # Tabular mock data for Olist/UCI
        mock_data = [
            {"InvoiceNo": "INV-1", "Description": "Product A", "Quantity": 1, "UnitPrice": 10.0, "review_score": 5, "review_text": "Good", "order_id": "ORD-1", "price": 100.0}
        ]
    else:
        # Default SEC XBRL Mock
        mock_data = {
            "entityName": "Apple Inc.", 
            "facts": {"us-gaap": {
                "Revenues": {"units": {"USD": [{"val": 100000, "fy": 2023, "fp": "FY"}]}},
                "Assets": {"units": {"USD": [{"val": 350000, "fy": 2023, "fp": "FY"}]}},
                "NetIncomeLoss": {"units": {"USD": [{"val": 95000, "fy": 2023, "fp": "FY"}]}}
            }}
        }
    
    mock_resp = MockResponse(200, mock_data)
    
    # 2. Industry-specific input overrides
    if industry == "finance":
         config["ciks"] = ["0000320193"]
    elif industry == "energy":
        config["series_id"] = "ELEC.GEN.ALL-US-99.M"
    elif industry == "transportation":
         config["input_uri"] = f"industries/transportation/datasets/airline_delays.csv"
    elif industry == "telecom":
         config["input_uri"] = f"industries/telecom/datasets/telecom_records.csv"
    elif industry == "unstructured":
         config["input_uri"] = "industries/unstructured/datasets/sample_document.txt"

    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        # Inject the mock llm_mgr into the engine so it's passed to ALL providers
        llm_mgr = LLMManager({"llm_provider": "mock"})
        engine.llm_manager = llm_mgr

        provider = engine.get_provider(industry, config)
        
        # 3. Standard Execution Pipeline (V2.0 Contract)
        raw_data = await provider.extract()
        transformed = await provider.transform(raw_data)
        
        # Hardening check for all sectors (ensures simulation or local data production)
        if industry in [
            "transportation", "agriculture", "unstructured", "demographics", 
            "labor", "environment", "education", "housing", "manufacturing", 
            "media_and_entertainment", "decision_support", "finance", "energy", "healthcare", "telecom", "ecommerce"
        ]:
             assert len(transformed) > 0, f"{industry} failed to produce records from dummy data."

        for record in transformed:
            assert isinstance(record, StandardSchema), f"{industry} must produce StandardSchema"
            assert record.industry == industry, f"{industry} output industry mismatch"
            assert "record_id" in record.to_dict(), f"{industry} missing record_id in dict"
            assert record.checksum is not None, f"{industry} missing checksum"
            assert provider.validate([record]), f"{industry} failed domain validation"

def test_pii_scrubbing_parity():
    """
    Verify that PII scrubbing is consistent across the framework.
    """
    llm = LLMManager({"llm_strategy": "mock"})
    engine = DatasetEngine(llm_manager=llm)
    provider = engine.get_provider("finance", {}) # Any provider works as it's in BaseProvider
    
    test_text = "Contact me at nudge@example.com or (555) 001-0199."
    scrubbed = provider.scrub_pii(test_text)
    
    assert "[EMAIL]" in scrubbed
    assert "[PHONE]" in scrubbed
    assert "nudge@example.com" not in scrubbed
    assert "(555) 001-0199" not in scrubbed

@pytest.mark.asyncio
async def test_resiliency_layer():
    """
    Verify that the request_with_retry layer handles failures correctly.
    """
    llm = LLMManager({"llm_strategy": "mock"})
    engine = DatasetEngine(llm_manager=llm)
    provider = engine.get_provider("finance", {"max_retries": 2})
    
    count = 0
    async def failing_func():
        nonlocal count
        count += 1
        raise Exception("Transient Error")

    result = await provider.request_with_retry(failing_func)
    
    assert result is None
    assert count == 2 # Max retries reached

def test_backup_rotation(tmp_path):
    """
    Verify that the rotational backup logic preserves data and prunes old versions.
    """
    from dataproc_engine.cli.main import run_rotational_backup
    import os
    import glob
    
    output_file = str(tmp_path / "test_data.jsonl")
    with open(output_file, "w") as f:
        f.write("original data")
    
    # 1. Trigger first backup
    archive1 = run_rotational_backup(output_file, max_backups=2)
    assert os.path.exists(archive1)
    
    # 2. Trigger multiple backups to test rotation (max=2)
    with open(output_file, "w") as f: f.write("data 2")
    archive2 = run_rotational_backup(output_file, max_backups=2)
    
    with open(output_file, "w") as f: f.write("data 3")
    archive3 = run_rotational_backup(output_file, max_backups=2)
    
    backups = sorted(glob.glob(f"{output_file}.*.bak"))
    assert len(backups) == 2
    assert archive1 not in backups
    assert archive2 in backups
    assert archive3 in backups


