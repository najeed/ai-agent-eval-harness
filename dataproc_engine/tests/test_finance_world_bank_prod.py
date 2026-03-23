import pytest
import aiohttp
from unittest.mock import patch, AsyncMock
from dataproc_engine.providers.finance import FinanceProvider
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_finance_world_bank_logic():
    """Verify World Bank macroeconomic extraction and simulation (Lines 27-65)."""
    # 1. Successful Web Fetch
    config = {"industry": "finance", "schema_type": "world_bank", "allow_simulation": False}
    provider = FinanceProvider(config, llm_manager=LLMManager({}))
    
    mock_wb_data = [
        {"page": 1},
        [
            {"country": {"value": "USA"}, "indicator": {"value": "GDP"}, "value": 25000000, "date": "2023"},
            {"country": {"value": "CAN"}, "indicator": {"value": "GDP"}, "value": 2000000, "date": "2023"}
        ]
    ]
    
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_wb_data)
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        transformed = await provider.transform(artifacts)
        assert len(transformed) > 0
        assert transformed[0].data["country"] == "USA"

@pytest.mark.asyncio
async def test_finance_world_bank_simulation():
    """Verify World Bank simulation fallback (Lines 54-65)."""
    config = {"industry": "finance", "schema_type": "world_bank", "allow_simulation": True}
    provider = FinanceProvider(config, llm_manager=LLMManager({}))
    
    # Force API failure to trigger simulation
    with patch("aiohttp.ClientSession.get", side_effect=Exception("Timeout")):
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        assert "WB" in artifacts[0].id
        transformed = await provider.transform(artifacts)
        assert len(transformed) > 0
