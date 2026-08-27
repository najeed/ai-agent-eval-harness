from unittest.mock import patch

import pytest

from dataproc_engine.core.llm_manager import LLMManager
from dataproc_engine.providers.energy import EnergyProvider
from dataproc_engine.providers.finance import FinanceProvider
from dataproc_engine.providers.public_sector.housing import HousingProvider
from dataproc_engine.providers.transportation import TransportationProvider


class MockResponse:
    """Explicit Async Context Manager for aiohttp mocks."""

    def __init__(self, status, json_data=None):
        self.status = status
        self._json = json_data or {}

    async def json(self):
        return self._json

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.mark.asyncio
async def test_housing_fhfa_and_hud_mastery():
    config = {"industry": "public_sector", "housing_mode": "hud", "allow_simulation": True}
    provider = HousingProvider(config, llm_manager=LLMManager({}))

    # 1. Trigger Simulation
    with patch("os.path.exists", return_value=False):
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        assert "sim-HUD" in artifacts[0].id

    # 2. Trigger transform
    result = await provider.transform(artifacts)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_finance_world_bank_fallback_mastery():
    config = {"industry": "finance", "finance_mode": "worldbank", "allow_simulation": True}
    provider = FinanceProvider(config, llm_manager=LLMManager({}))

    mock_resp = MockResponse(500)
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        assert "WB" in artifacts[0].id


@pytest.mark.asyncio
async def test_energy_opsd_fallback_mastery():
    config = {"industry": "energy", "energy_mode": "opsd", "allow_simulation": True}
    provider = EnergyProvider(config, llm_manager=LLMManager({}))

    mock_resp = MockResponse(500)
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        assert "OPSD" in artifacts[0].id


@pytest.mark.asyncio
async def test_transportation_eurostat_mastery():
    config = {
        "industry": "transportation",
        "transit_mode": "eurostat",  # Fixed key: transit_mode
        "allow_simulation": True,
    }
    provider = TransportationProvider(config, llm_manager=LLMManager({}))

    # 1. Extract Eurostat Simulation
    artifacts = await provider.extract()
    assert len(artifacts) > 0
    assert "EURO" in artifacts[0].id

    # 2. Transform Eurostat
    results = await provider.transform(artifacts)
    assert len(results) > 0
    assert results[0].provenance["provider"] == "Eurostat"

    # 3. Validate Eurostat
    assert provider.validate(results) is True
