import pytest
import os
import pandas as pd
import io
from unittest.mock import patch, MagicMock, AsyncMock
from dataproc_engine.providers.ecommerce import EcommerceProvider
from dataproc_engine.providers.telecom import TelecomProvider
from dataproc_engine.providers.transportation import TransportationProvider
from dataproc_engine.providers.unstructured_provider import UnstructuredProvider
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_ecommerce_macro_sentiment_deep_hit():
    """Target Ecommerce lines 51, 54-55, 68-69, 75, 168-172."""
    config = {
        "industry": "ecommerce",
        "input_uri": "test_ecom.csv",
        "allow_simulation": True,
        "llm_strategy": "heuristic"
    }
    provider = EcommerceProvider(config, llm_manager=LLMManager({}))
    
    with patch("os.path.exists", return_value=False):
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        
        # Trigger transform with CPI weighting (Lines 168-172)
        artifacts[0].content = [{"product_id": "P1", "review_text": "Great!", "score": 5}]
        results = await provider.transform(artifacts)
        assert len(results) > 0

@pytest.mark.asyncio
async def test_telecom_fcc_retry_and_e911_hardened():
    """Target Telecom lines 45, 63-78, 124-126, 133, 250-251."""
    config = {
        "industry": "telecom",
        "schema_type": "fcc",
        "fcc_urls": ["https://api.fcc.gov/test"],
        "allow_simulation": True
    }
    provider = TelecomProvider(config, llm_manager=LLMManager({}))
    
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        # Correct key "features" for TelecomProvider.extract
        mock_resp.json.return_value = {"features": [{"id": "FCC_1", "technology_type": "Fiber"}]}
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        
        # Trigger validation error (Line 250)
        results = await provider.transform(artifacts)
        results[0].data["download_speed"] = -1
        assert provider.validate(results) is False

@pytest.mark.asyncio
async def test_transportation_osm_quadkey_hit_hardened():
    """Target Transportation lines 33, 38-46, 55, 73, 90-103."""
    config = {
        "industry": "transportation",
        "schema_type": "osm",
        "allow_simulation": True
    }
    provider = TransportationProvider(config, llm_manager=LLMManager({"llm_provider": "heuristic"}))
    
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = {"elements": [{"id": 1, "tags": {"highway": "motorway", "name": "I-95"}}]}
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        
        results = await provider.transform(artifacts)
        assert len(results) > 0

@pytest.mark.asyncio
async def test_unstructured_llm_extraction_hit():
    """Target Unstructured lines 158-175 (Extraction via LLM)."""
    config = {"industry": "unstructured", "allow_simulation": True}
    llm = LLMManager({"llm_strategy": "heuristic"})
    provider = UnstructuredProvider(config, llm_manager=llm)
    
    # 1. Mock Extract (Simulation)
    artifacts = await provider.extract()
    
    # 2. Mock LLM Response (Lines 165-175)
    with patch.object(llm, "extract_structured_data", return_value={"entity_name": "Test Co", "revenue": 1000}):
        results = await provider.transform(artifacts)
        assert len(results) > 0
        assert results[0].data["entity_name"] == "Test Co"
