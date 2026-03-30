"""
test_environment_provider.py
Coverage for EnvironmentProvider — NOAA and Copernicus modes.
"""
import pytest
from unittest.mock import patch
from dataproc_engine.providers.public_sector.environment import EnvironmentProvider
from dataproc_engine.core.llm_manager import LLMManager


@pytest.mark.asyncio
async def test_environment_noaa_extract_simulation():
    """NOAA mode extract produces simulated temperature records."""
    config = {"environment_mode": "noaa", "allow_simulation": True}
    provider = EnvironmentProvider(config, llm_manager=LLMManager({"llm_strategy": "mock"}))

    artifacts = await provider.extract()
    assert len(artifacts) > 0
    assert artifacts[0].metadata.get("simulation") is True
    # Should have TMAX and TMIN records
    content = artifacts[0].content
    assert any(row.get("datatype") in ("TMAX", "TMIN") for row in content)


@pytest.mark.asyncio
async def test_environment_noaa_transform():
    """NOAA mode transform produces normalized temperature schema records."""
    config = {"environment_mode": "noaa", "allow_simulation": True}
    provider = EnvironmentProvider(config, llm_manager=LLMManager({"llm_strategy": "mock"}))

    artifacts = await provider.extract()
    results = await provider.transform(artifacts)

    assert len(results) > 0
    for r in results:
        assert r.industry == "environment"
        assert "location" in r.data
        assert "timestamp" in r.data
        assert "metric" in r.data
        assert "value" in r.data
        assert "unit" in r.data
        assert r.data["unit"] == "Celsius"


@pytest.mark.asyncio
async def test_environment_copernicus_extract_simulation():
    """Copernicus mode extract produces ERA5 simulation records."""
    config = {"environment_mode": "copernicus", "allow_simulation": True}
    provider = EnvironmentProvider(config, llm_manager=LLMManager({"llm_strategy": "mock"}))

    artifacts = await provider.extract()
    assert len(artifacts) > 0
    # Content should have lat/lon/time/t2m fields
    content = artifacts[0].content
    assert any("latitude" in row for row in content)
    assert any("t2m" in row for row in content)


@pytest.mark.asyncio
async def test_environment_copernicus_transform():
    """Copernicus mode transform produces location string from lat/lon."""
    config = {"environment_mode": "copernicus", "allow_simulation": True}
    provider = EnvironmentProvider(config, llm_manager=LLMManager({"llm_strategy": "mock"}))

    artifacts = await provider.extract()
    results = await provider.transform(artifacts)

    assert len(results) > 0
    for r in results:
        assert r.industry == "environment"
        # Location should be a lat/lon string
        assert "," in r.data["location"]
        assert r.data["unit"] == "K"
        assert r.data["metric"] == "Temperature (2m)"


@pytest.mark.asyncio
async def test_environment_copernicus_no_simulation_returns_empty():
    """Copernicus with simulation disabled returns empty list."""
    config = {"environment_mode": "copernicus", "allow_simulation": False}
    provider = EnvironmentProvider(config, llm_manager=LLMManager({"llm_strategy": "mock"}))

    artifacts = await provider.extract()
    assert artifacts == []


@pytest.mark.asyncio
async def test_environment_noaa_no_simulation_returns_empty():
    """NOAA with simulation disabled returns empty list."""
    config = {"environment_mode": "noaa", "allow_simulation": False}
    provider = EnvironmentProvider(config, llm_manager=LLMManager({"llm_strategy": "mock"}))

    artifacts = await provider.extract()
    assert artifacts == []


def test_environment_validate_celsius_bounds():
    """validate() rejects temperatures outside physically plausible Celsius range."""
    from dataproc_engine.core.base_provider import StandardSchema
    config = {"environment_mode": "noaa"}
    provider = EnvironmentProvider(config, llm_manager=LLMManager({"llm_strategy": "mock"}))

    valid_record = StandardSchema(
        id="r1", industry="environment",
        data={"location": "NYC", "timestamp": "2023-01-01", "metric": "TMAX", "value": 20.0, "unit": "Celsius"},
        provenance={}, checksum=""
    )
    out_of_range_record = StandardSchema(
        id="r2", industry="environment",
        data={"location": "NYC", "timestamp": "2023-01-01", "metric": "TMAX", "value": 75.0, "unit": "Celsius"},
        provenance={}, checksum=""
    )
    assert provider.validate([valid_record]) is True
    assert provider.validate([out_of_range_record]) is False


def test_environment_validate_kelvin_bounds():
    """validate() rejects Kelvin values outside physically plausible range."""
    from dataproc_engine.core.base_provider import StandardSchema
    config = {"environment_mode": "copernicus"}
    provider = EnvironmentProvider(config, llm_manager=LLMManager({"llm_strategy": "mock"}))

    valid_k = StandardSchema(
        id="r1", industry="environment",
        data={"location": "52.5, 13.4", "timestamp": "2023-01-01T12:00:00Z",
              "metric": "Temperature (2m)", "value": 280.1, "unit": "K"},
        provenance={}, checksum=""
    )
    invalid_k = StandardSchema(
        id="r2", industry="environment",
        data={"location": "52.5, 13.4", "timestamp": "2023-01-01T12:00:00Z",
              "metric": "Temperature (2m)", "value": 10.0, "unit": "K"},  # <150 K → invalid
        provenance={}, checksum=""
    )
    assert provider.validate([valid_k]) is True
    assert provider.validate([invalid_k]) is False


@pytest.mark.asyncio
async def test_environment_full_pipeline_noaa():
    """End-to-end pipeline: extract → transform → validate for NOAA mode."""
    config = {"environment_mode": "noaa", "allow_simulation": True}
    provider = EnvironmentProvider(config, llm_manager=LLMManager({"llm_strategy": "mock"}))

    artifacts = await provider.extract()
    results = await provider.transform(artifacts)
    is_valid = provider.validate(results)

    assert len(results) > 0
    assert is_valid is True


@pytest.mark.asyncio
async def test_environment_full_pipeline_copernicus():
    """End-to-end pipeline: extract → transform → validate for Copernicus mode."""
    config = {"environment_mode": "copernicus", "allow_simulation": True}
    provider = EnvironmentProvider(config, llm_manager=LLMManager({"llm_strategy": "mock"}))

    artifacts = await provider.extract()
    results = await provider.transform(artifacts)
    is_valid = provider.validate(results)

    assert len(results) > 0
    assert is_valid is True
