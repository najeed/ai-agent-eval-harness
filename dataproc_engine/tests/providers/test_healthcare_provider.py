from unittest.mock import patch

import pytest

from dataproc_engine.core.base_provider import StandardSchema
from dataproc_engine.core.llm_manager import LLMManager
from dataproc_engine.providers.healthcare import HealthcareProvider


class MockResponse:
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
async def test_healthcare_who_logic_and_failures():
    """Verify WHO extraction logic, failures (56-57), and missing mock simulation (72)."""
    # 1. Successful GHO Fetch
    config = {
        "industry": "healthcare",
        "healthcare_mode": "who",
        "allow_simulation": False,
        "indicator": "WHOSIS_000001",
    }
    provider = HealthcareProvider(config, llm_manager=LLMManager({"llm_strategy": "mock"}))

    mock_who_data = {"value": [{"SpatialDim": "USA", "NumericValue": 78.5, "TimeDim": "2021"}]}

    with patch("aiohttp.ClientSession.get", return_value=MockResponse(200, mock_who_data)):
        artifacts = await provider.extract()
        assert len(artifacts) == 1
        transformed = await provider.transform(artifacts)
        assert len(transformed) == 1
        assert transformed[0].data["country"] == "USA"

    # 2. WHO API failure (56-57) & missing mock file fallback (72)
    config_sim = {
        "industry": "healthcare",
        "healthcare_mode": "who",
        "allow_simulation": True,
        "indicator": "WHOSIS_000001",
    }
    provider_sim = HealthcareProvider(config_sim, llm_manager=LLMManager({}))
    # Mock request_with_retry to raise exception directly to trigger line 56-57 exception block
    with (
        patch.object(provider_sim, "request_with_retry", side_effect=Exception("API offline")),
        patch("os.path.exists", return_value=False),
        patch("asyncio.sleep", return_value=None),
    ):
        artifacts = await provider_sim.extract()
        assert len(artifacts) == 1
        assert artifacts[0].content[0]["SpatialDim"] == "USA"


@pytest.mark.asyncio
async def test_healthcare_clinical_and_cms_fallbacks():
    """
    Verify Clinical missing mock (131), simulation disabled (162, 206),
    and CMS failure (219-221).
    """
    # 1. Clinical missing mock file (131)
    config_clin = {
        "industry": "healthcare",
        "healthcare_mode": "clinical",
        "allow_simulation": True,
    }
    provider_clin = HealthcareProvider(config_clin, llm_manager=LLMManager({}))
    with patch("os.path.exists", return_value=False):
        artifacts = await provider_clin.extract()
        assert len(artifacts) == 1
        assert artifacts[0].content[0]["subject_id"] == "1001"

    # 2. Clinical simulation disabled (162)
    config_clin_no_sim = {
        "industry": "healthcare",
        "healthcare_mode": "clinical",
        "allow_simulation": False,
    }
    provider_clin_no_sim = HealthcareProvider(config_clin_no_sim, llm_manager=LLMManager({}))
    artifacts = await provider_clin_no_sim.extract()
    assert len(artifacts) == 0

    # 3. CMS simulation disabled (206)
    config_cms_no_sim = {
        "industry": "healthcare",
        "healthcare_mode": "cms",
        "allow_simulation": False,
        "input_uris": ["non_existent_cms.csv"],
    }
    provider_cms_no_sim = HealthcareProvider(config_cms_no_sim, llm_manager=LLMManager({}))
    # Return True for p check (231), then False for path exists (172)
    exists_calls = [True, False]
    with patch(
        "os.path.exists",
        side_effect=lambda p: exists_calls.pop(0) if exists_calls else False,
    ):
        artifacts = await provider_cms_no_sim.extract()
        assert len(artifacts) == 0

    # 4. CMS extraction exception handler (219-221)
    config_cms_fail = {
        "industry": "healthcare",
        "healthcare_mode": "cms",
        "allow_simulation": True,
        "input_uris": ["corrupt_cms.csv"],
    }
    provider_cms_fail = HealthcareProvider(config_cms_fail, llm_manager=LLMManager({}))
    # Return True for p check (231), then raise exception in read_csv
    with (
        patch("os.path.exists", return_value=True),
        patch("pandas.read_csv", side_effect=Exception("Corrupted spreadsheet")),
    ):
        artifacts = await provider_cms_fail.extract()
        assert len(artifacts) == 0


def test_healthcare_validation_and_ratings():
    """Verify validate() rating checks (407-410)."""
    provider = HealthcareProvider({"industry": "healthcare"}, llm_manager=LLMManager({}))

    # 1. Successful validation
    record_ok = StandardSchema(
        id="hc1",
        industry="healthcare",
        data={
            "facility_name": "General Clinic",
            "provider_id": "1",
            "overall_rating": 4,
            "mortality_metric": "Same",
        },
        provenance={},
        checksum="hash",
    )
    assert provider.validate([record_ok]) is True

    # 2. Missing facility name validation failure (407-410)
    record_fail = StandardSchema(
        id="hc2",
        industry="healthcare",
        data={
            "facility_name": None,
            "provider_id": "2",
            "overall_rating": 5,
        },
        provenance={},
        checksum="hash",
    )
    assert provider.validate([record_fail]) is False
