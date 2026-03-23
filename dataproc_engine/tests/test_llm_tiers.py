import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from dataproc_engine.core.llm_manager import LLMManager

@pytest.mark.asyncio
async def test_llm_tier_1_cloud_success():
    """Verify that Tier 1 (Cloud) is used when available."""
    llm = LLMManager({"llm_strategy": "cloud"})
    schema = {"test_key": "string"}
    
    with patch("os.getenv", return_value="test-key"):
        with patch("dataproc_engine.core.llm_manager.LLMManager._call_gemini", new_callable=AsyncMock) as mock_gemini:
            mock_gemini.return_value = {"test_key": "cloud_value"}
            result = await llm.extract_structured_data("some content", schema)
        
        assert result["test_key"] == "cloud_value"
        mock_gemini.assert_called_once()

@pytest.mark.asyncio
async def test_llm_tier_2_ollama_fallback():
    """Verify fallback to Tier 2 (Ollama) when Cloud fails."""
    llm = LLMManager({"llm_strategy": "auto"})
    schema = {"test_key": "string"}
    
    with patch("dataproc_engine.core.llm_manager.LLMManager._try_cloud_providers", new_callable=AsyncMock) as mock_cloud:
        mock_cloud.return_value = None # Cloud fails
        
        with patch("dataproc_engine.core.llm_manager.LLMManager._try_ollama", new_callable=AsyncMock) as mock_ollama:
            mock_ollama.return_value = {"test_key": "ollama_value"}
            result = await llm.extract_structured_data("some content", schema)
            
            assert result["test_key"] == "ollama_value"
            mock_ollama.assert_called_once()

@pytest.mark.asyncio
async def test_llm_tier_3_heuristic_fallback():
    """Verify fallback to Tier 3 (Heuristic) when both Cloud and Ollama fail."""
    llm = LLMManager({"llm_strategy": "auto"})
    schema = {"test_key": "string"}
    
    with patch("dataproc_engine.core.llm_manager.LLMManager._try_cloud_providers", new_callable=AsyncMock) as mock_cloud:
        mock_cloud.return_value = None
        
        with patch("dataproc_engine.core.llm_manager.LLMManager._try_ollama", new_callable=AsyncMock) as mock_ollama:
            mock_ollama.return_value = None
            
            # Heuristics should kick in (based on regex for "test_key: value")
            content = "test_key: heuristic_value"
            result = await llm.extract_structured_data(content, schema)
            
            assert result["test_key"] == "heuristic_value"

@pytest.mark.asyncio
async def test_sentiment_intensifiers():
    """Verify the expanded sentiment lexicon with intensifiers."""
    llm = LLMManager({"llm_strategy": "heuristic"})
    
    # 1. Neutral-Positive
    score1 = llm._heuristic_sentiment("Robust gain but we also had a loss.")
    # 2. Extremely positive
    score2 = llm._heuristic_sentiment("Extremely robust gain but we also had a loss.")
    assert score2 > score1
    
    # 3. Negative
    score_neg = llm._heuristic_sentiment("The massive loss was extremely weak.")
    assert score_neg < 0.5

@pytest.mark.asyncio
async def test_universal_sentiment_fallback():
    """Verify that sentiment uses the multi-provider fallback."""
    llm = LLMManager({"llm_strategy": "auto"})
    
    with patch("dataproc_engine.core.llm_manager.LLMManager._try_cloud_providers", new_callable=AsyncMock) as mock_cloud:
        mock_cloud.return_value = {"sentiment_score": 0.88}
        score = await llm._call_sentiment_llm("Great news!")
        assert score == 0.88


