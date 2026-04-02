import pytest
import os
from unittest.mock import patch, AsyncMock, MagicMock
from dataproc_engine.providers.energy import EnergyProvider
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_energy_api_success_and_failures():
    """Mock the EIA API to hit the 108-146 line block for 90%+ coverage."""
    config = {"industry": "energy", "eia_api_key": "TEST_KEY", "allow_simulation": False}
    llm = LLMManager({})
    provider = EnergyProvider(config, llm_manager=llm)
    
    with patch("aiohttp.ClientSession.get") as mock_get:
        # 1. Test API Success (200)
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = {
            "series": [{
                "name": "Crude Oil Price",
                "units": "USD",
                "data": [["2023-01-01", 80.5], ["2023-01-02", 79.2]]
            }]
        }
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        assert artifacts[0].metadata["series_name"] == "Crude Oil Price"

        # 2. Test API Failure (500)
        mock_resp.status = 500
        fail_artifacts = await provider.extract()
        assert len(fail_artifacts) == 0

@pytest.mark.asyncio
async def test_unstructured_ocr_and_pdf_mock_hardened():
    """Mock PDF and OCR dependencies for UnstructuredProvider (Hardened)."""
    from dataproc_engine.providers.unstructured_provider import UnstructuredProvider
    config = {"industry": "unstructured", "input_uri": "test.pdf", "allow_simulation": True}
    provider = UnstructuredProvider(config, llm_manager=LLMManager({}))
    
    # 1. Mock File Exists and PDF Content
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", MagicMock()):
            with patch("pypdf.PdfReader") as mock_pdf:
                mock_reader = MagicMock()
                mock_reader.pages = [MagicMock(extract_text=lambda: "Extracted PDF Text")]
                mock_pdf.return_value = mock_reader
                
                raw = await provider.extract()
                assert len(raw) > 0
                assert "Extracted PDF Text" in raw[0].content
