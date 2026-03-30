import pytest
import pandas as pd
from unittest.mock import patch, AsyncMock
from dataproc_engine.providers.public_sector.demographics import DemographicsProvider
from dataproc_engine.providers.public_sector.labor import LaborProvider
from dataproc_engine.providers.public_sector.housing import HousingProvider
from dataproc_engine.providers.public_sector.environment import EnvironmentProvider
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_demographics_world_bank_production():
    """Verify World Bank demographics extraction and transformation via simulation path."""
    config = {"industry": "public_sector", "demographics_mode": "worldbank", "allow_simulation": True}
    provider = DemographicsProvider(config, llm_manager=LLMManager({"llm_provider": "heuristic"}))

    # Force simulation path by making request_with_retry return None (API unreachable in CI)
    with patch.object(provider, 'request_with_retry', return_value=None):
        artifacts = await provider.extract()
        assert len(artifacts) > 0

        results = await provider.transform(artifacts)
        assert len(results) > 0
        # Simulation data for USA has value=333287557 — must be > 0
        pop_values = [r.data["population"] for r in results]
        assert any(p > 0 for p in pop_values), f"Expected at least one positive population, got: {pop_values}"
        assert results[0].provenance["provider"] == "World Bank"

@pytest.mark.asyncio
async def test_demographics_census_hardened():
    """Verify US Census transformation logic (Lines 107-127)."""
    config = {"industry": "public_sector", "demographics_mode": "census", "allow_simulation": True}
    provider = DemographicsProvider(config, llm_manager=LLMManager({"llm_provider": "heuristic"}))
    
    artifacts = await provider.extract()
    results = await provider.transform(artifacts)
    assert len(results) > 0
    assert results[0].data["state"] == "California"

@pytest.mark.asyncio
async def test_public_sector_local_load_boost(tmp_path):
    """Verify local CSV loading across Labor, Housing, and Environment (Lines 24-38)."""
    df = pd.DataFrame([{"key": "val", "metric": 100}])
    csv_path = str(tmp_path / "sector_data.csv")
    df.to_csv(csv_path, index=False)
    
    # Labor
    p_labor = LaborProvider({"industry": "public_sector", "input_uri": csv_path}, llm_manager=LLMManager({}))
    raw_l = await p_labor.extract()
    assert len(raw_l) > 0
    
    # Housing
    p_housing = HousingProvider({"industry": "public_sector", "input_uri": csv_path}, llm_manager=LLMManager({}))
    raw_h = await p_housing.extract()
    assert len(raw_h) > 0
    
    # Environment
    p_env = EnvironmentProvider({"industry": "public_sector", "input_uri": csv_path}, llm_manager=LLMManager({}))
    raw_e = await p_env.extract()
    assert len(raw_e) > 0

@pytest.mark.asyncio
async def test_housing_fhfa_transformation():
    """Verify FHFA/HUD housing transformation (Lines 61-79)."""
    # Create raw artifact mimicking FHFA structure
    provider = HousingProvider({"industry": "public_sector", "housing_mode": "hud"}, llm_manager=LLMManager({"llm_provider": "heuristic"}))
    sim_data = [{"region": "West", "index_value": 250.5, "year": 2023}]
    artifact = provider.create_simulated_artifact(id="FHFA-SIM", content=sim_data)
    
    results = await provider.transform([artifact])
    assert results[0].data["location"] == "West"
    assert results[0].data["hpi_index"] == 250.5
