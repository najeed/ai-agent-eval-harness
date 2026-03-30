import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from dataproc_engine.providers.telecom import TelecomProvider
from dataproc_engine.core.llm_manager import LLMManager

class MockResponse:
    """Explicit Async Context Manager for aiohttp mocks."""
    def __init__(self, status, json_data=None):
        self.status = status
        self._json = json_data or {}
    async def json(self): return self._json
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass

@pytest.mark.asyncio
async def test_telecom_itu_production_loop():
    """Verify ITU ICT Statistics transformation (Lines 147-166)."""
    config = {"industry": "telecom", "telecom_mode": "itu", "allow_simulation": True}
    provider = TelecomProvider(config, llm_manager=LLMManager({"llm_provider": "heuristic"}))
    
    artifacts = await provider.extract()
    assert len(artifacts) > 0
    results = await provider.transform(artifacts)
    
    assert len(results) > 0
    assert results[0].data["usage_value"] > 0
    assert results[0].provenance["provider"] == "ITU"

@pytest.mark.asyncio
async def test_telecom_ookla_production_loop(tmp_path):
    """Verify Ookla Speedtest Tile transformation (Lines 168-195)."""
    df = pd.DataFrame([
        {"quadkey": "02313013", "avg_d_kbps": 150000, "avg_u_kbps": 50000, "avg_lat_ms": 10, "tests": 100}
    ])
    csv_path = str(tmp_path / "ookla.csv")
    df.to_csv(csv_path, index=False)
    
    config = {"industry": "telecom", "telecom_mode": "ookla", "input_uri": csv_path}
    provider = TelecomProvider(config, llm_manager=LLMManager({"llm_provider": "heuristic"}))
    
    artifacts = await provider.extract()
    results = await provider.transform(artifacts)
    
    assert len(results) == 1
    assert results[0].data["avg_download_speed"] == 150.0 # 150000 / 1000
    assert "Ookla" in results[0].provenance["schema"]

@pytest.mark.asyncio
async def test_telecom_fcc_api_retry_and_simulation():
    """Verify FCC API failure and simulation fallbacks (Lines 103-140)."""
    config = {"industry": "telecom", "telecom_mode": "fcc", "allow_simulation": True}
    provider = TelecomProvider(config, llm_manager=LLMManager({"llm_provider": "heuristic"}))
    
    # 1. API Failure triggers simulated fallback within fetch_fcc
    with patch("aiohttp.ClientSession.get", return_value=MockResponse(500)):
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        assert "fcc-stream" in artifacts[0].id
        results = await provider.transform(artifacts)
        assert results[0].data["download_speed"] == 1000.0

@pytest.mark.asyncio
async def test_telecom_validation_branches():
    """Exercise Ookla/ITU validation logic (Lines 241-252)."""
    provider = TelecomProvider({"telecom_mode": "ookla"}, llm_manager=LLMManager({}))
    bad_record = MagicMock(data={"avg_download_speed": -10.0})
    assert provider.validate([bad_record]) is False
    
    provider.telecom_mode = "itu"
    bad_record_itu = MagicMock(data={"usage_value": -1.0})
    assert provider.validate([bad_record_itu]) is False
