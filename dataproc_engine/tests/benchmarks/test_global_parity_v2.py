import pytest
import asyncio
from unittest.mock import patch, MagicMock
from typing import List, Dict, Any
from dataproc_engine.core.engine import DatasetEngine
from dataproc_engine.core.llm_manager import LLMManager
from dataproc_engine.core.base_provider import StandardSchema

class MockResponse:
    """Explicit Async Context Manager for aiohttp mocks."""
    def __init__(self, status, json_data=None):
        self.status = status
        self._json = json_data or {}
    def validate(self, normalized_data: List[StandardSchema]) -> bool:
        if not normalized_data:
            return False 
        for record in normalized_data:
            if record.data.get("population", 0) <= 0:
                return False
        return True
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
    ("education", {"education_mode": "nces"}),
    ("manufacturing", {"manufacturing_mode": "industrial_stats"}),
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
    
    # 1. Mode-Aware High-Fidelity Mock for Industry domain validation
    if industry == "finance" and config.get("finance_mode") == "worldbank":
        mock_data = [
            {"page": 1},
            [{"country": {"value": "USA", "id": "US"}, "indicator": {"value": "GDP"}, "value": 1.0, "date": "2023"}]
        ]
    elif industry == "ecommerce":
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
        llm_mgr = LLMManager({"llm_provider": "mock"})
        engine.llm_manager = llm_mgr
        
        provider = engine.get_provider(industry, config)
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        
        results = await provider.transform(artifacts)
        assert len(results) > 0
        
        # Schema parity check
        for res in results:
            assert isinstance(res, StandardSchema)
            assert res.industry == industry
            assert "data" in res.__dict__
            assert "provenance" in res.__dict__
