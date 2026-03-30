import pytest
import pandas as pd
import os
from unittest.mock import patch, AsyncMock, MagicMock
from dataproc_engine.providers.ecommerce import EcommerceProvider
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_ecommerce_olist_production_loop(tmp_path):
    """Verify Olist (Brazil) extraction and transformation (Lines 28-129)."""
    # 1. Setup Mock Tabular Data
    df = pd.DataFrame([
        {"order_id": "ORD1", "product_id": "P1", "price": 100.0, "freight_value": 10.0, "customer_id": "C1", "order_status": "delivered", "review_score": 5}
    ])
    csv_path = str(tmp_path / "olist.csv")
    df.to_csv(csv_path, index=False)
    
    config = {
        "industry": "ecommerce",
        "ecommerce_mode": "olist",
        "input_uris": [csv_path],
        "allow_simulation": False
    }
    llm = LLMManager({"llm_provider": "heuristic"})
    provider = EcommerceProvider(config, llm_manager=llm)
    
    # 2. Extract & Transform
    artifacts = await provider.extract()
    assert len(artifacts) > 0
    results = await provider.transform(artifacts)
    
    assert len(results) == 1
    assert results[0].data["price"] == 100.0
    assert results[0].industry == "ecommerce"

@pytest.mark.asyncio
async def test_ecommerce_uci_production_loop(tmp_path):
    """Verify UCI (UK Retail) extraction and transformation (Lines 28-119)."""
    df = pd.DataFrame([
        {"InvoiceNo": "INV1", "StockCode": "S1", "Description": "Tape", "Quantity": 10, "UnitPrice": 2.5, "CustomerID": "C1", "Country": "UK"}
    ])
    csv_path = str(tmp_path / "uci.csv")
    df.to_csv(csv_path, index=False)
    
    config = {"industry": "ecommerce", "ecommerce_mode": "uci", "input_uris": [csv_path]}
    provider = EcommerceProvider(config, llm_manager=LLMManager({"llm_provider": "heuristic"}))
    
    artifacts = await provider.extract()
    results = await provider.transform(artifacts)
    assert results[0].data["invoice_no"] == "INV1"
    assert results[0].data["unit_price"] == 2.5

@pytest.mark.asyncio
async def test_ecommerce_cpi_inflation_impact():
    """Verify CPI-impact weighting for sentiment (Lines 143-147)."""
    config = {"industry": "ecommerce", "ecommerce_mode": "standard", "cpi_impact": 0.1} # 10% inflation
    llm = LLMManager({"llm_provider": "heuristic"})
    provider = EcommerceProvider(config, llm_manager=llm)
    
    # Mock LLM returning 1.0 (Positive)
    with patch.object(LLMManager, "analyze_sentiment", AsyncMock(return_value=1.0)):
        sim_data = [{"review_text": "Good", "rating": 5.0, "category": "Home"}]
        artifacts = [provider.create_simulated_artifact(id="test", content=sim_data)]
        results = await provider.transform(artifacts)
        
        # 1.0 * (1 - 0.1) = 0.9
        assert results[0].data["sentiment"] == 0.9
        assert "inflation pressure" in results[0].data["note"]

@pytest.mark.asyncio
async def test_ecommerce_web_stream_hit():
    """Verify web-streaming/text extraction (Lines 43-67)."""
    config = {"industry": "ecommerce", "ecommerce_mode": "standard", "input_uris": ["https://example.com/reviews.txt"]}
    provider = EcommerceProvider(config, llm_manager=LLMManager({}))
    
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.text = AsyncMock(return_value="Review 1\nReview 2")
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        artifacts = await provider.extract()
        assert len(artifacts) > 0
        assert "ecom-stream" in artifacts[0].id
