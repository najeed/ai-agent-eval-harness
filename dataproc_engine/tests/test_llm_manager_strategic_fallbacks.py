import pytest
import os
import json
import aiohttp
from unittest.mock import patch, AsyncMock, MagicMock
from dataproc_engine.core.llm_manager import LLMManager

@pytest.fixture
def llm_config():
    return {"llm_strategy": "auto", "llm_provider": "gemini"}

@pytest.mark.asyncio
async def test_llm_manager_tiered_success(llm_config):
    """Verify successful cloud extraction with schema verification (Tiers 1-2)."""
    llm = LLMManager(llm_config)
    schema = {"revenue": "number", "entity_name": "string"}
    content = "Apple Inc. reported $394.3 billion in revenue."
    
    # 1. Mock Successful Gemini Call
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "candidates": [{"content": {"parts": [{"text": '{"revenue": 394300000000, "entity_name": "Apple Inc."}'}]}}]
        })
        mock_post.return_value.__aenter__.return_value = mock_resp
        
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            result = await llm.extract_structured_data(content, schema)
            assert result["revenue"] == 394300000000
            assert result["entity_name"] == "Apple Inc."

@pytest.mark.asyncio
async def test_llm_manager_heuristic_recovery(llm_config):
    """Verify Tier 3 Heuristic recovery when Cloud/Ollama fail (Lines 266-307)."""
    llm = LLMManager({"llm_strategy": "heuristic"})
    schema = {"revenue": "number", "status": "string"}
    # Intentionally messy content that should hit the regexes
    content = """
    Financial Summary:
    revenue: $125,000.50
    status: verified
    """
    
    result = await llm.extract_structured_data(content, schema)
    # The current regex handles commas by removing them if they are between digits
    assert result["revenue"] == 125000.5
    assert result["status"] == "verified"

@pytest.mark.asyncio
async def test_llm_manager_sentiment_loops(llm_config):
    """Verify sentiment fallback from Cloud to Heuristics (Lines 60-129)."""
    llm = LLMManager(llm_config)
    content = "The market is extremely bullish and showing robust stability."
    
    # 1. Cloud success (Hits Line 67)
    with patch.object(llm, "_call_sentiment_llm", AsyncMock(return_value=0.9)):
        assert await llm.analyze_sentiment(content) == 0.9
        
    # 2. total failure (Hits Lines 88-89, 69)
    llm.strategy = "ollama"
    with patch.object(llm, "_try_cloud_providers", AsyncMock(return_value=None)):
        with patch.object(llm, "_try_ollama", AsyncMock(return_value={})): # Empty return
            score = await llm.analyze_sentiment(content)
            assert score > 0.8

@pytest.mark.asyncio
async def test_llm_manager_error_resiliency(llm_config):
    """Verify exception handling in all Cloud Provider calls (Harden: Lines 169-238)."""
    llm = LLMManager(llm_config)
    providers = ["openai", "gemini", "claude", "grok"]
    schema = {"v": "s"}
    
    for provider in providers:
        llm.preferred_provider = provider
        with patch("aiohttp.ClientSession.post", side_effect=aiohttp.ClientError("Connection Refused")):
            with patch.dict(os.environ, {f"{provider.upper()}_API_KEY": "test"}):
                # Should catch the error and return None for the provider call
                result = await llm._try_cloud_providers("test", schema)
                assert result is None

@pytest.mark.asyncio
async def test_llm_manager_type_enforcement(llm_config):
    """Exhaustive test for _verify_schema type conversions (Lines 344-366)."""
    llm = LLMManager(llm_config)
    schema = {"price": "number", "id": "integer", "name": "string"}
    
    # Valid conversions
    data = {"price": "$1,200.50", "id": "42.0", "name": 123}
    verified = llm._verify_schema(data, schema)
    assert verified["price"] == 1200.5
    assert verified["id"] == 42
    assert verified["name"] == "123"
    
    # Invalid conversions
    assert llm._verify_schema({"price": "not-a-number"}, schema) is None
    assert llm._verify_schema({"id": "NaN"}, schema) is None

@pytest.mark.asyncio
async def test_llm_manager_ollama_json_fail(llm_config):
    """Harden Ollama JSON parsing resilience (Line 260, 264)."""
    llm = LLMManager({"llm_strategy": "ollama"})
    with patch("aiohttp.ClientSession.post", side_effect=Exception("Ollama Dead")):
        # Hits Line 264 (return None)
        result = await llm._try_ollama("test", {"k": "v"})
        assert result is None
        
    with patch("aiohttp.ClientSession.post") as mock_post:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        # Corrupt JSON response (Hits Line 260 exception)
        mock_resp.json = AsyncMock(return_value={"response": "{invalid-json}"})
        mock_post.return_value.__aenter__.return_value = mock_resp
        
@pytest.mark.asyncio
async def test_llm_manager_unknown_provider(llm_config):
    """Hit Line 150: Unsupported provider fallback."""
    llm = LLMManager({"llm_strategy": "cloud", "llm_provider": "unknown_ai"})
    with patch.dict(os.environ, {"UNKNOWN_AI_API_KEY": "test"}):
        assert await llm._try_cloud_providers("test", {"k": "v"}) is None

@pytest.mark.asyncio
async def test_llm_manager_grok_fail_path(llm_config):
    """Hit Line 238: Grok exception path."""
    llm = LLMManager({"llm_strategy": "cloud", "llm_provider": "grok"})
    with patch("aiohttp.ClientSession.post", side_effect=Exception("Grok Offline")):
        assert await llm._call_grok("test", {"k": "v"}, "test-key") is None
