import pytest
import aiohttp
from unittest.mock import patch, MagicMock
from dataproc_engine.providers.finance import FinanceProvider
from dataproc_engine.core.llm_manager import LLMManager

class MockResponse:
    """Explicit Async Context Manager for aiohttp mocks."""
    def __init__(self, status, json_data=None):
        self.status = status
        self._json = json_data or []
    async def json(self): return self._json
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass

@pytest.mark.asyncio
async def test_finance_world_bank_logic():
    """Verify World Bank macroeconomic extraction and simulation (Lines 27-65)."""
    # 1. Successful Web Fetch
    config = {"industry": "finance", "finance_mode": "worldbank", "allow_simulation": False}
    provider = FinanceProvider(config, llm_manager=LLMManager({"llm_provider": "mock"}))
    
    mock_wb_data = [
        {"page": 1},
        [
            {"country": {"value": "USA"}, "indicator": {"value": "GDP"}, "value": 25000000, "date": "2023"},
            {"country": {"value": "CAN"}, "indicator": {"value": "GDP"}, "value": 2000000, "date": "2023"}
        ]
    ]
    
    with patch("aiohttp.ClientSession.get", return_value=MockResponse(200, mock_wb_data)):
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        transformed = await provider.transform(artifacts)
        assert len(transformed) > 0
        assert transformed[0].data["country"] == "USA"

@pytest.mark.asyncio
async def test_finance_world_bank_simulation():
    """Verify World Bank simulation fallback."""
    config = {"industry": "finance", "finance_mode": "worldbank", "allow_simulation": True}
    provider = FinanceProvider(config, llm_manager=LLMManager({}))
    
    # Force API failure to trigger simulation
    with patch("aiohttp.ClientSession.get", return_value=MockResponse(500)):
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        assert any("WB-" in a.id for a in artifacts)
        assert "WB" in artifacts[0].id
        transformed = await provider.transform(artifacts)
        assert len(transformed) > 0
