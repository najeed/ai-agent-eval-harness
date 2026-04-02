import pytest
import hashlib
import json
from unittest.mock import patch, AsyncMock
from dataproc_engine.providers.manufacturing import ManufacturingProvider
from dataproc_engine.providers.media_and_entertainment import MediaProvider
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
async def test_manufacturing_asm_production():
    """Verify US Census ASM transformation (Lines 85-107)."""
    config = {"industry": "manufacturing", "manufacturing_mode": "asm", "allow_simulation": True}
    provider = ManufacturingProvider(config, llm_manager=LLMManager({"llm_provider": "heuristic"}))
    
    artifacts = await provider.extract()
    results = await provider.transform(artifacts)
    assert len(results) > 0
    assert "Food manufacturing" in results[0].data["industry_label"]
    assert results[0].data["establishments"] > 0

@pytest.mark.asyncio
async def test_media_entertainment_production():
    """Verify Media & Entertainment extraction and transformation (High-fidelity)."""
    config = {"industry": "media_and_entertainment", "media_mode": "imdb", "allow_simulation": True}
    provider = MediaProvider(config, llm_manager=LLMManager({"llm_provider": "heuristic"}))
    
    artifacts = await provider.extract()
    assert len(artifacts) > 0
    results = await provider.transform(artifacts)
    assert len(results) > 0
    assert results[0].data["rating"] > 0
    assert results[0].industry == "media_and_entertainment"
