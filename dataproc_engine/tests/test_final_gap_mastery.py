import pytest
import os
import aiohttp
from unittest.mock import patch, MagicMock, AsyncMock
from dataproc_engine.providers.unstructured_provider import UnstructuredProvider
from dataproc_engine.providers.transportation import TransportationProvider
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_unstructured_common_crawl_protocol_hit():
    """Target Unstructured lines 26-31, 140-158 (Common Crawl)."""
    config = {
        "industry": "unstructured",
        "schema_type": "common_crawl",
        "allow_simulation": True
    }
    provider = UnstructuredProvider(config, llm_manager=LLMManager({}))
    
    # 1. Extract (Lines 26-31)
    artifacts = await provider.extract()
    assert len(artifacts) > 0
    assert "CC-" in artifacts[0].id
    
    # 2. Transform (Lines 140-158)
    results = await provider.transform(artifacts)
    assert len(results) > 0
    assert results[0].provenance["provider"] == "Common Crawl"

@pytest.mark.asyncio
async def test_unstructured_url_extraction_hit():
    """Target Unstructured lines 60-62, 66 (Web URL Extract)."""
    config = {
        "industry": "unstructured",
        "input_uri": "https://example.com/report.html",
        "allow_simulation": True
    }
    provider = UnstructuredProvider(config, llm_manager=LLMManager({}))
    
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text.return_value = "WEB CONTENT"
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        assert artifacts[0].content == "WEB CONTENT"

@pytest.mark.asyncio
async def test_transportation_overpass_error_fallback():
    """Target Transportation lines 33, 45, 55, 73 (Error Fallbacks)."""
    config = {
        "industry": "transportation",
        "schema_type": "osm",
        "allow_simulation": True
    }
    provider = TransportationProvider(config, llm_manager=LLMManager({}))
    
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 500 # Trigger fallback
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        assert "bbox" in artifacts[0].metadata
