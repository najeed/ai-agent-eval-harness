import pytest
import os
import pandas as pd
from unittest.mock import patch, AsyncMock, MagicMock
from dataproc_engine.providers.agriculture import AgricultureProvider
from dataproc_engine.providers.finance import FinanceProvider
from dataproc_engine.providers.healthcare import HealthcareProvider
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_agriculture_api_deep_hit():
    """Mock USDA QuickStats API for AgricultureProvider coverage."""
    config = {"industry": "agriculture", "usda_api_key": "MOCK", "allow_simulation": False}
    provider = AgricultureProvider(config, llm_manager=LLMManager({}))
    
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = {"data": [{"commodity_desc": "CORN", "year": 2023, "value": "150", "unit_desc": "BUSHELS / ACRE"}]}
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        transformed = await provider.transform(artifacts)
        assert len(transformed) > 0

@pytest.mark.asyncio
async def test_finance_credit_risk_hit():
    """Mock UCI Credit Risk XLS loading."""
    config = {"industry": "finance", "schema_type": "credit_risk", "allow_simulation": False}
    provider = FinanceProvider(config, llm_manager=LLMManager({}))
    
    # Mock load_raw_data to return a DataFrame
    df = pd.DataFrame([{"ID": 1, "LIMIT_BAL": 20000, "SEX": 2, "EDUCATION": 2, "MARRIAGE": 1, "AGE": 24, "PAY_0": 2, "BILL_AMT1": 3913, "PAY_AMT1": 0, "default.payment.next.month": 1}])
    with patch.object(provider, "load_raw_data", return_value=df):
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        transformed = await provider.transform(artifacts)
        assert len(transformed) > 0

@pytest.mark.asyncio
async def test_healthcare_cms_hit_hardened():
    """Mock CMS API with correct schema keys for HealthcareProvider."""
    config = {"industry": "healthcare", "schema_type": "cms", "allow_simulation": True}
    provider = HealthcareProvider(config, llm_manager=LLMManager({"llm_provider": "heuristic"}))
    
    # CMS expected keys: "Hospital Name", "Provider ID"
    content = [{"Hospital Name": "TEST CLINIC", "Provider ID": "123", "Hospital overall rating": 4}]
    
    with patch("os.path.exists", return_value=True):
        with patch("pandas.read_csv", return_value=pd.DataFrame(content)):
            artifacts = await provider.extract()
            assert len(artifacts) > 0
            transformed = await provider.transform(artifacts)
            results = transformed
            assert len(results) > 0
            assert results[0].data["facility_name"] == "TEST CLINIC"

@pytest.mark.asyncio
async def test_unstructured_ocr_fail_branches_hardened():
    """Test OCR failure branches in UnstructuredProvider with mock sys.modules."""
    from dataproc_engine.providers.unstructured_provider import UnstructuredProvider
    config = {"industry": "unstructured", "input_uri": "test.png", "allow_simulation": False}
    provider = UnstructuredProvider(config, llm_manager=LLMManager({}))
    
    with patch("os.path.exists", return_value=True):
        m_open = MagicMock()
        m_open.return_value.__enter__.return_value.read.return_value = "RAW TEXT CONTENT"
        with patch("builtins.open", m_open):
            # Mock presence of pytesseract and easyocr
            with patch.dict("sys.modules", {"pytesseract": MagicMock(), "easyocr": MagicMock()}):
                import pytesseract
                import easyocr
                with patch("pytesseract.image_to_string", side_effect=Exception("No Tesseract")):
                    mock_reader = MagicMock()
                    mock_reader.readtext.return_value = [([0,0,1,1], "OCR TEXT", 0.99)]
                    with patch("easyocr.Reader", return_value=mock_reader):
                        artifacts = await provider.extract()
                        assert len(artifacts) > 0
                        assert "OCR TEXT" in artifacts[0].content
