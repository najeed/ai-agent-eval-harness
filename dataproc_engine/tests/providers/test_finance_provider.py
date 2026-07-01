import json
from unittest.mock import MagicMock, patch

import pytest

from dataproc_engine.core.llm_manager import LLMManager
from dataproc_engine.providers.finance import FinanceProvider


class MockResponse:
    """Explicit Async Context Manager for aiohttp mocks."""

    def __init__(self, status, json_data=None):
        self.status = status
        self._json = json_data or []

    async def json(self):
        return self._json

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.mark.asyncio
async def test_finance_world_bank_logic():
    """Verify World Bank macroeconomic extraction and simulation (Lines 27-65)."""
    # 1. Successful Web Fetch
    config = {"industry": "finance", "finance_mode": "worldbank", "allow_simulation": False}
    provider = FinanceProvider(config, llm_manager=LLMManager({"llm_provider": "mock"}))

    mock_wb_data = [
        {"page": 1},
        [
            {
                "country": {"value": "USA"},
                "indicator": {"value": "GDP"},
                "value": 25000000,
                "date": "2023",
            },
            {
                "country": {"value": "CAN"},
                "indicator": {"value": "GDP"},
                "value": 2000000,
                "date": "2023",
            },
        ],
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


@pytest.mark.asyncio
async def test_finance_extraction_failures_and_missing_sim_files():
    """
    Cover WB fail logs (60-61), SEC fail (199-201),
    non-existent mock file fallbacks (76, 132).
    """
    # 1. WB extract fail log (60-61) and fallback to inline mock (76)
    config_wb = {"industry": "finance", "finance_mode": "worldbank", "allow_simulation": True}
    provider_wb = FinanceProvider(config_wb, llm_manager=LLMManager({}))

    with (
        patch.object(provider_wb, "request_with_retry", side_effect=Exception("Connection lost")),
        patch("os.path.exists", return_value=False),  # Ensure mock file doesn't exist
    ):
        artifacts = await provider_wb.extract()
        assert len(artifacts) == 1
        assert artifacts[0].content[1][0]["country"]["value"] == "United States"

    # 2. Credit Risk extract simulation missing file (132)
    config_cr = {"industry": "finance", "finance_mode": "credit_risk", "allow_simulation": True}
    provider_cr = FinanceProvider(config_cr, llm_manager=LLMManager({}))
    with patch("os.path.exists", return_value=False):
        artifacts = await provider_cr.extract()
        assert len(artifacts) == 1
        assert artifacts[0].content[0]["LIMIT_BAL"] == 20000

    # 3. Credit Risk simulation disabled (166)
    config_cr_no_sim = {
        "industry": "finance",
        "finance_mode": "credit_risk",
        "allow_simulation": False,
    }
    provider_cr_no_sim = FinanceProvider(config_cr_no_sim, llm_manager=LLMManager({}))
    artifacts = await provider_cr_no_sim.extract()
    assert len(artifacts) == 0

    # 4. SEC EDGAR fetch failure logs (199-201)
    config_sec = {
        "industry": "finance",
        "finance_mode": "sec_edgar",
        "allow_simulation": False,
        "ciks": ["0000320193"],
    }
    provider_sec = FinanceProvider(config_sec, llm_manager=LLMManager({}))
    with patch.object(provider_sec, "request_with_retry", side_effect=Exception("SEC blocks IP")):
        artifacts = await provider_sec.extract()
        assert len(artifacts) == 0

    # 5. SEC EDGAR mock file loading (218-219)
    config_sec_sim = {
        "industry": "finance",
        "finance_mode": "sec_edgar",
        "allow_simulation": True,
        "ciks": ["0000320193"],
    }
    provider_sec_sim = FinanceProvider(config_sec_sim, llm_manager=LLMManager({}))
    mock_file_content = json.dumps({"0000320193": {"entityName": "Mock SEC Company"}})
    mock_file = MagicMock()
    mock_file.__enter__.return_value.read.return_value = mock_file_content
    with (
        patch("aiohttp.ClientSession.get", side_effect=Exception("Offline")),
        patch("os.path.exists", return_value=True),
        patch("builtins.open", return_value=mock_file),
        patch("asyncio.sleep", return_value=None),
    ):
        artifacts = await provider_sec_sim.extract()
        assert len(artifacts) == 1
        assert artifacts[0].metadata["company"] == "Mock SEC Company"

    # 6. Transform non-list World Bank raw artifact (306)
    from dataproc_engine.core.base_provider import RawArtifact

    raw_non_list = RawArtifact(
        id="WB-test",
        source_url="http://wb",
        content={"page": 1},  # not a list
        metadata={"simulation": True},
        timestamp="2026-06-30T00:00:00Z",
    )
    # Under mock strategy (is_strict = False)
    provider_wb.llm_manager.strategy = "mock"
    transformed = await provider_wb.transform([raw_non_list])
    assert len(transformed) == 1  # wrapped into [content], processed successfully
