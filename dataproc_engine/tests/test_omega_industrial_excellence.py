import pytest
import os
import io
from unittest.mock import patch, MagicMock, AsyncMock
from dataproc_engine.providers.public_sector.housing import HousingProvider
from dataproc_engine.providers.finance import FinanceProvider
from dataproc_engine.providers.energy import EnergyProvider
from dataproc_engine.providers.transportation import TransportationProvider
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_housing_fhfa_and_hud_mastery():
    """Target Housing lines 24-38, 55, 61-79."""
    config = {
        "industry": "public_sector",
        "mode": "hud",
        "allow_simulation": True
    }
    provider = HousingProvider(config, llm_manager=LLMManager({}))
    
    # 1. Trigger Simulation (Lines 24-38)
    with patch("os.path.exists", return_value=False):
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        assert "sim-HUD" in artifacts[0].id
        
    # 2. Trigger transform (Lines 61-79)
    result = await provider.transform(artifacts)
    assert len(result) > 0

@pytest.mark.asyncio
async def test_finance_world_bank_fallback_mastery():
    """Target Finance lines 39, 51-52, 65, 95, 113, 129-131."""
    config = {
        "industry": "finance",
        "schema_type": "world_bank",
        "allow_simulation": True
    }
    provider = FinanceProvider(config, llm_manager=LLMManager({}))
    
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 500 # Trigger fallback (Lines 51-52)
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        assert "sim-WB" in artifacts[0].id

@pytest.mark.asyncio
async def test_energy_opsd_fallback_mastery():
    """Target Energy lines 53, 63, 72, 87, 95, 116-117, 149-150."""
    config = {
        "industry": "energy",
        "schema_type": "opsd",
        "allow_simulation": True
    }
    provider = EnergyProvider(config, llm_manager=LLMManager({}))
    
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 500 # Trigger fallback
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        assert "sim-OPSD" in artifacts[0].id

@pytest.mark.asyncio
async def test_transportation_eurostat_mastery():
    """Target Transportation lines 33, 57, 62-73, 137-149, 183-184."""
    config = {
        "industry": "transportation",
        "transit_mode": "eurostat", # Fixed key: transit_mode (Line 19 in provider)
        "allow_simulation": True
    }
    provider = TransportationProvider(config, llm_manager=LLMManager({}))
    
    # 1. Extract Eurostat Simulation (Lines 62-73)
    artifacts = await provider.extract()
    assert len(artifacts) > 0
    assert "EURO" in artifacts[0].id
    
    # 2. Transform Eurostat (Lines 137-149)
    results = await provider.transform(artifacts)
    assert len(results) > 0
    assert results[0].provenance["provider"] == "Eurostat"
    
    # 3. Validate Eurostat (Lines 183-184)
    assert provider.validate(results) is True
