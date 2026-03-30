import pytest
import asyncio
from dataproc_engine.providers.education import EducationProvider
from dataproc_engine.providers.energy import EnergyProvider
from dataproc_engine.providers.transportation import TransportationProvider
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_education_hegemony():
    """Exhaustive coverage for every EducationProvider branch."""
    llm = LLMManager({"llm_strategy": "heuristic"})
    modes = [
        {"education_mode": "nces"}, {"education_mode": "unesco"}, 
        {"education_mode": "mooc"}, {"education_mode": "kaggle"}
    ]
    for mode in modes:
        config = {"industry": "education", "allow_simulation": True}
        config.update(mode)
        provider = EducationProvider(config, llm_manager=llm)
        raw = await provider.extract()
        assert len(raw) > 0
        transformed = await provider.transform(raw)
        assert len(transformed) > 0
        assert provider.validate(transformed) is True

@pytest.mark.asyncio
async def test_energy_hegemony():
    """Exhaustive coverage for every EnergyProvider branch."""
    llm = LLMManager({"llm_strategy": "heuristic"})
    modes = [
        {"eia_mode": "opsd", "series_id": "TEST"},
        {"eia_mode": "energy_balances"},
        {"eia_mode": "opsd"},
        {"eia_mode": "balances"}
    ]
    for mode in modes:
        config = {"industry": "energy", "allow_simulation": True}
        config.update(mode)
        provider = EnergyProvider(config, llm_manager=llm)
        raw = await provider.extract()
        assert len(raw) > 0
        transformed = await provider.transform(raw)
        assert len(transformed) > 0

@pytest.mark.asyncio
async def test_transportation_hegemony():
    """Exhaustive coverage for every TransportationProvider branch."""
    llm = LLMManager({"llm_strategy": "heuristic"})
    modes = [
        {"schema_type": "air"},
        {"transit_mode": "osm"},
        {"transit_mode": "eurostat"},
        {"transit_mode": "gtfs"}
    ]
    for mode in modes:
        config = {"industry": "transportation", "allow_simulation": True}
        config.update(mode)
        provider = TransportationProvider(config, llm_manager=llm)
        raw = await provider.extract()
        assert len(raw) > 0
        transformed = await provider.transform(raw)
        assert len(transformed) > 0
