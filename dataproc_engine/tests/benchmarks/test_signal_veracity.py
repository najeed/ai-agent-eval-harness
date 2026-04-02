import pytest
import os
import pandas as pd
from unittest.mock import patch, MagicMock
from dataproc_engine.core.correlator import DataCorrelator
from dataproc_engine.providers.telecom import TelecomProvider
from dataproc_engine.providers.unstructured_provider import UnstructuredProvider
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_correlator_edge_branches():
    """Exercise Correlator error and missing key branches."""
    correlator = DataCorrelator()
    
    # 1. Missing Secondary Dataset branch (Lines 29-43)
    results = correlator.correlate_cross_sector(
        primary_dataset=[MagicMock()],
        secondary_dataset=[], # Empty
        correlation_type="finance_health"
    )
    assert len(results) > 0 # Returns primary dataset regardless of secondary
    
    # 2. Unsupported Correlation Type (Lines 59-74)
    results_invalid = correlator.correlate_cross_sector(
        primary_dataset=[MagicMock()],
        secondary_dataset=[MagicMock()],
        correlation_type="invalid_type"
    )
    assert len(results_invalid) > 0 # Primary remains

@pytest.mark.asyncio
async def test_telecom_ookla_hit():
    """Mock Ookla performance extraction for TelecomProvider."""
    config = {"industry": "telecom", "telecom_mode": "ookla", "allow_simulation": False}
    provider = TelecomProvider(config, llm_manager=LLMManager({}))
    
    df = pd.DataFrame([{"quadkey": "123", "avg_d_kbps": 50000, "avg_u_kbps": 20000, "avg_lat_ms": 15, "tests": 10, "devices": 5}])
    with patch.object(provider, "load_raw_data", return_value=df):
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        assert any("OOKLA" in a.id for a in artifacts)
        transformed = await provider.transform(artifacts)
        assert len(transformed) > 0

@pytest.mark.asyncio
async def test_unstructured_common_crawl_hit():
    """Mock Common Crawl branch for UnstructuredProvider."""
    config = {"industry": "unstructured", "input_uri": "common_crawl://2023-01", "allow_simulation": True}
    provider = UnstructuredProvider(config, llm_manager=LLMManager({}))
    
    # Mock the Input path found check (Line 108)
    with patch("os.path.exists", return_value=True):
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        assert any("doc-" in a.id for a in artifacts) or any("CC-" in a.id for a in artifacts)
        transformed = await provider.transform(artifacts)
    assert len(transformed) > 0
    assert transformed[0].industry == "unstructured"
