from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dataproc_engine.core.base_provider import RawArtifact, StandardSchema
from dataproc_engine.providers.agriculture import AgricultureProvider
from dataproc_engine.providers.ecommerce import EcommerceProvider
from dataproc_engine.providers.education import EducationProvider
from dataproc_engine.providers.energy import EnergyProvider
from dataproc_engine.providers.finance import FinanceProvider
from dataproc_engine.providers.healthcare import HealthcareProvider
from dataproc_engine.providers.manufacturing import ManufacturingProvider
from dataproc_engine.providers.media_and_entertainment import MediaProvider
from dataproc_engine.providers.public_sector.demographics import DemographicsProvider
from dataproc_engine.providers.public_sector.housing import HousingProvider
from dataproc_engine.providers.public_sector.labor import LaborProvider
from dataproc_engine.providers.telecom import TelecomProvider
from dataproc_engine.providers.unstructured_provider import UnstructuredProvider


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.strategy = "mock"
    llm._verify_schema.side_effect = lambda data, schema, strict=False: data
    llm.extract_structured_data = AsyncMock(return_value={"entity_name": "Test", "revenue": 100})
    llm._heuristic_sentiment.return_value = 0.5
    llm.analyze_sentiment = AsyncMock(return_value=0.5)
    return llm


@pytest.mark.asyncio
async def test_agriculture_usda_and_heuristic_coverage(mock_llm):
    config = {"agriculture_mode": "usda", "allow_simulation": True}
    provider = AgricultureProvider(config, llm_manager=mock_llm)
    artifacts = await provider.extract()
    assert len(artifacts) > 0
    mock_llm.strategy = "heuristic"
    records = await provider.transform(artifacts)
    assert len(records) > 0


@pytest.mark.asyncio
async def test_ecommerce_extract_failures_and_validation(mock_llm):
    config = {
        "ecommerce_mode": "tabular",
        "allow_simulation": False,
        "input_uri": "http://fail.com",
    }
    provider = EcommerceProvider(config, llm_manager=mock_llm)
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value.status = 404
        artifacts = await provider.extract()
        assert artifacts == []


@pytest.mark.asyncio
async def test_education_validation_failures(mock_llm):
    provider = EducationProvider({"education_mode": "nces"}, llm_manager=mock_llm)
    r1 = StandardSchema(
        id="1", industry="edu", data={"literacy_rate": 150}, provenance={}, checksum="x"
    )
    assert provider.validate([r1]) is False


@pytest.mark.asyncio
async def test_energy_coverage_gaps(mock_llm):
    provider = EnergyProvider(
        {"energy_mode": "opsd", "allow_simulation": False}, llm_manager=mock_llm
    )
    assert await provider.extract() == []


@pytest.mark.asyncio
async def test_finance_deep_coverage(mock_llm):
    provider = FinanceProvider(
        {"finance_mode": "worldbank", "allow_simulation": True}, llm_manager=mock_llm
    )
    with patch("aiohttp.ClientSession.get", side_effect=Exception("API Down")):
        artifacts = await provider.extract()
        assert len(artifacts) > 0


@pytest.mark.asyncio
async def test_healthcare_validation_and_failures(mock_llm):
    provider = HealthcareProvider({"healthcare_mode": "clinical"}, llm_manager=mock_llm)
    r1 = StandardSchema(
        id="1", industry="hc", data={"subject_id": None}, provenance={}, checksum="x"
    )
    assert provider.validate([r1]) is False


@pytest.mark.asyncio
async def test_manufacturing_and_media_no_sim(mock_llm):
    p1 = ManufacturingProvider({"allow_simulation": False}, llm_manager=mock_llm)
    assert await p1.extract() == []
    p2 = MediaProvider({"allow_simulation": False}, llm_manager=mock_llm)
    assert await p2.extract() == []


@pytest.mark.asyncio
async def test_demographics_and_housing_gaps(mock_llm):
    p1 = DemographicsProvider(
        {"demographics_mode": "worldbank", "allow_simulation": False}, llm_manager=mock_llm
    )
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value.status = 404
        assert await p1.extract() == []
    p2 = HousingProvider({"allow_simulation": False}, llm_manager=mock_llm)
    assert await p2.extract() == []


@pytest.mark.asyncio
async def test_labor_and_telecom_coverage(mock_llm):
    p1 = LaborProvider({"allow_simulation": False}, llm_manager=mock_llm)
    assert await p1.extract() == []
    p2 = TelecomProvider({"telecom_mode": "fcc", "allow_simulation": False}, llm_manager=mock_llm)
    with patch("aiohttp.ClientSession.get", side_effect=Exception("Boom")):
        assert await p2.extract() == []


@pytest.mark.asyncio
async def test_unstructured_provider_deep_logic(mock_llm):
    p = UnstructuredProvider(
        {"input_uri": "http://fail.com", "allow_simulation": True}, llm_manager=mock_llm
    )
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.return_value.status = 500
        artifacts = await p.extract()
        assert "CC-" in artifacts[0].id

    # File read fail
    p3 = UnstructuredProvider(
        {"input_uri": "test.txt", "allow_simulation": False}, llm_manager=mock_llm
    )
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", side_effect=Exception("Read fail")):
            assert await p3.extract() == []

    # Integrity fail
    raw = RawArtifact(id="1", source_url="x", content="x", timestamp="x", metadata={})
    mock_llm.extract_structured_data.return_value = {"revenue": -100}
    assert await p.transform([raw]) == []
