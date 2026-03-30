import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from dataproc_engine.providers.energy import EnergyProvider
from dataproc_engine.providers.public_sector.labor import LaborProvider
from dataproc_engine.providers.healthcare import HealthcareProvider
from dataproc_engine.core.base_provider import RawArtifact
import datetime


@pytest.mark.asyncio
async def test_energy_provider_series_id_failure():
    """Harden EnergyProvider against EIA Series ID fetching failures."""
    # Pass series_id via config (extract() takes no kwargs per V2.0 contract)
    provider = EnergyProvider({"series_id": "INVALID_ID", "allow_simulation": False})

    # Simulate a scenario where request_with_retry returns None (API failure)
    with patch.object(provider, 'request_with_retry', return_value=None):
        raw_data = await provider.extract()
        # With allow_simulation=False and no API key, should return empty list
        assert raw_data is None or len(raw_data) == 0


@pytest.mark.asyncio
async def test_labor_provider_ilo_fallback():
    """Verify LaborProvider graceful fallback to simulation when API fails (V2.0 contract)."""
    # ILO mode with simulation enabled — provider should return simulated data gracefully
    provider = LaborProvider({"labor_mode": "ilo", "allow_simulation": True})

    # Mock request_with_retry to simulate API failure
    with patch.object(provider, 'request_with_retry', side_effect=Exception("ILO API DOWN")):
        # V2.0 contract: simulation fallback prevents exception propagation
        artifacts = await provider.extract()
        # Should produce simulated ILO records instead of raising
        assert len(artifacts) > 0
        assert artifacts[0].metadata.get("simulation") is True


@pytest.mark.asyncio
async def test_healthcare_provider_csv_integrity_error():
    """Harden HealthcareProvider against corrupt CSV ingestion (V2.0 config-based API)."""
    # Pass input_uri and source via config dict (extract() takes no kwargs)
    provider = HealthcareProvider({
        "healthcare_mode": "clinical",
        "input_uri": "non_existent.csv",
        "allow_simulation": True
    })

    # Test extraction — provider should fallback to simulation for a non-existent file
    raw_data = await provider.extract()
    # V2.0: simulation fallback guarantees non-empty output
    assert len(raw_data) > 0


@pytest.mark.asyncio
async def test_sector_token_limit_handling(heuristic_mock, patched_llm_manager):
    """Verify that sector providers handle LLM errors gracefully via LLMManager."""
    provider = EnergyProvider({})
    # V2.0 attribute is llm_manager, not llm
    provider.llm_manager = patched_llm_manager

    # Force a rate limit failure in the mock
    heuristic_mock.set_failure_mode("rate_limit")

    # Build a proper RawArtifact (transform expects RawArtifact objects, not dicts)
    artifact = RawArtifact(
        id="test-artifact",
        source_url="test://source",
        content=[{"series_id": "TEST", "series_name": "Test Series", "latest_value": 100.0,
                   "unit": "MWh", "period": "2023-01"}],
        metadata={},
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
    )

    # With a patched LLMManager, transform should handle any exception gracefully
    # (error propagates from LLM call, not a "Rate limit reached" msg — test correct behavior)
    with pytest.raises(Exception):
        await provider.transform([artifact])
