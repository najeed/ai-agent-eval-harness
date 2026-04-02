import pytest
import hashlib
import json
from unittest.mock import patch, AsyncMock
from dataproc_engine.providers.manufacturing import ManufacturingProvider
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_manufacturing_industrial_production():
    """Verify industrial stats manufacturing transformation."""
    config = {"industry": "manufacturing", "manufacturing_mode": "industrial_stats", "allow_simulation": True}
    provider = ManufacturingProvider(config, llm_manager=LLMManager({"llm_provider": "heuristic"}))
    
    artifacts = await provider.extract()
    assert len(artifacts) > 0
    results = await provider.transform(artifacts)
    assert results[0].data["mva_value"] > 0
    assert results[0].provenance["provider"] == "Industrial-Stats-Agency"

@pytest.mark.asyncio
async def test_manufacturing_census_baseline():
    """Verify census-based manufacturing baseline extraction."""
    config = {"industry": "manufacturing", "manufacturing_mode": "census", "allow_simulation": True}
    provider = ManufacturingProvider(config, llm_manager=LLMManager({"llm_provider": "heuristic"}))
    
    artifacts = await provider.extract()
    assert len(artifacts) > 0
    results = await provider.transform(artifacts)
    assert len(results) > 0
    assert "Food manufacturing" in results[0].data["industry_label"]
    assert results[0].data["establishments"] > 0
